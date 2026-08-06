from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import AuthorizationError, DomainError, NotFoundError
from app.db.enums import (
    ApprovalStatus,
    ApproverType,
    ChangeRequestPriority,
    ChangeRequestStatus,
    ChangeRequestType,
    EntityType,
    TaskPriority,
    TaskStatus,
)
from app.db.models.change_request import ChangeRequest
from app.db.models.contact import Contact
from app.db.models.planning import Milestone, Task
from app.db.models.user import User
from app.graphql.notifications.service import notify
from app.graphql.change_requests.repository import (
    create_approval_row,
    create_change_request_row,
    create_task_row,
    dashboard_aggregates,
    get_approval_by_id,
    get_change_request,
    get_first_phase_for_project,
    get_org_settings,
    get_project_for_company,
    get_project_for_cr,
    list_approvals_for_cr,
    list_change_requests,
    list_pending_client_cr_approvals,
    list_project_milestones,
    list_project_tasks,
)
from app.graphql.change_requests.state_machine import (
    ChangeRequestSnapshot,
    TransitionActor,
    apply_snapshot_transition,
    apply_transition,
    actor_from_internal_role,
    compute_approval_requirements,
    org_settings_from_dict,
    validate_transition,
)


OPEN_STATUSES = frozenset(
    {
        ChangeRequestStatus.SUBMITTED.value,
        ChangeRequestStatus.UNDER_REVIEW.value,
        ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
        ChangeRequestStatus.PENDING_APPROVAL.value,
        ChangeRequestStatus.APPROVED.value,
        ChangeRequestStatus.IN_PROGRESS.value,
        ChangeRequestStatus.IMPLEMENTED.value,
        ChangeRequestStatus.ON_HOLD.value,
    }
)


def _cr_to_dict(cr: ChangeRequest) -> dict:
    return {
        "id": str(cr.id),
        "project_id": str(cr.project_id),
        "status": cr.status,
        "type": cr.type,
        "revision_count": cr.revision_count,
        "requires_client_approval": cr.requires_client_approval,
        "requires_internal_approval": cr.requires_internal_approval,
    }


def _snapshot_from_model(cr: ChangeRequest) -> ChangeRequestSnapshot:
    return ChangeRequestSnapshot(
        status=cr.status,
        type=cr.type,
        revision_count=cr.revision_count,
        impact_cost=float(cr.impact_cost) if cr.impact_cost is not None else None,
        impact_timeline_days=cr.impact_timeline_days,
        requires_client_approval=cr.requires_client_approval,
        requires_internal_approval=cr.requires_internal_approval,
        manager_escalation_flagged=cr.manager_escalation_flagged,
    )


async def _load_org_cr_settings(db: AsyncSession, org_id: UUID):
    settings = await get_org_settings(db, org_id)
    return org_settings_from_dict(settings)


async def _write_transition_log(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    cr: ChangeRequest,
    before: dict,
    to_status: str,
    reason: str | None = None,
) -> None:
    after = _cr_to_dict(cr)
    after["status"] = to_status
    diff: dict = {"before": before, "after": after}
    if reason:
        diff["reason"] = reason
    await write_activity_log(
        db,
        org_id=org_id,
        actor_id=actor_id,
        action="transition",
        entity_type=EntityType.CHANGE_REQUEST.value,
        entity_id=cr.id,
        diff=diff,
    )


async def _apply_model_transition(
    db: AsyncSession,
    *,
    cr: ChangeRequest,
    to_status: str,
    actor: TransitionActor,
    org_id: UUID,
    actor_id: UUID,
    reason: str | None = None,
) -> ChangeRequest:
    org_settings = await _load_org_cr_settings(db, org_id)
    before = _cr_to_dict(cr)
    snapshot = _snapshot_from_model(cr)
    result = apply_transition(snapshot, to_status, actor, org_settings=org_settings)
    cr.status = result.status
    cr.revision_count = result.revision_count
    cr.manager_escalation_flagged = result.manager_escalation_flagged
    if to_status in {ChangeRequestStatus.REJECTED.value, ChangeRequestStatus.APPROVED.value}:
        cr.decided_at = datetime.now(UTC)
    await db.flush()
    await _write_transition_log(db, org_id=org_id, actor_id=actor_id, cr=cr, before=before, to_status=to_status, reason=reason)
    if result.trigger_escalation:
        await _notify_manager_escalation(db, cr=cr, org_id=org_id)
    return cr


async def _notify_manager_escalation(db: AsyncSession, *, cr: ChangeRequest, org_id: UUID) -> None:
    project = await get_project_for_cr(db, cr.project_id)
    notify_user_id = cr.assigned_pm_id or (project.project_manager_id if project else None)
    if notify_user_id is None:
        return
    recipient = await db.get(User, notify_user_id)
    if recipient is None or recipient.deleted_at is not None:
        return
    await notify(
        db,
        org_id=org_id,
        recipient=recipient,
        category="change_requests",
        type_="cr_revision_escalation",
        title=f"Change request revision cap exceeded: {cr.title}",
        message=(
            f"Change request '{cr.title}' has exceeded the revision cap "
            f"(revision_count={cr.revision_count}). Manager review required."
        ),
        link=f"/change-requests/{cr.id}",
    )


async def _setup_approval_rows(
    db: AsyncSession,
    *,
    cr: ChangeRequest,
    org_id: UUID,
    org_settings,
) -> ChangeRequestStatus:
    """Create approval rows per sequencing rule; return next status."""
    requires_client, requires_internal = compute_approval_requirements(
        cr_type=cr.type,
        impact_cost=float(cr.impact_cost) if cr.impact_cost is not None else None,
        impact_timeline_days=cr.impact_timeline_days,
        org_settings=org_settings,
    )
    cr.requires_client_approval = requires_client
    cr.requires_internal_approval = requires_internal

    if not requires_client and not requires_internal:
        return ChangeRequestStatus.APPROVED

    if requires_internal:
        await create_approval_row(db, org_id=org_id, cr_id=cr.id, approver_type=ApproverType.INTERNAL.value)
        return ChangeRequestStatus.PENDING_APPROVAL

    await create_approval_row(db, org_id=org_id, cr_id=cr.id, approver_type=ApproverType.CLIENT.value)
    return ChangeRequestStatus.PENDING_APPROVAL


async def _all_required_approvals_complete(db: AsyncSession, cr: ChangeRequest) -> bool:
    approvals = await list_approvals_for_cr(db, cr.id)
    if not approvals:
        return not cr.requires_client_approval and not cr.requires_internal_approval
    for row in approvals:
        if row.status != ApprovalStatus.APPROVED.value:
            return False
    if cr.requires_internal_approval and not any(
        a.approver_type == ApproverType.INTERNAL.value for a in approvals
    ):
        return False
    if cr.requires_client_approval and not any(a.approver_type == ApproverType.CLIENT.value for a in approvals):
        return False
    return True


async def _apply_in_progress_side_effects(
    db: AsyncSession,
    *,
    cr: ChangeRequest,
    actor: User,
    apply_financial_impact: bool,
) -> None:
    project = await get_project_for_cr(db, cr.project_id)
    if project is None:
        raise NotFoundError("Project not found")

    phase = await get_first_phase_for_project(db, cr.project_id)
    if cr.type == ChangeRequestType.SCOPE_ADDITION.value and phase is not None:
        await create_task_row(
            db,
            Task(
                org_id=cr.org_id,
                project_id=cr.project_id,
                phase_id=phase.id,
                title=f"CR: {cr.title}",
                description=cr.description,
                status=TaskStatus.TODO.value,
                priority=TaskPriority.MEDIUM.value,
                estimated_hours=float(cr.impact_hours) if cr.impact_hours is not None else None,
            ),
        )

    if cr.type == ChangeRequestType.TIMELINE_CHANGE.value and cr.impact_timeline_days:
        delta = timedelta(days=cr.impact_timeline_days)
        for milestone in await list_project_milestones(db, cr.project_id):
            if milestone.due_date is not None:
                milestone.due_date = milestone.due_date + delta
        for task in await list_project_tasks(db, cr.project_id):
            if task.due_date is not None:
                task.due_date = task.due_date + delta
        if apply_financial_impact and project.end_date is not None:
            project.end_date = project.end_date + delta

    if cr.type == ChangeRequestType.BUDGET_CHANGE.value and apply_financial_impact and cr.impact_cost is not None:
        current = float(project.budget) if project.budget is not None else 0.0
        project.budget = current + float(cr.impact_cost)

    await db.flush()


async def create_change_request(
    db: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID,
    company_id: UUID,
    title: str,
    description: str | None,
    cr_type: str,
    priority: str = ChangeRequestPriority.MEDIUM.value,
    requested_by_contact_id: UUID | None = None,
    desired_due_date: date | None = None,
    actor_id: UUID,
) -> ChangeRequest:
    project = await get_project_for_cr(db, project_id)
    if project is None or project.company_id != company_id:
        raise NotFoundError("Project not found")
    now = datetime.now(UTC)
    cr = ChangeRequest(
        org_id=org_id,
        project_id=project_id,
        company_id=company_id,
        requested_by_contact_id=requested_by_contact_id,
        type=cr_type,
        title=title,
        description=description,
        priority=priority,
        status=ChangeRequestStatus.SUBMITTED.value,
        desired_due_date=desired_due_date,
        submitted_at=now,
    )
    await create_change_request_row(db, cr)
    await write_activity_log(
        db,
        org_id=org_id,
        actor_id=actor_id,
        action="create",
        entity_type=EntityType.CHANGE_REQUEST.value,
        entity_id=cr.id,
        diff={"after": _cr_to_dict(cr)},
    )
    if project.project_manager_id is not None and project.project_manager_id != actor_id:
        pm = await db.get(User, project.project_manager_id)
        if pm is not None and pm.deleted_at is None:
            await notify(
                db,
                org_id=org_id,
                recipient=pm,
                category="change_requests",
                type_="change_request.created",
                title="New change request",
                message=f'"{cr.title}" was raised on {project.name}',
                link=f"/projects/{project.id}/change-requests",
            )
    return cr


async def transition_change_request(
    db: AsyncSession,
    *,
    actor: User,
    cr_id: UUID,
    to_status: str,
    reason: str | None = None,
) -> ChangeRequest:
    cr = await get_change_request(db, cr_id)
    if cr is None:
        raise NotFoundError("Change request not found")
    transition_actor = actor_from_internal_role(actor.role)
    return await _apply_model_transition(
        db,
        cr=cr,
        to_status=to_status,
        actor=transition_actor,
        org_id=actor.org_id,
        actor_id=actor.id,
        reason=reason,
    )


async def submit_impact_assessment(
    db: AsyncSession,
    *,
    actor: User,
    cr_id: UUID,
    impact_hours: float | None = None,
    impact_cost: float | None = None,
    impact_timeline_days: int | None = None,
    assessment_notes: str | None = None,
) -> ChangeRequest:
    if actor.role not in {"project_manager", "admin"}:
        raise AuthorizationError("Only PM or admin can submit impact assessment")

    cr = await get_change_request(db, cr_id)
    if cr is None:
        raise NotFoundError("Change request not found")
    if cr.status != ChangeRequestStatus.UNDER_REVIEW.value:
        raise DomainError("Change request must be under review", code="conflict")

    cr.impact_hours = impact_hours
    cr.impact_cost = impact_cost
    cr.impact_timeline_days = impact_timeline_days
    cr.assessment_notes = assessment_notes
    cr.assigned_pm_id = cr.assigned_pm_id or actor.id
    await db.flush()

    await _apply_model_transition(
        db,
        cr=cr,
        to_status=ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
        actor=TransitionActor.INTERNAL_PM,
        org_id=actor.org_id,
        actor_id=actor.id,
    )

    org_settings = await _load_org_cr_settings(db, actor.org_id)
    next_status = await _setup_approval_rows(db, cr=cr, org_id=actor.org_id, org_settings=org_settings)

    if next_status == ChangeRequestStatus.APPROVED:
        await _apply_model_transition(
            db,
            cr=cr,
            to_status=ChangeRequestStatus.PENDING_APPROVAL.value,
            actor=TransitionActor.SYSTEM,
            org_id=actor.org_id,
            actor_id=actor.id,
        )
        await _apply_model_transition(
            db,
            cr=cr,
            to_status=ChangeRequestStatus.APPROVED.value,
            actor=TransitionActor.SYSTEM,
            org_id=actor.org_id,
            actor_id=actor.id,
        )
    else:
        await _apply_model_transition(
            db,
            cr=cr,
            to_status=ChangeRequestStatus.PENDING_APPROVAL.value,
            actor=TransitionActor.SYSTEM,
            org_id=actor.org_id,
            actor_id=actor.id,
        )

    return cr


async def decide_change_request(
    db: AsyncSession,
    *,
    cr_id: UUID,
    approval_id: UUID,
    decision: str,
    comment: str | None,
    apply_financial_impact: bool,
    internal_actor: User | None = None,
    portal_contact: Contact | None = None,
) -> ChangeRequest:
    cr = await get_change_request(db, cr_id)
    if cr is None:
        raise NotFoundError("Change request not found")
    if cr.status != ChangeRequestStatus.PENDING_APPROVAL.value:
        raise DomainError("Change request is not pending approval", code="conflict")

    approval = await get_approval_by_id(db, approval_id)
    if approval is None or approval.entity_id != cr.id or approval.entity_type != EntityType.CHANGE_REQUEST.value:
        raise NotFoundError("Approval not found")
    if approval.status != ApprovalStatus.PENDING.value:
        raise DomainError("Approval is not pending", code="conflict")

    if approval.approver_type == ApproverType.INTERNAL.value:
        if internal_actor is None or internal_actor.role not in {"project_manager", "admin"}:
            raise AuthorizationError("Internal approver required")
        actor_id = internal_actor.id
        org_id = internal_actor.org_id
    elif approval.approver_type == ApproverType.CLIENT.value:
        if portal_contact is None or portal_contact.company_id != cr.company_id:
            raise AuthorizationError("Client approver required")
        actor_id = portal_contact.id
        org_id = portal_contact.org_id
        apply_financial_impact = False
    else:
        raise DomainError("Unknown approver type", code="validation_error")

    if approval.approver_type == ApproverType.CLIENT.value:
        internal_rows = [
            a
            for a in await list_approvals_for_cr(db, cr.id)
            if a.approver_type == ApproverType.INTERNAL.value
        ]
        if internal_rows and any(a.status != ApprovalStatus.APPROVED.value for a in internal_rows):
            raise DomainError("Internal approval must complete before client approval", code="conflict")

    now = datetime.now(UTC)
    if decision == ApprovalStatus.REJECTED.value:
        approval.status = ApprovalStatus.REJECTED.value
        approval.comment = comment
        approval.approver_id = actor_id
        approval.decided_at = now
        await db.flush()
        await _apply_model_transition(
            db,
            cr=cr,
            to_status=ChangeRequestStatus.REJECTED.value,
            actor=TransitionActor.PORTAL_CONTACT if portal_contact else TransitionActor.INTERNAL_PM,
            org_id=org_id,
            actor_id=actor_id,
            reason=comment,
        )
        return cr

    if decision != ApprovalStatus.APPROVED.value:
        raise DomainError("Decision must be approved or rejected", code="validation_error")

    approval.status = ApprovalStatus.APPROVED.value
    approval.approver_id = actor_id
    approval.comment = comment
    approval.decided_at = now
    await db.flush()

    if approval.approver_type == ApproverType.INTERNAL.value and cr.requires_client_approval:
        existing_client = [
            a
            for a in await list_approvals_for_cr(db, cr.id)
            if a.approver_type == ApproverType.CLIENT.value
        ]
        if not existing_client:
            await create_approval_row(db, org_id=org_id, cr_id=cr.id, approver_type=ApproverType.CLIENT.value)
        return cr

    if not await _all_required_approvals_complete(db, cr):
        return cr

    await _apply_model_transition(
        db,
        cr=cr,
        to_status=ChangeRequestStatus.APPROVED.value,
        actor=TransitionActor.SYSTEM,
        org_id=org_id,
        actor_id=actor_id,
    )
    await _apply_model_transition(
        db,
        cr=cr,
        to_status=ChangeRequestStatus.IN_PROGRESS.value,
        actor=TransitionActor.SYSTEM,
        org_id=org_id,
        actor_id=actor_id,
    )
    if internal_actor is not None:
        await _apply_in_progress_side_effects(
            db,
            cr=cr,
            actor=internal_actor,
            apply_financial_impact=apply_financial_impact,
        )
    elif portal_contact is not None:
        pm = await db.get(User, cr.assigned_pm_id) if cr.assigned_pm_id else None
        if pm is not None:
            await _apply_in_progress_side_effects(
                db,
                cr=cr,
                actor=pm,
                apply_financial_impact=apply_financial_impact,
            )
    return cr


async def portal_resubmit_change_request(
    db: AsyncSession,
    *,
    contact: Contact,
    cr_id: UUID,
) -> ChangeRequest:
    cr = await get_change_request(db, cr_id)
    if cr is None or cr.company_id != contact.company_id:
        raise NotFoundError("Change request not found")
    if cr.status != ChangeRequestStatus.REJECTED.value:
        raise DomainError("Only rejected change requests can be resubmitted", code="conflict")
    org_settings = await _load_org_cr_settings(db, contact.org_id)
    snapshot = _snapshot_from_model(cr)
    result = apply_transition(
        snapshot,
        ChangeRequestStatus.SUBMITTED.value,
        TransitionActor.PORTAL_CONTACT,
        org_settings=org_settings,
    )
    before = _cr_to_dict(cr)
    cr.status = result.status
    cr.revision_count = result.revision_count
    cr.manager_escalation_flagged = result.manager_escalation_flagged
    cr.decided_at = None
    cr.submitted_at = datetime.now(UTC)
    await db.flush()
    await _write_transition_log(
        db,
        org_id=contact.org_id,
        actor_id=contact.id,
        cr=cr,
        before=before,
        to_status=cr.status,
    )
    if result.trigger_escalation:
        await _notify_manager_escalation(db, cr=cr, org_id=contact.org_id)
    return cr


async def assign_change_request(
    db: AsyncSession,
    *,
    actor: User,
    cr_id: UUID,
    assigned_pm_id: UUID | None,
) -> ChangeRequest:
    if actor.role not in {"project_manager", "admin"}:
        raise AuthorizationError("Only PM or admin can assign a change request")

    cr = await get_change_request(db, cr_id)
    if cr is None:
        raise NotFoundError("Change request not found")

    if assigned_pm_id is not None:
        pm = await db.get(User, assigned_pm_id)
        if pm is None or pm.deleted_at is not None or pm.org_id != actor.org_id:
            raise NotFoundError("User not found")

    before_pm_id = str(cr.assigned_pm_id) if cr.assigned_pm_id else None
    cr.assigned_pm_id = assigned_pm_id
    await db.flush()
    after_pm_id = str(assigned_pm_id) if assigned_pm_id else None
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="assign",
        entity_type=EntityType.CHANGE_REQUEST.value,
        entity_id=cr.id,
        diff={"before": {"assigned_pm_id": before_pm_id}, "after": {"assigned_pm_id": after_pm_id}},
    )
    return cr


async def get_change_requests(
    db: AsyncSession,
    *,
    project_id: UUID,
    status: str | None = None,
) -> list[ChangeRequest]:
    return await list_change_requests(db, project_id=project_id, status=status)


async def get_change_request_dashboard(db: AsyncSession, *, org_id: UUID) -> dict:
    org_settings = await _load_org_cr_settings(db, org_id)
    return await dashboard_aggregates(db, org_id=org_id, sla_days=org_settings.response_sla_days)


# Statuses where the change request is awaiting a response — matches the overdue
# definition in repository.dashboard_aggregates (ON_HOLD deliberately excluded,
# same as the frontend's RESPONSE_SLA_DAYS keys: a parked request has no clock).
RESPONSE_SLA_STATUSES = frozenset(
    {
        ChangeRequestStatus.SUBMITTED.value,
        ChangeRequestStatus.UNDER_REVIEW.value,
        ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
        ChangeRequestStatus.PENDING_APPROVAL.value,
    }
)


async def get_response_due_at(
    db: AsyncSession,
    *,
    org_id: UUID,
    status: str,
    submitted_at: datetime | None,
) -> tuple[datetime | None, bool]:
    if status not in RESPONSE_SLA_STATUSES or submitted_at is None:
        return None, False
    org_settings = await _load_org_cr_settings(db, org_id)
    due_at = submitted_at + timedelta(days=org_settings.response_sla_days)
    return due_at, datetime.now(UTC) > due_at


async def list_portal_cr_approvals(db: AsyncSession, *, company_id: UUID):
    return await list_pending_client_cr_approvals(db, company_id=company_id)
