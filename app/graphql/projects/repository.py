from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project


async def list_projects(db: AsyncSession, company_id: UUID | None = None) -> list[Project]:
    stmt = select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)
    if company_id:
        stmt = stmt.where(Project.company_id == company_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_project(db: AsyncSession, project_id: UUID) -> Project | None:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_project(db: AsyncSession, project: Project) -> Project:
    db.add(project)
    await db.flush()
    return project


async def soft_delete_project(db: AsyncSession, project: Project) -> Project:
    project.deleted_at = datetime.now(UTC)
    await db.flush()
    return project


async def get_projects_by_ids(db: AsyncSession, project_ids: list[UUID]) -> list[Project]:
    if not project_ids:
        return []
    result = await db.execute(
        select(Project).where(Project.id.in_(project_ids), Project.deleted_at.is_(None))
    )
    return list(result.scalars().all())
