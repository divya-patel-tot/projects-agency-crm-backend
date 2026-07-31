from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.activity_log import ActivityLog


async def write_activity_log(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    action: str,
    entity_type: str,
    entity_id: UUID,
    diff: dict | None,
) -> None:
    db.add(
        ActivityLog(
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            diff=diff,
        )
    )
