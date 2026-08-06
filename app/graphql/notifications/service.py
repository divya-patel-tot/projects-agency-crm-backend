from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.notification import Notification
from app.db.models.user import User
from app.graphql.notifications.repository import (
    count_unread,
    create_notification,
    get_notification,
    list_notifications,
    mark_all_read,
)
from app.graphql.profile.preferences import normalize_preferences


async def notify(
    db: AsyncSession,
    *,
    org_id: UUID,
    recipient: User,
    category: str,
    type_: str,
    title: str,
    message: str,
    link: str | None = None,
) -> Notification | None:
    """Create an in-app notification for `recipient`, honoring their
    per-category `in_app` preference. Silently does nothing if they've
    turned that category off, or if they're the one who triggered it.
    """
    prefs = normalize_preferences(recipient.preferences, portal=False)
    if not prefs.get(category, {}).get("in_app", True):
        return None

    notification = Notification(
        org_id=org_id,
        user_id=recipient.id,
        type=type_,
        title=title,
        message=message,
        link=link,
    )
    return await create_notification(db, notification)


async def get_notifications(
    db: AsyncSession, *, actor: User, unread_only: bool = False, limit: int = 50, offset: int = 0
) -> list[Notification]:
    return await list_notifications(db, user_id=actor.id, unread_only=unread_only, limit=limit, offset=offset)


async def get_unread_count(db: AsyncSession, *, actor: User) -> int:
    return await count_unread(db, user_id=actor.id)


async def mark_notification_read_record(db: AsyncSession, *, actor: User, notification_id: UUID) -> Notification:
    notification = await get_notification(db, notification_id, actor.id)
    if notification is None:
        raise NotFoundError("Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.flush()
    return notification


async def mark_all_notifications_read_record(db: AsyncSession, *, actor: User) -> bool:
    await mark_all_read(db, user_id=actor.id)
    return True
