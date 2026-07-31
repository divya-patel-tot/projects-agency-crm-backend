from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.client_health import ClientHealthScore
from app.db.models.company import Company


async def list_health_history(
    db: AsyncSession,
    *,
    company_id: UUID,
    limit: int = 30,
) -> list[ClientHealthScore]:
    result = await db.execute(
        select(ClientHealthScore)
        .where(ClientHealthScore.company_id == company_id)
        .order_by(ClientHealthScore.calculated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_latest_health_score(db: AsyncSession, company_id: UUID) -> ClientHealthScore | None:
    result = await db.execute(
        select(ClientHealthScore)
        .where(ClientHealthScore.company_id == company_id)
        .order_by(ClientHealthScore.calculated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def insert_health_score(db: AsyncSession, row: ClientHealthScore) -> ClientHealthScore:
    db.add(row)
    await db.flush()
    return row


async def list_companies_for_scoring(db: AsyncSession) -> list[Company]:
    result = await db.execute(
        select(Company).where(
            Company.deleted_at.is_(None),
            Company.status.in_(["active", "paused"]),
        )
    )
    return list(result.scalars().all())


async def list_at_risk_companies(db: AsyncSession, *, threshold: float) -> list[Company]:
    result = await db.execute(
        select(Company).where(
            Company.deleted_at.is_(None),
            Company.status.in_(["active", "paused"]),
            Company.health_score.is_not(None),
            Company.health_score < threshold,
        )
        .order_by(Company.health_score.asc())
    )
    return list(result.scalars().all())
