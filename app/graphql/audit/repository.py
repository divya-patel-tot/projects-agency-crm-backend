from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.activity_log import ActivityLog


async def list_activity_logs(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    actor_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[ActivityLog]:
    query = select(ActivityLog).order_by(ActivityLog.created_at.desc())
    if entity_type is not None:
        query = query.where(ActivityLog.entity_type == entity_type)
    if actor_id is not None:
        query = query.where(ActivityLog.actor_id == actor_id)
    if start_at is not None:
        query = query.where(ActivityLog.created_at >= start_at)
    if end_at is not None:
        query = query.where(ActivityLog.created_at <= end_at)
    query = query.limit(min(limit, 5000)).offset(max(offset, 0))
    result = await db.execute(query)
    return list(result.scalars().all())
