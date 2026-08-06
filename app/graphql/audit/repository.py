from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.activity_log import ActivityLog


def _filtered(
    *,
    entity_type: str | None,
    entity_id: UUID | None = None,
    actor_id: UUID | None,
    start_at: datetime | None,
    end_at: datetime | None,
):
    query = select(ActivityLog)
    if entity_type is not None:
        query = query.where(ActivityLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(ActivityLog.entity_id == entity_id)
    if actor_id is not None:
        query = query.where(ActivityLog.actor_id == actor_id)
    if start_at is not None:
        query = query.where(ActivityLog.created_at >= start_at)
    if end_at is not None:
        query = query.where(ActivityLog.created_at <= end_at)
    return query


async def list_activity_logs(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    actor_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[ActivityLog]:
    query = _filtered(
        entity_type=entity_type, entity_id=entity_id, actor_id=actor_id, start_at=start_at, end_at=end_at
    )
    query = query.order_by(ActivityLog.created_at.desc()).limit(min(limit, 5000)).offset(max(offset, 0))
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_activity_logs(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    actor_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> int:
    query = _filtered(
        entity_type=entity_type, entity_id=entity_id, actor_id=actor_id, start_at=start_at, end_at=end_at
    )
    result = await db.execute(select(func.count()).select_from(query.subquery()))
    return int(result.scalar_one())
