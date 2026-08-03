from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ApprovalStatus, ApproverType, ChangeRequestStatus, EntityType
from app.db.models.approval import Approval
from app.db.models.change_request import ChangeRequest, ChangeRequestAttachment
from app.db.models.notification import Notification
from app.db.models.organization import Organization
from app.db.models.planning import Milestone, ProjectPhase, Task
from app.db.models.project import Project


async def get_change_request(db: AsyncSession, cr_id: UUID) -> ChangeRequest | None:
    result = await db.execute(
        select(ChangeRequest).where(
            ChangeRequest.id == cr_id,
            ChangeRequest.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_change_requests(
    db: AsyncSession,
    *,
    project_id: UUID,
    status: str | None = None,
) -> list[ChangeRequest]:
    query = select(ChangeRequest).where(
        ChangeRequest.project_id == project_id,
        ChangeRequest.deleted_at.is_(None),
    )
    if status is not None:
        query = query.where(ChangeRequest.status == status)
    query = query.order_by(ChangeRequest.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_change_requests_for_company(
    db: AsyncSession,
    *,
    company_id: UUID,
) -> list[ChangeRequest]:
    result = await db.execute(
        select(ChangeRequest)
        .where(
            ChangeRequest.company_id == company_id,
            ChangeRequest.deleted_at.is_(None),
        )
        .order_by(ChangeRequest.created_at.desc())
    )
    return list(result.scalars().all())


async def create_change_request_row(db: AsyncSession, row: ChangeRequest) -> ChangeRequest:
    db.add(row)
    await db.flush()
    return row


async def get_project_for_cr(db: AsyncSession, project_id: UUID) -> Project | None:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_project_for_company(
    db: AsyncSession,
    *,
    project_id: UUID,
    company_id: UUID,
) -> Project | None:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.company_id == company_id,
            Project.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_org_settings(db: AsyncSession, org_id: UUID) -> dict:
    org = await db.get(Organization, org_id)
    return org.settings if org and org.settings else {}


async def list_approvals_for_cr(db: AsyncSession, cr_id: UUID) -> list[Approval]:
    result = await db.execute(
        select(Approval)
        .where(
            Approval.entity_type == EntityType.CHANGE_REQUEST.value,
            Approval.entity_id == cr_id,
        )
        .order_by(Approval.created_at.asc())
    )
    return list(result.scalars().all())


async def get_approval_by_id(db: AsyncSession, approval_id: UUID) -> Approval | None:
    return await db.get(Approval, approval_id)


async def create_approval_row(
    db: AsyncSession,
    *,
    org_id: UUID,
    cr_id: UUID,
    approver_type: str,
) -> Approval:
    row = Approval(
        org_id=org_id,
        entity_type=EntityType.CHANGE_REQUEST.value,
        entity_id=cr_id,
        approver_type=approver_type,
        status=ApprovalStatus.PENDING.value,
    )
    db.add(row)
    await db.flush()
    return row


async def list_pending_client_cr_approvals(db: AsyncSession, *, company_id: UUID) -> list[Approval]:
    result = await db.execute(
        select(Approval)
        .join(ChangeRequest, Approval.entity_id == ChangeRequest.id)
        .where(
            Approval.entity_type == EntityType.CHANGE_REQUEST.value,
            Approval.status == ApprovalStatus.PENDING.value,
            Approval.approver_type == ApproverType.CLIENT.value,
            ChangeRequest.company_id == company_id,
            ChangeRequest.deleted_at.is_(None),
            ChangeRequest.status == ChangeRequestStatus.PENDING_APPROVAL.value,
        )
        .order_by(Approval.created_at.desc())
    )
    return list(result.scalars().all())


async def get_first_phase_for_project(db: AsyncSession, project_id: UUID) -> ProjectPhase | None:
    result = await db.execute(
        select(ProjectPhase)
        .where(
            ProjectPhase.project_id == project_id,
            ProjectPhase.deleted_at.is_(None),
        )
        .order_by(ProjectPhase.order_index.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_project_milestones(db: AsyncSession, project_id: UUID) -> list[Milestone]:
    result = await db.execute(
        select(Milestone)
        .join(ProjectPhase, Milestone.phase_id == ProjectPhase.id)
        .where(
            ProjectPhase.project_id == project_id,
            Milestone.deleted_at.is_(None),
            ProjectPhase.deleted_at.is_(None),
        )
        .order_by(ProjectPhase.order_index.asc(), Milestone.order_index.asc())
    )
    return list(result.scalars().all())


async def list_project_tasks(db: AsyncSession, project_id: UUID) -> list[Task]:
    result = await db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def create_task_row(db: AsyncSession, task: Task) -> Task:
    db.add(task)
    await db.flush()
    return task


async def create_notification_row(
    db: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
    type: str,
    title: str,
    message: str,
    link: str | None = None,
) -> Notification:
    row = Notification(
        org_id=org_id,
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        link=link,
    )
    db.add(row)
    await db.flush()
    return row


async def dashboard_aggregates(
    db: AsyncSession,
    *,
    org_id: UUID,
    sla_days: int,
) -> dict:
    now = datetime.now(UTC)
    sla_cutoff = now - timedelta(days=sla_days)
    open_statuses = [
        ChangeRequestStatus.SUBMITTED.value,
        ChangeRequestStatus.UNDER_REVIEW.value,
        ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
        ChangeRequestStatus.PENDING_APPROVAL.value,
        ChangeRequestStatus.APPROVED.value,
        ChangeRequestStatus.IN_PROGRESS.value,
        ChangeRequestStatus.IMPLEMENTED.value,
        ChangeRequestStatus.ON_HOLD.value,
    ]
    base = select(ChangeRequest).where(
        ChangeRequest.org_id == org_id,
        ChangeRequest.deleted_at.is_(None),
    )

    open_result = await db.execute(
        base.where(ChangeRequest.status.in_(open_statuses)).with_only_columns(func.count())
    )
    pending_result = await db.execute(
        base.where(ChangeRequest.status == ChangeRequestStatus.PENDING_APPROVAL.value).with_only_columns(func.count())
    )
    overdue_result = await db.execute(
        base.where(
            ChangeRequest.status.in_(
                [
                    ChangeRequestStatus.SUBMITTED.value,
                    ChangeRequestStatus.UNDER_REVIEW.value,
                    ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
                    ChangeRequestStatus.PENDING_APPROVAL.value,
                ]
            ),
            ChangeRequest.submitted_at.is_not(None),
            ChangeRequest.submitted_at < sla_cutoff,
        ).with_only_columns(func.count())
    )

    aging_rows = await db.execute(
        select(ChangeRequest.status, func.count())
        .where(
            ChangeRequest.org_id == org_id,
            ChangeRequest.deleted_at.is_(None),
            ChangeRequest.status.in_(open_statuses),
        )
        .group_by(ChangeRequest.status)
    )
    aging = {status: count for status, count in aging_rows.all()}

    return {
        "open_count": open_result.scalar_one(),
        "pending_approval_count": pending_result.scalar_one(),
        "overdue_count": overdue_result.scalar_one(),
        "aging_by_status": aging,
        "sla_days": sla_days,
    }
