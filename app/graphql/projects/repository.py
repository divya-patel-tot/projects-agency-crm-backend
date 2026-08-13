import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError
from app.db.models.contact import Contact
from app.db.models.planning import ProjectColumn
from app.db.models.project import Project
from app.db.models.project_contact import ProjectContact
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


async def ensure_project_member(db: AsyncSession, *, org_id: UUID, project_id: UUID, user_id: UUID) -> None:
    """Add someone to a project's roster if they aren't on it already — the
    quiet side effect of being assigned a task or set as project manager, not
    a user-initiated action, so it skips the Team-tab permission checks.
    """
    existing = await get_project_member(db, project_id, user_id)
    if existing is not None:
        return
    db.add(ProjectMember(org_id=org_id, project_id=project_id, user_id=user_id))
    await db.flush()


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


async def get_projects_by_company_ids(db: AsyncSession, company_ids: list[UUID]) -> list[Project]:
    if not company_ids:
        return []
    result = await db.execute(
        select(Project)
        .where(Project.company_id.in_(company_ids), Project.deleted_at.is_(None))
        .order_by(Project.name)
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


async def get_project_contact(db: AsyncSession, project_id: UUID, contact_id: UUID) -> ProjectContact | None:
    result = await db.execute(
        select(ProjectContact).where(
            ProjectContact.project_id == project_id, ProjectContact.contact_id == contact_id
        )
    )
    return result.scalar_one_or_none()


async def get_contacts_by_project_ids(db: AsyncSession, project_ids: list[UUID]) -> list[tuple[UUID, Contact]]:
    if not project_ids:
        return []
    result = await db.execute(
        select(ProjectContact.project_id, Contact)
        .join(Contact, Contact.id == ProjectContact.contact_id)
        .where(ProjectContact.project_id.in_(project_ids), Contact.deleted_at.is_(None))
        .order_by(Contact.first_name, Contact.last_name)
    )
    return list(result.all())


async def list_columns_for_project(db: AsyncSession, project_id: UUID) -> list[ProjectColumn]:
    result = await db.execute(
        select(ProjectColumn)
        .where(ProjectColumn.project_id == project_id)
        .order_by(ProjectColumn.order_index)
    )
    return list(result.scalars().all())


async def get_columns_by_project_ids(db: AsyncSession, project_ids: list[UUID]) -> list[ProjectColumn]:
    if not project_ids:
        return []
    result = await db.execute(
        select(ProjectColumn)
        .where(ProjectColumn.project_id.in_(project_ids))
        .order_by(ProjectColumn.order_index)
    )
    return list(result.scalars().all())


async def get_project_column(db: AsyncSession, column_id: UUID) -> ProjectColumn | None:
    result = await db.execute(select(ProjectColumn).where(ProjectColumn.id == column_id))
    return result.scalar_one_or_none()


async def get_terminal_column(db: AsyncSession, project_id: UUID) -> ProjectColumn | None:
    result = await db.execute(
        select(ProjectColumn).where(
            ProjectColumn.project_id == project_id, ProjectColumn.is_terminal.is_(True)
        )
    )
    return result.scalar_one_or_none()


async def get_first_column(db: AsyncSession, project_id: UUID) -> ProjectColumn | None:
    result = await db.execute(
        select(ProjectColumn)
        .where(ProjectColumn.project_id == project_id)
        .order_by(ProjectColumn.order_index)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def reorder_column_indices(
    db: AsyncSession, project_id: UUID, ordered_ids: list[UUID]
) -> list[ProjectColumn]:
    columns = await list_columns_for_project(db, project_id)
    current_ids = {column.id for column in columns}
    if set(ordered_ids) != current_ids or len(ordered_ids) != len(columns):
        raise DomainError("orderedColumnIds must match the exact current column set", code="reorder_invalid")

    column_map = {column.id: column for column in columns}
    for index, column_id in enumerate(ordered_ids):
        column_map[column_id].order_index = index
    await db.flush()
    return [column_map[cid] for cid in ordered_ids]


_SLUG_RUN = re.compile(r"[^a-z0-9]+")


def slugify_column_code(label: str, existing_codes: set[str]) -> str:
    base = _SLUG_RUN.sub("_", label.strip().lower()).strip("_") or "column"
    code = base
    suffix = 2
    while code in existing_codes:
        code = f"{base}_{suffix}"
        suffix += 1
    return code


async def seed_default_columns(db: AsyncSession, *, org_id: UUID, project_id: UUID) -> list[ProjectColumn]:
    """The same 4-column default (todo/in_progress/review/done, done
    terminal) every pre-existing project got backfilled with in migration
    022 — called here so every newly created project starts the same way.
    """
    defaults = [
        ("todo", "To do", 0, False),
        ("in_progress", "In progress", 1, False),
        ("review", "In review", 2, False),
        ("done", "Done", 3, True),
    ]
    columns = [
        ProjectColumn(
            org_id=org_id,
            project_id=project_id,
            code=code,
            label=label,
            order_index=order_index,
            is_terminal=is_terminal,
        )
        for code, label, order_index, is_terminal in defaults
    ]
    db.add_all(columns)
    await db.flush()
    return columns
