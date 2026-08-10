from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry
from strawberry.types import Info

from app.core.deps import require_role
from app.graphql.audit.service import get_audit_logs, get_audit_logs_count


@strawberry.type
class ActivityLogType:
    id: strawberry.ID
    actor_id: strawberry.ID
    action: str
    entity_type: str
    entity_id: strawberry.ID
    diff: strawberry.scalars.JSON | None
    created_at: datetime

    @classmethod
    def from_model(cls, row) -> "ActivityLogType":
        return cls(
            id=strawberry.ID(str(row.id)),
            actor_id=strawberry.ID(str(row.actor_id)),
            action=row.action,
            entity_type=row.entity_type,
            entity_id=strawberry.ID(str(row.entity_id)),
            diff=row.diff,
            created_at=row.created_at,
        )


@strawberry.type
class AuditQuery:
    @strawberry.field
    async def activity_logs(
        self,
        info: Info,
        entity_type: str | None = None,
        actor_id: strawberry.ID | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ActivityLogType]:
        ctx = require_role(info.context, "admin", "project_manager")
        rows = await get_audit_logs(
            ctx.db,
            entity_type=entity_type,
            actor_id=UUID(str(actor_id)) if actor_id else None,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=offset,
        )
        return [ActivityLogType.from_model(r) for r in rows]

    @strawberry.field
    async def activity_logs_count(
        self,
        info: Info,
        entity_type: str | None = None,
        actor_id: strawberry.ID | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> int:
        ctx = require_role(info.context, "admin", "project_manager")
        return await get_audit_logs_count(
            ctx.db,
            entity_type=entity_type,
            actor_id=UUID(str(actor_id)) if actor_id else None,
            start_at=start_at,
            end_at=end_at,
        )
