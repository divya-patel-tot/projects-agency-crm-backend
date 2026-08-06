"""Scheduled jobs â€” async, per-org with RLS. Idempotent via job_runs + DB constraints."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, get_tenant_db
from app.db.enums import ChangeRequestStatus, EnrollmentStatus, TouchpointChannel, TouchpointStatus
from app.db.models.change_request import ChangeRequest
from app.db.models.company import Company
from app.db.models.organization import Organization
from app.db.models.planning import Milestone, ProjectPhase, Task
from app.db.models.project import Project
from app.db.models.retention import JobRun
from app.db.models.user import User
from app.graphql.change_requests.state_machine import org_settings_from_dict
from app.graphql.contracts.repository import list_active_contracts_in_renewal_window
from app.graphql.health.service import get_at_risk_companies, get_primary_contact, recalculate_org_health_scores
from app.graphql.notifications.service import notify
from app.graphql.org_settings import health_settings_from_dict
from app.graphql.retention.repository import (
    job_run_exists,
    list_active_enrollments,
    list_scheduled_touchpoints_past_due,
    list_steps_for_sequence,
)
from app.graphql.retention.service import enroll_renewal_sequences, materialize_due_touchpoint

logger = logging.getLogger(__name__)

JOB_PROCESS_DUE_STEPS = "process_due_sequence_steps"
JOB_FLAG_OVERDUE = "flag_overdue_touchpoints"
JOB_ESCALATE_CR = "escalate_pending_change_requests"
JOB_DEADLINE_REMINDERS = "project_deadline_reminders"
JOB_RECALCULATE_HEALTH = "recalculate_health_scores"
JOB_CONTRACT_RENEWAL = "contract_renewal_check"
JOB_WEEKLY_DIGEST = "weekly_digest_email"
JOB_FLAG_OVERDUE_INVOICES = "flag_overdue_invoices"


async def _list_org_ids() -> list[UUID]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Organization.id))
        return [row[0] for row in result.all()]


async def _record_job_run(org_id: UUID, job_name: str, run_date: date, detail: str | None = None) -> None:
    async with get_tenant_db(org_id) as db:
        if await job_run_exists(db, org_id=org_id, job_name=job_name, run_date=run_date):
            return
        now = datetime.now(UTC)
        db.add(
            JobRun(
                org_id=org_id,
                job_name=job_name,
                run_date=run_date,
                started_at=now,
                finished_at=now,
                status="completed",
                detail=detail,
            )
        )


async def _should_run_job(org_id: UUID, job_name: str, run_date: date) -> bool:
    async with get_tenant_db(org_id) as db:
        return not await job_run_exists(db, org_id=org_id, job_name=job_name, run_date=run_date)


async def process_due_sequence_steps(run_date: date | None = None) -> dict:
    today = run_date or date.today()
    end_of_day = datetime.combine(today, datetime.max.time(), tzinfo=UTC)
    created = 0
    emails = 0

    for org_id in await _list_org_ids():
        if not await _should_run_job(org_id, JOB_PROCESS_DUE_STEPS, today):
            continue
        async with get_tenant_db(org_id) as db:
            for enrollment in await list_active_enrollments(db):
                steps = await list_steps_for_sequence(db, enrollment.sequence_id)
                for step in steps:
                    due_at = enrollment.enrolled_at + timedelta(days=step.offset_days)
                    if due_at > end_of_day:
                        continue
                    tp = await materialize_due_touchpoint(db, enrollment=enrollment, step=step)
                    if tp is None:
                        continue
                    created += 1
                    # Mail disabled â€” retention EMAIL steps still materialize touchpoints but do not send.
                    # if step.channel == TouchpointChannel.EMAIL.value and step.template_id:
                    #     contact = await db.get(Contact, enrollment.contact_id)
                    #     template = await get_email_template(db, step.template_id)
                    #     if contact and template and contact.email:
                    #         ctx = {
                    #             "contact_first_name": contact.first_name,
                    #             "contact_last_name": contact.last_name,
                    #             "company_id": str(enrollment.company_id),
                    #         }
                    #         subject, body = render_template(template.subject, template.body, ctx)
                    #         try:
                    #             send_email(to=contact.email, subject=subject, body=body)
                    #             emails += 1
                    #         except Exception as exc:  # noqa: BLE001
                    #             logger.warning("Email send failed touchpoint=%s: %s", tp.id, exc)
        await _record_job_run(org_id, JOB_PROCESS_DUE_STEPS, today, detail=f"created={created}")

    return {"touchpoints_created": created, "emails_sent": emails}


async def flag_overdue_touchpoints(run_date: date | None = None) -> dict:
    today = run_date or date.today()
    now = datetime.now(UTC)
    flagged = 0

    for org_id in await _list_org_ids():
        if not await _should_run_job(org_id, JOB_FLAG_OVERDUE, today):
            continue
        async with get_tenant_db(org_id) as db:
            for tp in await list_scheduled_touchpoints_past_due(db, now=now):
                tp.status = TouchpointStatus.OVERDUE.value
                flagged += 1

                company = await db.get(Company, tp.company_id)
                owner = await db.get(User, company.account_owner_id) if company and company.account_owner_id else None
                if owner is not None and owner.deleted_at is None:
                    await notify(
                        db,
                        org_id=org_id,
                        recipient=owner,
                        category="retention_touchpoints",
                        type_="touchpoint_overdue",
                        title=f"Overdue touchpoint: {company.name if company else 'a client'}",
                        message=f"A scheduled {tp.type.replace('_', ' ')} touchpoint is now overdue.",
                        link=f"/companies/{tp.company_id}/touchpoints",
                    )
        await _record_job_run(org_id, JOB_FLAG_OVERDUE, today, detail=f"flagged={flagged}")

    return {"flagged": flagged}


async def escalate_pending_change_requests(run_date: date | None = None) -> dict:
    today = run_date or date.today()
    now = datetime.now(UTC)
    escalated = 0

    open_cr_statuses = [
        ChangeRequestStatus.SUBMITTED.value,
        ChangeRequestStatus.UNDER_REVIEW.value,
        ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
        ChangeRequestStatus.PENDING_APPROVAL.value,
    ]

    for org_id in await _list_org_ids():
        if not await _should_run_job(org_id, JOB_ESCALATE_CR, today):
            continue
        async with get_tenant_db(org_id) as db:
            from app.db.models.organization import Organization

            org = await db.get(Organization, org_id)
            org_settings = org_settings_from_dict(org.settings if org else {})
            sla_cutoff = now - timedelta(days=org_settings.response_sla_days)

            result = await db.execute(
                select(ChangeRequest).where(
                    ChangeRequest.org_id == org_id,
                    ChangeRequest.deleted_at.is_(None),
                    ChangeRequest.status.in_(open_cr_statuses),
                    ChangeRequest.submitted_at.is_not(None),
                    ChangeRequest.submitted_at < sla_cutoff,
                    ChangeRequest.manager_escalation_flagged.is_(False),
                )
            )
            for cr in result.scalars().all():
                cr.manager_escalation_flagged = True
                project = await db.get(Project, cr.project_id)
                notify_user_id = cr.assigned_pm_id or (project.project_manager_id if project else None)
                recipient = await db.get(User, notify_user_id) if notify_user_id else None
                if recipient is not None and recipient.deleted_at is None:
                    await notify(
                        db,
                        org_id=org_id,
                        recipient=recipient,
                        category="change_requests",
                        type_="cr_sla_escalation",
                        title=f"CR overdue for response: {cr.title}",
                        message=f"Change request '{cr.title}' exceeded SLA ({org_settings.response_sla_days} days).",
                        link=f"/change-requests/{cr.id}",
                    )
                    escalated += 1
        await _record_job_run(org_id, JOB_ESCALATE_CR, today, detail=f"escalated={escalated}")

    return {"escalated": escalated}


async def project_deadline_reminders(run_date: date | None = None) -> dict:
    today = run_date or date.today()
    horizon = today + timedelta(days=3)
    notified = 0

    for org_id in await _list_org_ids():
        if not await _should_run_job(org_id, JOB_DEADLINE_REMINDERS, today):
            continue
        async with get_tenant_db(org_id) as db:
            task_rows = await db.execute(
                select(Task).where(
                    Task.deleted_at.is_(None),
                    Task.due_date.is_not(None),
                    Task.due_date <= horizon,
                    Task.status.notin_(["done"]),
                )
            )
            for task in task_rows.scalars().all():
                assignee = await db.get(User, task.assignee_id) if task.assignee_id else None
                if assignee is not None and assignee.deleted_at is None:
                    await notify(
                        db,
                        org_id=org_id,
                        recipient=assignee,
                        category="task_assignments",
                        type_="task_deadline_reminder",
                        title=f"Task due soon: {task.title}",
                        message=f"Task '{task.title}' is due on {task.due_date}.",
                        link=f"/projects/{task.project_id}/board",
                    )
                    notified += 1

            ms_rows = await db.execute(
                select(Milestone)
                .join(ProjectPhase, Milestone.phase_id == ProjectPhase.id)
                .join(Project, ProjectPhase.project_id == Project.id)
                .where(
                    Milestone.deleted_at.is_(None),
                    Milestone.due_date.is_not(None),
                    Milestone.due_date <= horizon,
                    Milestone.status.notin_(["completed"]),
                )
            )
            for ms in ms_rows.scalars().all():
                phase = await db.get(ProjectPhase, ms.phase_id)
                project = await db.get(Project, phase.project_id) if phase else None
                pm = await db.get(User, project.project_manager_id) if project and project.project_manager_id else None
                if pm is not None and pm.deleted_at is None:
                    await notify(
                        db,
                        org_id=org_id,
                        recipient=pm,
                        category="project_updates",
                        type_="milestone_deadline_reminder",
                        title=f"Milestone due soon: {ms.title}",
                        message=f"Milestone '{ms.title}' is due on {ms.due_date}.",
                        link=f"/projects/{project.id}",
                    )
                    notified += 1

        await _record_job_run(org_id, JOB_DEADLINE_REMINDERS, today, detail=f"notified={notified}")

    return {"notified": notified}


async def recalculate_health_scores(run_date: date | None = None) -> dict:
    today = run_date or date.today()
    total_calculated = 0

    for org_id in await _list_org_ids():
        if not await _should_run_job(org_id, JOB_RECALCULATE_HEALTH, today):
            continue
        org_calculated = 0
        async with get_tenant_db(org_id) as db:
            org = await db.get(Organization, org_id)
            settings = health_settings_from_dict(org.settings if org else {})
            org_calculated = await recalculate_org_health_scores(
                db,
                org_settings=settings,
                today=today,
                include_ai=True,
            )
        total_calculated += org_calculated
        await _record_job_run(org_id, JOB_RECALCULATE_HEALTH, today, detail=f"companies={org_calculated}")

    return {"companies_scored": total_calculated}


async def contract_renewal_check(run_date: date | None = None) -> dict:
    today = run_date or date.today()
    enrolled = 0
    notified = 0

    for org_id in await _list_org_ids():
        if not await _should_run_job(org_id, JOB_CONTRACT_RENEWAL, today):
            continue
        async with get_tenant_db(org_id) as db:
            org = await db.get(Organization, org_id)
            settings = health_settings_from_dict(org.settings if org else {})
            window_end = today + timedelta(days=settings.contract_renewal_window_days)

            contracts = await list_active_contracts_in_renewal_window(
                db,
                window_start=today,
                window_end=window_end,
            )
            for contract in contracts:
                contact = await get_primary_contact(db, contract.company_id)
                if contact is None:
                    continue
                new_enrollments = await enroll_renewal_sequences(
                    db,
                    org_id=org_id,
                    company_id=contract.company_id,
                    contact_id=contact.id,
                )
                enrolled += len(new_enrollments)

                company = await db.get(Company, contract.company_id)
                owner = await db.get(User, company.account_owner_id) if company and company.account_owner_id else None
                if owner is not None and owner.deleted_at is None:
                    days_left = (contract.end_date - today).days
                    await notify(
                        db,
                        org_id=org_id,
                        recipient=owner,
                        category="project_updates",
                        type_="contract_renewal_approaching",
                        title=f"Contract renewal approaching: {company.name}",
                        message=(
                            f"Contract '{contract.name}' for {company.name} ends in {days_left} days "
                            f"({contract.end_date.isoformat()}). Review renewal â€” never auto-churn."
                        ),
                        link=f"/companies/{company.id}/contracts",
                    )
                    notified += 1

                    # Mail disabled â€” in-app notification above is still created.
                    # owner = await db.get(User, company.account_owner_id)
                    # if owner and owner.email:
                    #     try:
                    #         send_email(
                    #             to=owner.email,
                    #             subject=f"Contract renewal approaching: {company.name}",
                    #             body=(
                    #                 f"Contract '{contract.name}' for {company.name} ends in {days_left} days "
                    #                 f"({contract.end_date.isoformat()}).\n\n"
                    #                 "Please review renewal options. Clients are never auto-churned."
                    #             ),
                    #         )
                    #     except Exception as exc:  # noqa: BLE001
                    #         logger.warning("Renewal email failed company=%s: %s", company.id, exc)

        await _record_job_run(org_id, JOB_CONTRACT_RENEWAL, today, detail=f"enrolled={enrolled},notified={notified}")

    return {"enrollments_created": enrolled, "owners_notified": notified}


async def weekly_digest_email(run_date: date | None = None) -> dict:
    """Weekly at-risk digest â€” mail disabled; returns immediately without sending."""
    _ = run_date
    return {"emails_sent": 0}

    # --- Mail implementation (disabled) ---
    # today = run_date or date.today()
    # emails_sent = 0
    #
    # for org_id in await _list_org_ids():
    #     if not await _should_run_job(org_id, JOB_WEEKLY_DIGEST, today):
    #         continue
    #     async with get_tenant_db(org_id) as db:
    #         org = await db.get(Organization, org_id)
    #         settings = health_settings_from_dict(org.settings if org else {})
    #         at_risk = await get_at_risk_companies(db, org_settings=settings)
    #
    #         if not at_risk:
    #             await _record_job_run(org_id, JOB_WEEKLY_DIGEST, today, detail="no_at_risk")
    #             continue
    #
    #         lines = [f"- {c.name}: health score {float(c.health_score):.1f}" for c in at_risk[:20]]
    #         body = (
    #             f"Weekly at-risk client digest for {org.name if org else org_id}\n\n"
    #             f"{len(at_risk)} client(s) below threshold ({settings.at_risk_threshold}):\n"
    #             + "\n".join(lines)
    #             + "\n\nThis is an automated advisory digest."
    #         )
    #
    #         result = await db.execute(
    #             select(User).where(
    #                 User.org_id == org_id,
    #                 User.status == "active",
    #                 User.role.in_(["admin"]),
    #             )
    #         )
    #         for user in result.scalars().all():
    #             if not user.email:
    #                 continue
    #             try:
    #                 send_email(
    #                     to=user.email,
    #                     subject=f"Weekly at-risk clients ({len(at_risk)})",
    #                     body=body,
    #                 )
    #                 emails_sent += 1
    #             except Exception as exc:  # noqa: BLE001
    #                 logger.warning("Weekly digest email failed user=%s: %s", user.id, exc)
    #
    #     await _record_job_run(org_id, JOB_WEEKLY_DIGEST, today, detail=f"emails={emails_sent}")
    #
    # return {"emails_sent": emails_sent}


async def flag_overdue_invoices(run_date: date | None = None) -> dict:
    today = run_date or date.today()
    flagged = 0

    for org_id in await _list_org_ids():
        if not await _should_run_job(org_id, JOB_FLAG_OVERDUE_INVOICES, today):
            continue
        async with get_tenant_db(org_id) as db:
            from app.db.enums import InvoiceStatus
            from app.graphql.invoices.repository import list_overdue_candidates

            for invoice in await list_overdue_candidates(db, as_of=today):
                if invoice.status != InvoiceStatus.OVERDUE.value:
                    invoice.status = InvoiceStatus.OVERDUE.value
                    flagged += 1

                    company = await db.get(Company, invoice.company_id)
                    owner = (
                        await db.get(User, company.account_owner_id)
                        if company and company.account_owner_id
                        else None
                    )
                    if owner is not None and owner.deleted_at is None:
                        await notify(
                            db,
                            org_id=org_id,
                            recipient=owner,
                            category="project_updates",
                            type_="invoice_overdue",
                            title=f"Invoice overdue: {company.name if company else 'a client'}",
                            message=(
                                f"Invoice {invoice.invoice_number or invoice.id} "
                                f"for {company.name if company else 'this client'} is now overdue."
                            ),
                            link=f"/companies/{invoice.company_id}/invoices",
                        )
        await _record_job_run(org_id, JOB_FLAG_OVERDUE_INVOICES, today, detail=f"flagged={flagged}")

    return {"flagged": flagged}


JOB_REGISTRY = {
    JOB_PROCESS_DUE_STEPS: process_due_sequence_steps,
    JOB_FLAG_OVERDUE: flag_overdue_touchpoints,
    JOB_ESCALATE_CR: escalate_pending_change_requests,
    JOB_DEADLINE_REMINDERS: project_deadline_reminders,
    JOB_RECALCULATE_HEALTH: recalculate_health_scores,
    JOB_CONTRACT_RENEWAL: contract_renewal_check,
    JOB_WEEKLY_DIGEST: weekly_digest_email,
    JOB_FLAG_OVERDUE_INVOICES: flag_overdue_invoices,
}
