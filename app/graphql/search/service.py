"""Workspace-wide search across companies, contacts, projects and tasks.

Each group is capped at RESULT_LIMIT, prefix matches ranked ahead of
substring matches, with a separate count so the UI can show "N more".
Relies on RLS for org scoping, same as every other list query here.
"""

from dataclasses import dataclass

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import Company
from app.db.models.contact import Contact
from app.db.models.planning import Task
from app.db.models.project import Project

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


async def search_workspace(db: AsyncSession, *, query: str) -> SearchWorkspaceResult:
    pattern = f"%{query}%"
    prefix_pattern = f"{query}%"

    company_match = Company.name.ilike(pattern)
    company_rows = (
        await db.execute(
            select(Company)
            .where(Company.deleted_at.is_(None), company_match)
            .order_by(case((Company.name.ilike(prefix_pattern), 0), else_=1), Company.name)
            .limit(RESULT_LIMIT)
        )
    ).scalars().all()
    companies_count = (
        await db.execute(
            select(func.count()).select_from(Company).where(Company.deleted_at.is_(None), company_match)
        )
    ).scalar_one()

    full_name = Contact.first_name + " " + Contact.last_name
    contact_match = or_(full_name.ilike(pattern), Contact.email.ilike(pattern))
    contact_rows = (
        await db.execute(
            select(Contact)
            .where(Contact.deleted_at.is_(None), contact_match)
            .order_by(case((full_name.ilike(prefix_pattern), 0), else_=1), Contact.first_name)
            .limit(RESULT_LIMIT)
        )
    ).scalars().all()
    contacts_count = (
        await db.execute(
            select(func.count()).select_from(Contact).where(Contact.deleted_at.is_(None), contact_match)
        )
    ).scalar_one()

    project_match = Project.name.ilike(pattern)
    project_rows = (
        await db.execute(
            select(Project)
            .where(Project.deleted_at.is_(None), project_match)
            .order_by(case((Project.name.ilike(prefix_pattern), 0), else_=1), Project.name)
            .limit(RESULT_LIMIT)
        )
    ).scalars().all()
    projects_count = (
        await db.execute(
            select(func.count()).select_from(Project).where(Project.deleted_at.is_(None), project_match)
        )
    ).scalar_one()

    task_match = Task.title.ilike(pattern)
    task_rows = (
        await db.execute(
            select(Task)
            .where(Task.deleted_at.is_(None), task_match)
            .order_by(case((Task.title.ilike(prefix_pattern), 0), else_=1), Task.title)
            .limit(RESULT_LIMIT)
        )
    ).scalars().all()
    tasks_count = (
        await db.execute(select(func.count()).select_from(Task).where(Task.deleted_at.is_(None), task_match))
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
