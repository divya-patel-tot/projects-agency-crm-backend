"""Weighted client health score calculation — numeric score only; GROQ is advisory text."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ChangeRequestStatus, CompanyStatus, ProjectHealth, TouchpointOutcome
from app.db.models.change_request import ChangeRequest
from app.db.models.client_health import ClientHealthScore
from app.db.models.company import Company
from app.db.models.contact import Contact
from app.db.models.project import Project
from app.db.models.retention import Touchpoint
from app.db.models.user import User
from app.graphql.contracts.repository import list_contracts
from app.graphql.notifications.service import notify
from app.graphql.health.repository import (
    insert_health_score,
    list_at_risk_companies,
    list_companies_for_scoring,
    list_health_history,
)
from app.graphql.org_settings import HealthOrgSettings, health_settings_from_dict
from app.graphql.retention.eligibility import get_company_retention_eligibility
from app.integrations.groq_client import generate_text

OPEN_CR_STATUSES = [
    ChangeRequestStatus.SUBMITTED.value,
    ChangeRequestStatus.UNDER_REVIEW.value,
    ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
    ChangeRequestStatus.PENDING_APPROVAL.value,
    ChangeRequestStatus.APPROVED.value,
    ChangeRequestStatus.IN_PROGRESS.value,
]

_PROJECT_HEALTH_POINTS = {
    ProjectHealth.ON_TRACK.value: 100.0,
    ProjectHealth.AT_RISK.value: 50.0,
    ProjectHealth.DELAYED.value: 25.0,
}

_TOUCHPOINT_OUTCOME_POINTS = {
    TouchpointOutcome.POSITIVE.value: 100.0,
    TouchpointOutcome.NEUTRAL.value: 70.0,
    TouchpointOutcome.AT_RISK.value: 30.0,
}

_COMPANY_STATUS_POINTS = {
    CompanyStatus.ACTIVE.value: 100.0,
    CompanyStatus.PAUSED.value: 50.0,
    CompanyStatus.LEAD.value: 70.0,
    CompanyStatus.CHURNED.value: 0.0,
}


@dataclass(frozen=True)
class FactorResult:
    key: str
    value: float
    weight: float
    detail: str


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _open_cr_score(open_count: int) -> tuple[float, str]:
    if open_count == 0:
        return 100.0, "No open change requests"
    if open_count == 1:
        return 80.0, "1 open change request"
    if open_count == 2:
        return 60.0, "2 open change requests"
    return 40.0, f"{open_count} open change requests"


def _contract_factor_score(
    *,
    contracts: list,
    today: date,
    renewal_window_days: int,
) -> tuple[float, str]:
    active = [c for c in contracts if c.status == "active" and c.end_date >= today]
    if not active:
        return 60.0, "No active contract on file"

    nearest = min(active, key=lambda c: c.end_date)
    days_left = (nearest.end_date - today).days
    if days_left > renewal_window_days:
        return 100.0, f"Contract renews in {days_left} days"

    # Linear scale inside renewal window: 50 at day 0, 100 at window edge
    ratio = days_left / max(renewal_window_days, 1)
    value = 50.0 + (50.0 * ratio)
    return _clamp(value), f"Contract ends in {days_left} days (renewal window)"


async def compute_company_health_factors(
    db: AsyncSession,
    *,
    company: Company,
    settings: HealthOrgSettings,
    today: date | None = None,
) -> tuple[float, dict]:
    today = today or date.today()
    cutoff = datetime.now(UTC) - timedelta(days=90)

    project_rows = await db.execute(
        select(Project).where(
            Project.company_id == company.id,
            Project.deleted_at.is_(None),
            Project.status == "active",
        )
    )
    projects = list(project_rows.scalars().all())
    if projects:
        project_values = [_PROJECT_HEALTH_POINTS.get(p.health, 75.0) for p in projects]
        project_value = sum(project_values) / len(project_values)
        on_track = sum(1 for p in projects if p.health == ProjectHealth.ON_TRACK.value)
        project_detail = f"{on_track}/{len(projects)} active projects on track"
    else:
        project_value = 75.0
        project_detail = "No active projects (neutral default)"

    tp_rows = await db.execute(
        select(Touchpoint).where(
            Touchpoint.company_id == company.id,
            Touchpoint.completed_at.is_not(None),
            Touchpoint.completed_at >= cutoff,
        )
    )
    touchpoints = list(tp_rows.scalars().all())
    if touchpoints:
        tp_values = [_TOUCHPOINT_OUTCOME_POINTS.get(tp.outcome or TouchpointOutcome.NEUTRAL.value, 70.0) for tp in touchpoints]
        touchpoint_value = sum(tp_values) / len(tp_values)
        touchpoint_detail = f"{len(touchpoints)} touchpoints in last 90 days"
    else:
        touchpoint_value = 70.0
        touchpoint_detail = "No recent touchpoints (neutral default)"

    cr_count = (
        await db.execute(
            select(func.count())
            .select_from(ChangeRequest)
            .join(Project, ChangeRequest.project_id == Project.id)
            .where(
                Project.company_id == company.id,
                ChangeRequest.deleted_at.is_(None),
                ChangeRequest.status.in_(OPEN_CR_STATUSES),
            )
        )
    ).scalar_one()
    cr_value, cr_detail = _open_cr_score(int(cr_count))

    contracts = await list_contracts(db, company_id=company.id)
    contract_value, contract_detail = _contract_factor_score(
        contracts=contracts,
        today=today,
        renewal_window_days=settings.contract_renewal_window_days,
    )

    status_value = _COMPANY_STATUS_POINTS.get(company.status, 70.0)
    status_detail = f"Company status: {company.status}"

    factors = [
        FactorResult("project_health", project_value, settings.weight_project_health, project_detail),
        FactorResult("touchpoints", touchpoint_value, settings.weight_touchpoints, touchpoint_detail),
        FactorResult("change_requests", cr_value, settings.weight_change_requests, cr_detail),
        FactorResult("contract", contract_value, settings.weight_contract, contract_detail),
        FactorResult("company_status", status_value, settings.weight_company_status, status_detail),
    ]

    score = sum(f.value * f.weight for f in factors)
    factors_dict = {
        f.key: {"value": round(f.value, 2), "weight": f.weight, "detail": f.detail} for f in factors
    }
    return round(_clamp(score), 2), factors_dict


async def maybe_generate_ai_summary(score: float, factors: dict, company_name: str) -> str | None:
    prompt = (
        f"Write one short advisory paragraph (max 3 sentences) summarizing client health for '{company_name}'. "
        f"Overall score: {score}/100. Factor breakdown: {factors}. "
        "This is advisory only for an account manager — do not prescribe automatic actions."
    )
    return await generate_text(prompt, timeout=5)


async def record_company_health_score(
    db: AsyncSession,
    *,
    company: Company,
    settings: HealthOrgSettings,
    today: date | None = None,
    include_ai: bool = True,
) -> ClientHealthScore:
    previous_score = company.health_score
    score, factors = await compute_company_health_factors(db, company=company, settings=settings, today=today)
    ai_summary = None
    if include_ai:
        ai_summary = await maybe_generate_ai_summary(score, factors, company.name)

    now = datetime.now(UTC)
    row = ClientHealthScore(
        org_id=company.org_id,
        company_id=company.id,
        score=score,
        factors=factors,
        ai_summary=ai_summary,
        calculated_at=now,
    )
    await insert_health_score(db, row)
    company.health_score = score
    await db.flush()

    just_became_at_risk = score < settings.at_risk_threshold and (
        previous_score is None or previous_score >= settings.at_risk_threshold
    )
    if just_became_at_risk and company.account_owner_id:
        owner = await db.get(User, company.account_owner_id)
        if owner is not None and owner.deleted_at is None:
            await notify(
                db,
                org_id=company.org_id,
                recipient=owner,
                category="project_updates",
                type_="company_at_risk",
                title=f"{company.name} is now at risk",
                message=(
                    f"{company.name}'s health score dropped to {score:.0f}, "
                    f"below the at-risk threshold of {settings.at_risk_threshold:.0f}."
                ),
                link=f"/companies/{company.id}",
            )

    return row


async def recalculate_org_health_scores(
    db: AsyncSession,
    *,
    org_settings: HealthOrgSettings,
    today: date | None = None,
    include_ai: bool = True,
) -> int:
    count = 0
    for company in await list_companies_for_scoring(db):
        await record_company_health_score(
            db,
            company=company,
            settings=org_settings,
            today=today,
            include_ai=include_ai,
        )
        count += 1
    return count


async def get_at_risk_companies(
    db: AsyncSession,
    *,
    threshold: float | None = None,
    org_settings: HealthOrgSettings | None = None,
) -> list[Company]:
    settings = org_settings or HealthOrgSettings()
    effective_threshold = threshold if threshold is not None else settings.at_risk_threshold
    rows = await list_at_risk_companies(db, threshold=effective_threshold)
    eligible: list[Company] = []
    for company in rows:
        eligibility = await get_company_retention_eligibility(db, company.id)
        if eligibility.eligible:
            eligible.append(company)
    return eligible


async def get_company_health_history(db: AsyncSession, *, company_id: UUID, limit: int = 30) -> list[ClientHealthScore]:
    return await list_health_history(db, company_id=company_id, limit=limit)


async def get_primary_contact(db: AsyncSession, company_id: UUID) -> Contact | None:
    result = await db.execute(
        select(Contact).where(
            Contact.company_id == company_id,
            Contact.deleted_at.is_(None),
            Contact.is_primary.is_(True),
        )
    )
    return result.scalar_one_or_none()
