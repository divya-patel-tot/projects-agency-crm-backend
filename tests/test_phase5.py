import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.db import AsyncSessionLocal, get_tenant_db
from app.core.security import hash_password
from app.db.enums import EnrollmentStatus, ProjectStatus, SequenceTriggerType, TouchpointChannel, TouchpointStatus
from app.db.models.company import Company
from app.db.models.contact import Contact
from app.db.models.organization import Organization
from app.db.models.project import Project
from app.db.models.retention import RetentionEnrollment, RetentionSequence, RetentionSequenceStep
from app.db.models.user import User
from app.graphql.retention.repository import has_active_enrollment_for_sequence, list_steps_for_sequence
from app.graphql.retention.service import (
    complete_touchpoint,
    create_sequence_record,
    add_sequence_step,
    materialize_due_touchpoint,
)
from app.scheduler.jobs import flag_overdue_touchpoints, process_due_sequence_steps


async def _seed_retention_fixture() -> dict:
    org_id = uuid.uuid4()
    company_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    user_id = uuid.uuid4()
    sequence_id = uuid.uuid4()
    step_id = uuid.uuid4()
    project_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_id, name="Retention Org", plan="trial", settings={}))

    async with get_tenant_db(org_id) as db:
        db.add(Company(id=company_id, org_id=org_id, name="Co", status="active"))
        db.add(
            User(
                id=user_id,
                org_id=org_id,
                name="AM",
                email="am@example.com",
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
                last_name="Client",
                email="pat@client.com",
                is_primary=True,
                status="active",
            )
        )
        db.add(
            RetentionSequence(
                id=sequence_id,
                org_id=org_id,
                name="Welcome",
                trigger_type=SequenceTriggerType.MANUAL.value,
                is_active=True,
                is_template=False,
            )
        )
        await db.flush()
        db.add(
            RetentionSequenceStep(
                id=step_id,
                org_id=org_id,
                sequence_id=sequence_id,
                step_order=0,
                channel=TouchpointChannel.EMAIL.value,
                offset_days=0,
            )
        )
        db.add(
            Project(
                id=project_id,
                org_id=org_id,
                company_id=company_id,
                name="Active Project",
                status="active",
            )
        )
        await db.flush()
        enrolled_at = datetime.now(UTC) - timedelta(days=1)
        enrollment_id = uuid.uuid4()
        db.add(
            RetentionEnrollment(
                id=enrollment_id,
                org_id=org_id,
                sequence_id=sequence_id,
                company_id=company_id,
                contact_id=contact_id,
                status=EnrollmentStatus.ACTIVE.value,
                current_step=0,
                enrolled_at=enrolled_at,
            )
        )

    return {
        "org_id": org_id,
        "user_id": user_id,
        "enrollment_id": enrollment_id,
        "sequence_id": sequence_id,
        "step_id": step_id,
        "company_id": company_id,
        "contact_id": contact_id,
        "project_id": project_id,
    }


@pytest.mark.asyncio
async def test_materialize_touchpoint_is_idempotent():
    data = await _seed_retention_fixture()

    async with get_tenant_db(data["org_id"]) as db:
        from sqlalchemy import select

        enrollment = await db.get(RetentionEnrollment, data["enrollment_id"])
        step = await db.get(RetentionSequenceStep, data["step_id"])
        tp1 = await materialize_due_touchpoint(db, enrollment=enrollment, step=step)
        tp2 = await materialize_due_touchpoint(db, enrollment=enrollment, step=step)
        assert tp1 is not None
        assert tp2 is None
        count = len((await db.execute(select(RetentionEnrollment))).scalars().all())
        assert count == 1


@pytest.mark.asyncio
async def test_process_due_sequence_steps_idempotent_via_job_runs():
    data = await _seed_retention_fixture()
    from datetime import date

    today = date.today()
    await process_due_sequence_steps(run_date=today)
    await process_due_sequence_steps(run_date=today)

    async with get_tenant_db(data["org_id"]) as db:
        from sqlalchemy import func, select
        from app.db.models.retention import Touchpoint

        count = (await db.execute(select(func.count()).select_from(Touchpoint))).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_complete_touchpoint_completes_enrollment():
    data = await _seed_retention_fixture()

    async with get_tenant_db(data["org_id"], role="account_manager") as db:
        enrollment = await db.get(RetentionEnrollment, data["enrollment_id"])
        step = await db.get(RetentionSequenceStep, data["step_id"])
        tp = await materialize_due_touchpoint(db, enrollment=enrollment, step=step)
        user = await db.get(User, data["user_id"])
        await complete_touchpoint(db, actor=user, touchpoint_id=tp.id, outcome="positive")
        enrollment = await db.get(RetentionEnrollment, data["enrollment_id"])
        assert enrollment.status == EnrollmentStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_flag_overdue_touchpoints():
    data = await _seed_retention_fixture()

    async with get_tenant_db(data["org_id"]) as db:
        enrollment = await db.get(RetentionEnrollment, data["enrollment_id"])
        step = await db.get(RetentionSequenceStep, data["step_id"])
        tp = await materialize_due_touchpoint(db, enrollment=enrollment, step=step)
        tp.scheduled_at = datetime.now(UTC) - timedelta(days=2)
        await db.flush()
        tp_id = tp.id

    from datetime import date

    await flag_overdue_touchpoints(run_date=date.today())

    async with get_tenant_db(data["org_id"]) as db:
        from app.db.models.retention import Touchpoint

        tp = await db.get(Touchpoint, tp_id)
        assert tp.status == TouchpointStatus.OVERDUE.value


@pytest.mark.asyncio
async def test_auto_enroll_on_primary_contact_create():
    data = await _seed_retention_fixture()

    async with get_tenant_db(data["org_id"], role="account_manager") as db:
        user = await db.get(User, data["user_id"])
        seq = await create_sequence_record(
            db,
            actor=user,
            name="On Company Created",
            trigger_type=SequenceTriggerType.ON_COMPANY_CREATED.value,
        )
        await add_sequence_step(
            db,
            actor=user,
            sequence_id=seq.id,
            channel=TouchpointChannel.EMAIL.value,
            offset_days=0,
        )
        company_id = uuid.uuid4()
        db.add(Company(id=company_id, org_id=data["org_id"], name="New Co", status="active"))
        await db.flush()

        from app.graphql.contacts.service import create_contact_record

        await create_contact_record(
            db,
            actor=user,
            company_id=company_id,
            first_name="New",
            last_name="Primary",
            email="new@co.com",
            is_primary=True,
        )
        assert await has_active_enrollment_for_sequence(db, company_id=company_id, sequence_id=seq.id)


@pytest.mark.asyncio
async def test_auto_enroll_on_project_completed():
    data = await _seed_retention_fixture()

    async with get_tenant_db(data["org_id"], role="account_manager") as db:
        user = await db.get(User, data["user_id"])
        seq = await create_sequence_record(
            db,
            actor=user,
            name="On Project Completed",
            trigger_type=SequenceTriggerType.ON_PROJECT_COMPLETED.value,
        )
        await add_sequence_step(
            db,
            actor=user,
            sequence_id=seq.id,
            channel=TouchpointChannel.CALL.value,
            offset_days=1,
        )

        from app.graphql.projects.service import update_project_record

        await update_project_record(
            db,
            actor=user,
            project_id=data["project_id"],
            updates={"status": ProjectStatus.COMPLETED.value},
        )
        assert await has_active_enrollment_for_sequence(
            db,
            company_id=data["company_id"],
            sequence_id=seq.id,
        )
