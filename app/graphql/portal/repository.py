from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import Company
from app.db.models.project import Project


async def get_company_by_id(db: AsyncSession, company_id: UUID) -> Company | None:
    result = await db.execute(
        select(Company).where(
            Company.id == company_id,
            Company.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_projects_for_company(db: AsyncSession, *, company_id: UUID) -> list[Project]:
    result = await db.execute(
        select(Project)
        .where(
            Project.company_id == company_id,
            Project.deleted_at.is_(None),
        )
        .order_by(Project.name)
    )
    return list(result.scalars().all())


async def get_project_for_company(db: AsyncSession, *, project_id: UUID, company_id: UUID) -> Project | None:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.company_id == company_id,
            Project.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()
