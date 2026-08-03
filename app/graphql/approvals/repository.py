from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ApprovalStatus, ApproverType, EntityType, MilestoneStatus
from app.db.models.approval import Approval
from app.db.models.planning import Milestone, ProjectPhase
from app.db.models.project import Project


async def get_pending_client_approvals(db: AsyncSession, *, company_id: UUID) -> list[Approval]:
    result = await db.execute(
        select(Approval)
        .join(Milestone, (Approval.entity_id == Milestone.id) & (Approval.entity_type == EntityType.MILESTONE.value))
        .join(ProjectPhase, Milestone.phase_id == ProjectPhase.id)
        .join(Project, ProjectPhase.project_id == Project.id)
        .where(
            Approval.status == ApprovalStatus.PENDING.value,
            Approval.approver_type == ApproverType.CLIENT.value,
            Project.company_id == company_id,
            Milestone.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
        .order_by(Approval.created_at.desc())
    )
    return list(result.scalars().all())


async def get_approval_by_id(db: AsyncSession, approval_id: UUID) -> Approval | None:
    return await db.get(Approval, approval_id)


async def list_approvals_for_milestone(db: AsyncSession, milestone_id: UUID) -> list[Approval]:
    result = await db.execute(
        select(Approval)
        .where(
            Approval.entity_type == EntityType.MILESTONE.value,
            Approval.entity_id == milestone_id,
        )
        .order_by(Approval.created_at.asc())
    )
    return list(result.scalars().all())


async def get_milestone_for_company(db: AsyncSession, *, milestone_id: UUID, company_id: UUID) -> Milestone | None:
    result = await db.execute(
        select(Milestone)
        .join(ProjectPhase, Milestone.phase_id == ProjectPhase.id)
        .join(Project, ProjectPhase.project_id == Project.id)
        .where(
            Milestone.id == milestone_id,
            Project.company_id == company_id,
            Milestone.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def create_milestone_approval(
    db: AsyncSession,
    *,
    org_id: UUID,
    milestone_id: UUID,
) -> Approval:
    existing = await db.execute(
        select(Approval).where(
            Approval.entity_type == EntityType.MILESTONE.value,
            Approval.entity_id == milestone_id,
            Approval.status == ApprovalStatus.PENDING.value,
        )
    )
    if existing.scalar_one_or_none() is not None:
        from app.core.exceptions import DomainError

        raise DomainError("Milestone already has a pending approval", code="conflict")

    row = Approval(
        org_id=org_id,
        entity_type=EntityType.MILESTONE.value,
        entity_id=milestone_id,
        approver_type=ApproverType.CLIENT.value,
        status=ApprovalStatus.PENDING.value,
    )
    db.add(row)
    await db.flush()
    return row


async def approve_milestone_record(
    db: AsyncSession,
    *,
    approval: Approval,
    milestone: Milestone,
    approver_id: UUID,
) -> Approval:
    now = datetime.now(UTC)
    approval.status = ApprovalStatus.APPROVED.value
    approval.approver_id = approver_id
    approval.decided_at = now
    milestone.status = MilestoneStatus.COMPLETED.value
    milestone.approved_at = now
    await db.flush()
    return approval


async def reject_milestone_record(
    db: AsyncSession,
    *,
    approval: Approval,
    milestone: Milestone,
    approver_id: UUID,
    comment: str,
) -> Approval:
    now = datetime.now(UTC)
    approval.status = ApprovalStatus.REJECTED.value
    approval.approver_id = approver_id
    approval.comment = comment
    approval.decided_at = now
    milestone.status = MilestoneStatus.IN_PROGRESS.value
    milestone.approved_at = None
    await db.flush()
    return approval
