from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import Company


async def list_companies(db: AsyncSession) -> list[Company]:
    result = await db.execute(
        select(Company).where(Company.deleted_at.is_(None)).order_by(Company.name)
    )
    return list(result.scalars().all())


async def get_company(db: AsyncSession, company_id: UUID) -> Company | None:
    result = await db.execute(
        select(Company).where(Company.id == company_id, Company.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_company(db: AsyncSession, company: Company) -> Company:
    db.add(company)
    await db.flush()
    return company


async def soft_delete_company(db: AsyncSession, company: Company) -> Company:
    company.deleted_at = datetime.now(UTC)
    await db.flush()
    return company
