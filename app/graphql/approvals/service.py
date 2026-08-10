from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, DomainError, NotFoundError
from app.db.enums import ApprovalStatus, EntityType
from app.db.models.user import User
from app.graphql.approvals.repository import (
    approve_milestone_record,
    create_milestone_approval,
    get_approval_by_id,
    get_milestone_for_company,
    get_pending_client_approvals,
    reject_milestone_record,
)
from app.graphql.notifications.service import notify
from app.graphql.projects.service import actor_can_mutate_project


async def _notify_pm_of_milestone_response(db: AsyncSession, *, milestone, decision: str) -> None:
    from app.db.models.planning import ProjectPhase
    from app.db.models.project import Project
    from app.db.models.user import User

    phase = await db.get(ProjectPhase, milestone.phase_id)
    if phase is None:
        return
    project = await db.get(Project, phase.project_id)
    if project is None or project.project_manager_id is None:
        return
    pm = await db.get(User, project.project_manager_id)
    if pm is None or pm.deleted_at is not None:
        return
    await notify(
        db,
        org_id=project.org_id,
        recipient=pm,
        category="milestone_approvals",
        type_=f"milestone.{decision}",
        title="Client responded to a milestone" if decision == "changes_requested" else "Milestone approved",
        message=(
            f'The client requested changes on "{milestone.title}"'
            if decision == "changes_requested"
            else f'The client approved "{milestone.title}"'
        ),
        link=f"/projects/{project.id}/milestones",
    )


async def mark_milestone_ready_for_review(db: AsyncSession, *, org_id: UUID, milestone_id: UUID, actor: User):
    from app.db.models.planning import Milestone, ProjectPhase

    milestone = await db.get(Milestone, milestone_id)
    if milestone is None or milestone.deleted_at is not None:
        raise NotFoundError("Milestone not found")
    phase = await db.get(ProjectPhase, milestone.phase_id)
    if phase is not None and not await actor_can_mutate_project(db, actor, phase.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    return await create_milestone_approval(db, org_id=org_id, milestone_id=milestone_id)


async def list_pending_portal_approvals(db: AsyncSession, *, company_id: UUID):
    return await get_pending_client_approvals(db, company_id=company_id)


async def approve_milestone(db: AsyncSession, *, approval_id: UUID, company_id: UUID, contact_id: UUID):
    approval = await get_approval_by_id(db, approval_id)
    if approval is None or approval.entity_type != EntityType.MILESTONE.value:
        raise NotFoundError("Approval not found")
    if approval.status != ApprovalStatus.PENDING.value:
        raise DomainError("Approval is not pending", code="conflict")

    milestone = await get_milestone_for_company(db, milestone_id=approval.entity_id, company_id=company_id)
    if milestone is None:
        raise NotFoundError("Approval not found")

    result = await approve_milestone_record(
        db,
        approval=approval,
        milestone=milestone,
        approver_id=contact_id,
    )
    await _notify_pm_of_milestone_response(db, milestone=milestone, decision="approved")
    return result


async def request_milestone_changes(
    db: AsyncSession,
    *,
    approval_id: UUID,
    company_id: UUID,
    contact_id: UUID,
    comment: str,
):
    if not comment.strip():
        raise DomainError("Comment is required", code="validation_error")

    approval = await get_approval_by_id(db, approval_id)
    if approval is None or approval.entity_type != EntityType.MILESTONE.value:
        raise NotFoundError("Approval not found")
    if approval.status != ApprovalStatus.PENDING.value:
        raise DomainError("Approval is not pending", code="conflict")

    milestone = await get_milestone_for_company(db, milestone_id=approval.entity_id, company_id=company_id)
    if milestone is None:
        raise NotFoundError("Approval not found")

    result = await reject_milestone_record(
        db,
        approval=approval,
        milestone=milestone,
        approver_id=contact_id,
        comment=comment.strip(),
    )
    await _notify_pm_of_milestone_response(db, milestone=milestone, decision="changes_requested")
    return result
