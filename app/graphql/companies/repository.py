from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import Company
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember


def _member_company_ids_subquery(member_user_id: UUID):
    return (
        select(Project.company_id)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == member_user_id)
    )


async def list_companies(
    db: AsyncSession,
    *,
    org_id: UUID | None = None,
    member_user_id: UUID | None = None,
) -> list[Company]:
    stmt = select(Company).where(Company.deleted_at.is_(None)).order_by(Company.name)
    if org_id is not None:
        stmt = stmt.where(Company.org_id == org_id)
    if member_user_id:
        stmt = stmt.where(Company.id.in_(_member_company_ids_subquery(member_user_id)))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_company(
    db: AsyncSession,
    company_id: UUID,
    *,
    org_id: UUID | None = None,
    member_user_id: UUID | None = None,
) -> Company | None:
    stmt = select(Company).where(Company.id == company_id, Company.deleted_at.is_(None))
    if org_id is not None:
        stmt = stmt.where(Company.org_id == org_id)
    if member_user_id:
        stmt = stmt.where(Company.id.in_(_member_company_ids_subquery(member_user_id)))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_company(db: AsyncSession, company: Company) -> Company:
    db.add(company)
    await db.flush()
    return company


async def soft_delete_company(db: AsyncSession, company: Company) -> Company:
    company.deleted_at = datetime.now(UTC)
    await db.flush()
    return company
