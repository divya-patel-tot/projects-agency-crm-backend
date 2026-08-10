"""Post-project retention eligibility — call/email follow-ups only after delivery."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError
from app.db.enums import ProjectStatus, SequenceTriggerType, TouchpointChannel
from app.db.models.project import Project

INCOMPLETE_PROJECT_STATUSES = {
    ProjectStatus.PLANNING.value,
    ProjectStatus.ACTIVE.value,
    ProjectStatus.ON_HOLD.value,
}

RETENTION_CHANNELS = {
    TouchpointChannel.EMAIL.value,
    TouchpointChannel.CALL.value,
}

RETENTION_TRIGGER_TYPES = {
    SequenceTriggerType.MANUAL.value,
    SequenceTriggerType.ON_PROJECT_COMPLETED.value,
}


@dataclass(frozen=True)
class RetentionEligibility:
    eligible: bool
    reason: str | None
    completed_project_count: int
    incomplete_project_count: int
    blocking_projects: tuple[tuple[UUID, str, str], ...]


async def _company_projects(db: AsyncSession, company_id: UUID) -> list[Project]:
    result = await db.execute(
        select(Project)
        .where(Project.company_id == company_id, Project.deleted_at.is_(None))
        .order_by(Project.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_company_retention_eligibility(db: AsyncSession, company_id: UUID) -> RetentionEligibility:
    projects = await _company_projects(db, company_id)
    completed = [p for p in projects if p.status == ProjectStatus.COMPLETED.value]
    incomplete = [p for p in projects if p.status in INCOMPLETE_PROJECT_STATUSES]
    blocking = tuple((p.id, p.name, p.status) for p in incomplete)

    if not completed:
        return RetentionEligibility(
            eligible=False,
            reason=(
                "Retention unlocks after at least one project is completed end-to-end. "
                "Finish active delivery work first."
            ),
            completed_project_count=0,
            incomplete_project_count=len(incomplete),
            blocking_projects=blocking,
        )

    if incomplete:
        names = ", ".join(p.name for p in incomplete)
        return RetentionEligibility(
            eligible=False,
            reason=f"Finish in-progress projects before starting retention follow-ups: {names}.",
            completed_project_count=len(completed),
            incomplete_project_count=len(incomplete),
            blocking_projects=blocking,
        )

    return RetentionEligibility(
        eligible=True,
        reason=None,
        completed_project_count=len(completed),
        incomplete_project_count=0,
        blocking_projects=(),
    )


async def assert_company_retention_eligible(db: AsyncSession, company_id: UUID) -> RetentionEligibility:
    eligibility = await get_company_retention_eligibility(db, company_id)
    if not eligibility.eligible:
        raise DomainError(
            eligibility.reason or "Retention is not available for this client yet.",
            code="conflict",
        )
    return eligibility


def assert_retention_channel(channel: str) -> None:
    normalized = str(channel).lower()
    if normalized not in RETENTION_CHANNELS:
        raise DomainError(
            "Retention steps must be follow-up calls or emails only — no meetings or project tasks.",
            code="validation_error",
        )


def assert_retention_trigger(trigger_type: str) -> None:
    normalized = str(trigger_type).lower()
    if normalized not in RETENTION_TRIGGER_TYPES:
        raise DomainError(
            "Retention sequences only support manual enrollment or automatic start when a project completes.",
            code="validation_error",
        )


async def get_latest_completed_project_id(db: AsyncSession, company_id: UUID) -> UUID | None:
    result = await db.execute(
        select(Project.id)
        .where(
            Project.company_id == company_id,
            Project.deleted_at.is_(None),
            Project.status == ProjectStatus.COMPLETED.value,
        )
        .order_by(Project.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def assert_completed_project_for_company(
    db: AsyncSession,
    *,
    company_id: UUID,
    project_id: UUID,
) -> None:
    project = await db.get(Project, project_id)
    if (
        project is None
        or project.deleted_at is not None
        or project.company_id != company_id
        or project.status != ProjectStatus.COMPLETED.value
    ):
        raise DomainError(
            "Enrollment must link to a completed project for this client.",
            code="validation_error",
        )
