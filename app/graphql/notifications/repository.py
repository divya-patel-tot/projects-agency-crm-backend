from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.notification import Notification


async def create_notification(db: AsyncSession, notification: Notification) -> Notification:
    db.add(notification)
    await db.flush()
    return notification


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: UUID,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(min(limit, 200)).offset(max(offset, 0))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_unread(db: AsyncSession, *, user_id: UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
    )
    return int(result.scalar_one())


async def get_notification(db: AsyncSession, notification_id: UUID, user_id: UUID) -> Notification | None:
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def mark_all_read(db: AsyncSession, *, user_id: UUID) -> None:
    await db.execute(
        sa_update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await db.flush()
