import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.db import AsyncSessionLocal, get_tenant_db
from app.core.exceptions import AuthorizationError, DomainError
from app.core.security import hash_password
from app.db.enums import ApprovalStatus, ApproverType, ChangeRequestStatus, ChangeRequestType
from app.db.models.approval import Approval
from app.db.models.change_request import ChangeRequest
from app.db.models.company import Company
from app.db.models.contact import Contact
from app.db.models.notification import Notification
from app.db.models.organization import Organization
from app.db.models.planning import ProjectPhase, Task
from app.db.models.project import Project
from app.db.models.user import User
from app.graphql.change_requests.repository import list_approvals_for_cr
from app.graphql.change_requests.service import (
    create_change_request,
    decide_change_request,
    portal_resubmit_change_request,
    submit_impact_assessment,
    transition_change_request,
)


async def _seed_phase4_fixture() -> dict:
    org_id = uuid.uuid4()
    company_id = uuid.uuid4()
    pm_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    project_id = uuid.uuid4()
    phase_id = uuid.uuid4()

    settings = {
        "cr_internal_approval_cost_threshold": 5000,
        "cr_internal_approval_timeline_days_threshold": 5,
        "cr_revision_cap": 3,
        "cr_response_sla_days": 7,
    }

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                Organization(
                    id=org_id,
                    name="CR Org",
                    plan="trial",
                    settings=settings,
                )
            )

    async with get_tenant_db(org_id) as db:
        db.add(Company(id=company_id, org_id=org_id, name="Client Co", status="active"))
        db.add(
            User(
                id=pm_id,
                org_id=org_id,
                email="pm@example.com",
                password_hash=hash_password("ChangeMe123!"),
                name="PM User",
                role="project_manager",
                status="active",
            )
        )
        await db.flush()
        db.add(
            Contact(
                id=contact_id,
                org_id=org_id,
                company_id=company_id,
                first_name="Client",
                last_name="Contact",
                email="client@example.com",
                portal_access_enabled=True,
                password_hash=hash_password("PortalPass123!"),
                status="active",
            )
        )
        db.add(
            Project(
                id=project_id,
                org_id=org_id,
                company_id=company_id,
                name="Website Redesign",
                status="active",
                project_manager_id=pm_id,
                budget=10000,
                end_date=date(2026, 12, 31),
            )
        )
        db.add(
            ProjectPhase(
                id=phase_id,
                org_id=org_id,
                project_id=project_id,
                name="Build",
                order_index=0,
                status="in_progress",
            )
        )
        db.add(
            Task(
                org_id=org_id,
                project_id=project_id,
                phase_id=phase_id,
                title="Existing task",
                status="todo",
                priority="medium",
                due_date=date(2026, 6, 1),
            )
        )

    return {
        "org_id": org_id,
        "company_id": company_id,
        "pm_id": pm_id,
        "contact_id": contact_id,
        "project_id": project_id,
        "phase_id": phase_id,
    }


async def _get_pm(db, data) -> User:
    return await db.get(User, data["pm_id"])


async def _get_contact(db, data) -> Contact:
    return await db.get(Contact, data["contact_id"])


@pytest.mark.asyncio
async def test_submit_impact_assessment_rejects_non_pm():
    data = await _seed_phase4_fixture()

    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        pm = await _get_pm(db, data)
        cr = await create_change_request(
            db,
            org_id=data["org_id"],
            project_id=data["project_id"],
            company_id=data["company_id"],
            title="Add feature",
            description="More scope",
            cr_type=ChangeRequestType.SCOPE_ADDITION.value,
            actor_id=pm.id,
        )
        cr_id = cr.id
        await transition_change_request(
            db,
            actor=pm,
            cr_id=cr_id,
            to_status=ChangeRequestStatus.UNDER_REVIEW.value,
        )

    async with get_tenant_db(data["org_id"], role="team_member") as db:
        member = User(id=uuid.uuid4(), org_id=data["org_id"], name="Member", email="m@x.com", password_hash="x", role="team_member")
        with pytest.raises(AuthorizationError):
            await submit_impact_assessment(
                db,
                actor=member,
                cr_id=cr_id,
                impact_hours=10,
                impact_cost=1000,
                impact_timeline_days=2,
                assessment_notes="Minor add",
            )


@pytest.mark.asyncio
async def test_dual_approval_sequencing_internal_before_client():
    data = await _seed_phase4_fixture()

    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        pm = await _get_pm(db, data)
        cr = await create_change_request(
            db,
            org_id=data["org_id"],
            project_id=data["project_id"],
            company_id=data["company_id"],
            title="Big scope add",
            description="Expensive",
            cr_type=ChangeRequestType.SCOPE_ADDITION.value,
            actor_id=pm.id,
        )
        await transition_change_request(db, actor=pm, cr_id=cr.id, to_status=ChangeRequestStatus.UNDER_REVIEW.value)
        await submit_impact_assessment(
            db,
            actor=pm,
            cr_id=cr.id,
            impact_hours=40,
            impact_cost=6000,
            impact_timeline_days=3,
            assessment_notes="Needs both approvals",
        )
        cr_id = cr.id

    async with get_tenant_db(data["org_id"]) as db:
        approvals = await list_approvals_for_cr(db, cr_id)
        assert len(approvals) == 1
        assert approvals[0].approver_type == ApproverType.INTERNAL.value

    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        pm = await _get_pm(db, data)
        contact = await _get_contact(db, data)
        internal = (await list_approvals_for_cr(db, cr_id))[0]
        with pytest.raises(AuthorizationError):
            await decide_change_request(
                db,
                cr_id=cr_id,
                approval_id=internal.id,
                decision=ApprovalStatus.APPROVED.value,
                comment=None,
                apply_financial_impact=False,
                portal_contact=contact,
            )

        await decide_change_request(
            db,
            cr_id=cr_id,
            approval_id=internal.id,
            decision=ApprovalStatus.APPROVED.value,
            comment="LGTM internal",
            apply_financial_impact=False,
            internal_actor=pm,
        )

    async with get_tenant_db(data["org_id"]) as db:
        approvals = await list_approvals_for_cr(db, cr_id)
        client_rows = [a for a in approvals if a.approver_type == ApproverType.CLIENT.value]
        assert len(client_rows) == 1


@pytest.mark.asyncio
async def test_apply_financial_impact_only_when_flagged():
    data = await _seed_phase4_fixture()

    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        pm = await _get_pm(db, data)
        contact = await _get_contact(db, data)
        cr = await create_change_request(
            db,
            org_id=data["org_id"],
            project_id=data["project_id"],
            company_id=data["company_id"],
            title="Budget bump",
            description=None,
            cr_type=ChangeRequestType.BUDGET_CHANGE.value,
            actor_id=pm.id,
        )
        await transition_change_request(db, actor=pm, cr_id=cr.id, to_status=ChangeRequestStatus.UNDER_REVIEW.value)
        await submit_impact_assessment(
            db,
            actor=pm,
            cr_id=cr.id,
            impact_cost=2000,
            impact_timeline_days=0,
            assessment_notes="Budget increase",
        )
        cr_id = cr.id

    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        pm = await _get_pm(db, data)
        contact = await _get_contact(db, data)
        client_approval = [
            a for a in await list_approvals_for_cr(db, cr_id) if a.approver_type == ApproverType.CLIENT.value
        ][0]
        await decide_change_request(
            db,
            cr_id=cr_id,
            approval_id=client_approval.id,
            decision=ApprovalStatus.APPROVED.value,
            comment="Approved",
            apply_financial_impact=False,
            portal_contact=contact,
        )

    async with get_tenant_db(data["org_id"]) as db:
        project = await db.get(Project, data["project_id"])
        assert float(project.budget) == 10000

    # Internal-only CR: PM applies financial impact on timeline change
    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        pm = await _get_pm(db, data)
        cr2 = await create_change_request(
            db,
            org_id=data["org_id"],
            project_id=data["project_id"],
            company_id=data["company_id"],
            title="Timeline slip",
            description=None,
            cr_type=ChangeRequestType.TIMELINE_CHANGE.value,
            actor_id=pm.id,
        )
        await transition_change_request(db, actor=pm, cr_id=cr2.id, to_status=ChangeRequestStatus.UNDER_REVIEW.value)
        await submit_impact_assessment(
            db,
            actor=pm,
            cr_id=cr2.id,
            impact_timeline_days=10,
            assessment_notes="Extend deadline",
        )
        internal_approval = [
            a for a in await list_approvals_for_cr(db, cr2.id) if a.approver_type == ApproverType.INTERNAL.value
        ][0]
        await decide_change_request(
            db,
            cr_id=cr2.id,
            approval_id=internal_approval.id,
            decision=ApprovalStatus.APPROVED.value,
            comment="Approved with impact",
            apply_financial_impact=True,
            internal_actor=pm,
        )

    async with get_tenant_db(data["org_id"]) as db:
        project = await db.get(Project, data["project_id"])
        assert project.end_date == date(2027, 1, 10)


@pytest.mark.asyncio
async def test_revision_cap_escalation_notification():
    data = await _seed_phase4_fixture()

    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        pm = await _get_pm(db, data)
        contact = await _get_contact(db, data)
        cr = await create_change_request(
            db,
            org_id=data["org_id"],
            project_id=data["project_id"],
            company_id=data["company_id"],
            title="Flappy CR",
            description=None,
            cr_type=ChangeRequestType.OTHER.value,
            requested_by_contact_id=contact.id,
            actor_id=contact.id,
        )
        cr_id = cr.id
        cr.revision_count = 3
        cr.status = ChangeRequestStatus.REJECTED.value
        await db.flush()

    async with get_tenant_db(data["org_id"]) as db:
        contact = await _get_contact(db, data)
        await portal_resubmit_change_request(db, contact=contact, cr_id=cr_id)

    async with get_tenant_db(data["org_id"]) as db:
        cr = await db.get(ChangeRequest, cr_id)
        assert cr.revision_count == 4
        assert cr.manager_escalation_flagged is True
        from sqlalchemy import select

        result = await db.execute(
            select(Notification).where(
                Notification.org_id == data["org_id"],
                Notification.type == "cr_revision_escalation",
            )
        )
        notifications = list(result.scalars().all())
        assert len(notifications) == 1
        assert notifications[0].user_id == data["pm_id"]


@pytest.mark.asyncio
async def test_scope_addition_creates_task_on_in_progress():
    data = await _seed_phase4_fixture()

    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        pm = await _get_pm(db, data)
        cr = await create_change_request(
            db,
            org_id=data["org_id"],
            project_id=data["project_id"],
            company_id=data["company_id"],
            title="New page",
            description="Landing page",
            cr_type=ChangeRequestType.SCOPE_ADDITION.value,
            actor_id=pm.id,
        )
        await transition_change_request(db, actor=pm, cr_id=cr.id, to_status=ChangeRequestStatus.UNDER_REVIEW.value)
        await submit_impact_assessment(
            db,
            actor=pm,
            cr_id=cr.id,
            impact_hours=8,
            impact_cost=500,
            impact_timeline_days=1,
            assessment_notes="Small scope",
        )
        client_approval = [
            a for a in await list_approvals_for_cr(db, cr.id) if a.approver_type == ApproverType.CLIENT.value
        ][0]
        contact = await _get_contact(db, data)
        await decide_change_request(
            db,
            cr_id=cr.id,
            approval_id=client_approval.id,
            decision=ApprovalStatus.APPROVED.value,
            comment=None,
            apply_financial_impact=False,
            portal_contact=contact,
        )

    async with get_tenant_db(data["org_id"]) as db:
        from sqlalchemy import select

        tasks = list(
            (
                await db.execute(
                    select(Task).where(
                        Task.project_id == data["project_id"],
                        Task.title.like("CR:%"),
                    )
                )
            ).scalars().all()
        )
        assert len(tasks) == 1
        assert tasks[0].estimated_hours == 8
