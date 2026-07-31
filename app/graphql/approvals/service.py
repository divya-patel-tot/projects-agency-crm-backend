from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError, NotFoundError
from app.db.enums import ApprovalStatus, EntityType
from app.graphql.approvals.repository import (
    approve_milestone_record,
    create_milestone_approval,
    get_approval_by_id,
    get_milestone_for_company,
    get_pending_client_approvals,
    reject_milestone_record,
)


async def mark_milestone_ready_for_review(db: AsyncSession, *, org_id: UUID, milestone_id: UUID):
    from app.db.models.planning import Milestone

    milestone = await db.get(Milestone, milestone_id)
    if milestone is None or milestone.deleted_at is not None:
        raise NotFoundError("Milestone not found")
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

    return await approve_milestone_record(
        db,
        approval=approval,
        milestone=milestone,
        approver_id=contact_id,
    )


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

    return await reject_milestone_record(
        db,
        approval=approval,
        milestone=milestone,
        approver_id=contact_id,
        comment=comment.strip(),
    )
