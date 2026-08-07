"""Workspace-wide search across companies, contacts, projects and tasks.

Each group is capped at RESULT_LIMIT, prefix matches ranked ahead of
substring matches, with a separate count so the UI can show "N more".
Relies on RLS for org scoping, same as every other list query here.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import Company
from app.db.models.contact import Contact
from app.db.models.planning import Task
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember

RESULT_LIMIT = 8


@dataclass
class SearchWorkspaceResult:
    companies: list[Company]
    companies_count: int
    contacts: list[Contact]
    contacts_count: int
    projects: list[Project]
    projects_count: int
    tasks: list[Task]
    tasks_count: int


def _member_project_ids_subquery(member_user_id: UUID):
    return select(ProjectMember.project_id).where(ProjectMember.user_id == member_user_id)


def _member_company_ids_subquery(member_user_id: UUID):
    return (
        select(Project.company_id)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == member_user_id)
    )


async def search_workspace(
    db: AsyncSession, *, query: str, member_user_id: UUID | None = None
) -> SearchWorkspaceResult:
    pattern = f"%{query}%"
    prefix_pattern = f"{query}%"

    company_match = Company.name.ilike(pattern)
    company_scope = [Company.deleted_at.is_(None), company_match]
    if member_user_id:
        company_scope.append(Company.id.in_(_member_company_ids_subquery(member_user_id)))
    company_rows = (
        await db.execute(
            select(Company)
            .where(*company_scope)
            .order_by(case((Company.name.ilike(prefix_pattern), 0), else_=1), Company.name)
            .limit(RESULT_LIMIT)
        )
    ).scalars().all()
    companies_count = (
        await db.execute(select(func.count()).select_from(Company).where(*company_scope))
    ).scalar_one()

    full_name = Contact.first_name + " " + Contact.last_name
    contact_match = or_(full_name.ilike(pattern), Contact.email.ilike(pattern))
    contact_scope = [Contact.deleted_at.is_(None), contact_match]
    if member_user_id:
        contact_scope.append(Contact.company_id.in_(_member_company_ids_subquery(member_user_id)))
    contact_rows = (
        await db.execute(
            select(Contact)
            .where(*contact_scope)
            .order_by(case((full_name.ilike(prefix_pattern), 0), else_=1), Contact.first_name)
            .limit(RESULT_LIMIT)
        )
    ).scalars().all()
    contacts_count = (
        await db.execute(select(func.count()).select_from(Contact).where(*contact_scope))
    ).scalar_one()

    project_match = Project.name.ilike(pattern)
    project_scope = [Project.deleted_at.is_(None), project_match]
    if member_user_id:
        project_scope.append(Project.id.in_(_member_project_ids_subquery(member_user_id)))
    project_rows = (
        await db.execute(
            select(Project)
            .where(*project_scope)
            .order_by(case((Project.name.ilike(prefix_pattern), 0), else_=1), Project.name)
            .limit(RESULT_LIMIT)
        )
    ).scalars().all()
    projects_count = (
        await db.execute(select(func.count()).select_from(Project).where(*project_scope))
    ).scalar_one()

    task_match = Task.title.ilike(pattern)
    task_scope = [Task.deleted_at.is_(None), task_match]
    if member_user_id:
        task_scope.append(Task.project_id.in_(_member_project_ids_subquery(member_user_id)))
    task_rows = (
        await db.execute(
            select(Task)
            .where(*task_scope)
            .order_by(case((Task.title.ilike(prefix_pattern), 0), else_=1), Task.title)
            .limit(RESULT_LIMIT)
        )
    ).scalars().all()
    tasks_count = (
        await db.execute(select(func.count()).select_from(Task).where(*task_scope))
    ).scalar_one()

    return SearchWorkspaceResult(
        companies=list(company_rows),
        companies_count=companies_count,
        contacts=list(contact_rows),
        contacts_count=contacts_count,
        projects=list(project_rows),
        projects_count=projects_count,
        tasks=list(task_rows),
        tasks_count=tasks_count,
    )
