import csv
import io
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.graphql.audit.repository import count_activity_logs, list_activity_logs


async def get_audit_logs(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    actor_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = 500,
    offset: int = 0,
):
    return await list_activity_logs(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )


async def get_audit_logs_count(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    actor_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> int:
    return await count_activity_logs(
        db, entity_type=entity_type, actor_id=actor_id, start_at=start_at, end_at=end_at
    )


def activity_logs_to_csv(rows) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "org_id",
            "actor_id",
            "action",
            "entity_type",
            "entity_id",
            "diff",
            "created_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                str(row.id),
                str(row.org_id),
                str(row.actor_id),
                row.action,
                row.entity_type,
                str(row.entity_id),
                json.dumps(row.diff, default=str) if row.diff is not None else "",
                row.created_at.isoformat(),
            ]
        )
    return buffer.getvalue()
