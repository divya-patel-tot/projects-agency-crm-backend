from datetime import datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import require_authenticated
from app.core.exceptions import DomainError, NotFoundError
from app.graphql.notifications.service import (
    get_notifications,
    get_unread_count,
    mark_all_notifications_read_record,
    mark_notification_read_record,
)


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, NotFoundError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class NotificationType:
    id: strawberry.ID
    type: str
    title: str
    message: str
    link: str | None
    read_at: datetime | None
    created_at: datetime

    @classmethod
    def from_model(cls, row) -> "NotificationType":
        return cls(
            id=strawberry.ID(str(row.id)),
            type=row.type,
            title=row.title,
            message=row.message,
            link=row.link,
            read_at=row.read_at,
            created_at=row.created_at,
        )


@strawberry.type
class NotificationQuery:
    @strawberry.field
    async def notifications(
        self, info: Info, unread_only: bool = False, limit: int = 50, offset: int = 0
    ) -> list[NotificationType]:
        ctx = require_authenticated(info.context)
        rows = await get_notifications(ctx.db, actor=ctx.user, unread_only=unread_only, limit=limit, offset=offset)
        return [NotificationType.from_model(row) for row in rows]

    @strawberry.field
    async def unread_notification_count(self, info: Info) -> int:
        ctx = require_authenticated(info.context)
        return await get_unread_count(ctx.db, actor=ctx.user)


@strawberry.type
class NotificationMutation:
    @strawberry.mutation
    async def mark_notification_read(self, info: Info, id: strawberry.ID) -> NotificationType:
        ctx = require_authenticated(info.context)
        try:
            row = await mark_notification_read_record(ctx.db, actor=ctx.user, notification_id=UUID(str(id)))
            return NotificationType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def mark_all_notifications_read(self, info: Info) -> bool:
        ctx = require_authenticated(info.context)
        return await mark_all_notifications_read_record(ctx.db, actor=ctx.user)
