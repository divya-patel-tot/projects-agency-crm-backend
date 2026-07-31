import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.db import AsyncSessionLocal, get_tenant_db
from app.core.security import hash_password
from app.db.enums import ContractStatus, ProjectHealth, SequenceTriggerType, TouchpointChannel
from app.db.models.company import Company
from app.db.models.contact import Contact
from app.db.models.contract import Contract
from app.db.models.organization import Organization
from app.db.models.project import Project
from app.db.models.retention import RetentionSequence, RetentionSequenceStep
from app.db.models.user import User
from app.graphql.health.service import (
    compute_company_health_factors,
    get_at_risk_companies,
    record_company_health_score,
)
from app.graphql.org_settings import HealthOrgSettings
from app.graphql.retention.repository import has_active_enrollment_for_sequence
from app.scheduler.jobs import contract_renewal_check, recalculate_health_scores


async def _seed_health_fixture() -> dict:
    org_id = uuid.uuid4()
    company_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    project_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_id, name="Health Org", plan="trial", settings={}))

    async with get_tenant_db(org_id) as db:
        db.add(Company(id=company_id, org_id=org_id, name="Acme", status="active"))
        db.add(
            User(
                id=user_id,
                org_id=org_id,
                name="AM",
                email="am-health@example.com",
                password_hash=hash_password("ChangeMe123!"),
                role="account_manager",
                status="active",
            )
        )
        await db.flush()
        db.add(
            Contact(
                id=contact_id,
                org_id=org_id,
                company_id=company_id,
                first_name="Pat",
                last_name="Lee",
                email="pat@acme.com",
                is_primary=True,
                status="active",
            )
        )
        db.add(
            Project(
                id=project_id,
                org_id=org_id,
                company_id=company_id,
                name="Main",
                status="active",
                health=ProjectHealth.ON_TRACK.value,
            )
        )

    return {
        "org_id": org_id,
        "company_id": company_id,
        "contact_id": contact_id,
        "project_id": project_id,
        "user_id": user_id,
    }


@pytest.mark.asyncio
async def test_compute_health_score_hand_calculated():
    data = await _seed_health_fixture()
    settings = HealthOrgSettings()

    async with get_tenant_db(data["org_id"]) as db:
        company = await db.get(Company, data["company_id"])
        score, factors = await compute_company_health_factors(db, company=company, settings=settings)

    # on_track project=100*0.35 + touchpoints default 70*0.25 + CR 100*0.15 + contract 60*0.15 + active 100*0.10
    expected = round(100 * 0.35 + 70 * 0.25 + 100 * 0.15 + 60 * 0.15 + 100 * 0.10, 2)
    assert score == expected
    assert factors["project_health"]["value"] == 100.0
    assert factors["touchpoints"]["value"] == 70.0


@pytest.mark.asyncio
async def test_record_health_score_groq_failure_continues():
    data = await _seed_health_fixture()
    settings = HealthOrgSettings()

    with patch("app.graphql.health.service.generate_text", new_callable=AsyncMock, return_value=None):
        async with get_tenant_db(data["org_id"]) as db:
            company = await db.get(Company, data["company_id"])
            row = await record_company_health_score(
                db,
                company=company,
                settings=settings,
                include_ai=True,
            )
            assert row.ai_summary is None
            assert float(row.score) > 0
            company = await db.get(Company, data["company_id"])
            assert float(company.health_score) == float(row.score)


@pytest.mark.asyncio
async def test_contract_renewal_check_enrolls_in_window():
    data = await _seed_health_fixture()
    sequence_id = uuid.uuid4()
    step_id = uuid.uuid4()
    contract_id = uuid.uuid4()
    today = date.today()

    async with get_tenant_db(data["org_id"]) as db:
        db.add(
            RetentionSequence(
                id=sequence_id,
                org_id=data["org_id"],
                name="Renewal",
                trigger_type=SequenceTriggerType.ON_RENEWAL_APPROACHING.value,
                is_active=True,
                is_template=False,
            )
        )
        await db.flush()
        db.add(
            RetentionSequenceStep(
                id=step_id,
                org_id=data["org_id"],
                sequence_id=sequence_id,
                step_order=0,
                channel=TouchpointChannel.EMAIL.value,
                offset_days=0,
            )
        )
        db.add(
            Contract(
                id=contract_id,
                org_id=data["org_id"],
                company_id=data["company_id"],
                name="Annual MSA",
                start_date=today - timedelta(days=300),
                end_date=today + timedelta(days=14),
                status=ContractStatus.ACTIVE.value,
            )
        )
        company = await db.get(Company, data["company_id"])
        company.account_owner_id = data["user_id"]

    result = await contract_renewal_check(run_date=today)
    assert result["enrollments_created"] >= 1

    async with get_tenant_db(data["org_id"]) as db:
        assert await has_active_enrollment_for_sequence(
            db,
            company_id=data["company_id"],
            sequence_id=sequence_id,
        )


@pytest.mark.asyncio
async def test_recalculate_health_scores_idempotent_via_job_runs():
    data = await _seed_health_fixture()
    today = date.today()

    await recalculate_health_scores(run_date=today)
    await recalculate_health_scores(run_date=today)

    async with get_tenant_db(data["org_id"]) as db:
        from sqlalchemy import func, select
        from app.db.models.client_health import ClientHealthScore

        count = (
            await db.execute(
                select(func.count()).select_from(ClientHealthScore).where(
                    ClientHealthScore.company_id == data["company_id"]
                )
            )
        ).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_at_risk_company_below_threshold():
    data = await _seed_health_fixture()
    settings = HealthOrgSettings(at_risk_threshold=60.0)

    async with get_tenant_db(data["org_id"]) as db:
        company = await db.get(Company, data["company_id"])
        project = await db.get(Project, data["project_id"])
        project.health = ProjectHealth.DELAYED.value
        company.status = "paused"
        await db.flush()

        score, _ = await compute_company_health_factors(db, company=company, settings=settings)
        assert score < settings.at_risk_threshold

        await record_company_health_score(db, company=company, settings=settings, include_ai=False)
        at_risk = await get_at_risk_companies(db, org_settings=settings)
        assert any(c.id == data["company_id"] for c in at_risk)


@pytest.mark.asyncio
async def test_weekly_digest_email_job_completes():
    data = await _seed_health_fixture()
    settings = HealthOrgSettings(at_risk_threshold=99.0)
    today = date.today()

    async with get_tenant_db(data["org_id"]) as db:
        company = await db.get(Company, data["company_id"])
        await record_company_health_score(db, company=company, settings=settings, include_ai=False)

    from app.scheduler.jobs import weekly_digest_email

    result = await weekly_digest_email(run_date=today)
    assert "emails_sent" in result
    assert result["emails_sent"] >= 0
