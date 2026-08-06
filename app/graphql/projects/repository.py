from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.project_member import ProjectMember
from app.db.models.user import User


async def list_projects(
    db: AsyncSession, company_id: UUID | None = None, member_user_id: UUID | None = None
) -> list[Project]:
    stmt = select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)
    if company_id:
        stmt = stmt.where(Project.company_id == company_id)
    if member_user_id:
        stmt = stmt.where(
            Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == member_user_id))
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_project(
    db: AsyncSession, project_id: UUID, member_user_id: UUID | None = None
) -> Project | None:
    stmt = select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    if member_user_id:
        stmt = stmt.where(
            Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == member_user_id))
        )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_project_member(db: AsyncSession, project_id: UUID, user_id: UUID) -> ProjectMember | None:
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
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


async def get_members_by_project_ids(db: AsyncSession, project_ids: list[UUID]) -> list[tuple[UUID, User]]:
    if not project_ids:
        return []
    result = await db.execute(
        select(ProjectMember.project_id, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id.in_(project_ids), User.deleted_at.is_(None))
        .order_by(User.name)
    )
    return list(result.all())
