from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import NotFoundError
from app.db.enums import ProjectStatus
from app.db.models.project import Project
from app.db.models.user import User
from app.graphql.projects.repository import create_project, get_project, list_projects, soft_delete_project


def _project_to_dict(project: Project) -> dict:
    return {
        "id": str(project.id),
        "company_id": str(project.company_id),
        "name": project.name,
        "status": project.status,
        "health": project.health,
        "budget": float(project.budget) if project.budget is not None else None,
    }


async def get_projects(db: AsyncSession, company_id: UUID | None = None) -> list[Project]:
    return await list_projects(db, company_id)


async def get_project_by_id(db: AsyncSession, project_id: UUID) -> Project:
    project = await get_project(db, project_id)
    if project is None:
        raise NotFoundError("Project not found")
    return project


async def create_project_record(
    db: AsyncSession,
    *,
    actor: User,
    company_id: UUID,
    name: str,
    description: str | None = None,
    status: str = "planning",
    priority: str | None = None,
    project_manager_id: UUID | None = None,
    start_date=None,
    end_date=None,
    budget: float | None = None,
    actual_cost: float | None = None,
    health: str | None = "on_track",
) -> Project:
    project = Project(
        org_id=actor.org_id,
        company_id=company_id,
        name=name,
        description=description,
        status=status,
        priority=priority,
        project_manager_id=project_manager_id,
        start_date=start_date,
        end_date=end_date,
        budget=budget,
        actual_cost=actual_cost,
        health=health,
    )
    await create_project(db, project)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="project",
        entity_id=project.id,
        diff={"after": _project_to_dict(project)},
    )
    return project


async def update_project_record(
    db: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    updates: dict,
) -> Project:
    project = await get_project_by_id(db, project_id)
    before = _project_to_dict(project)
    prev_status = project.status
    for key, value in updates.items():
        if value is not None and hasattr(project, key):
            setattr(project, key, value)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="project",
        entity_id=project.id,
        diff={"before": before, "after": _project_to_dict(project)},
    )
    if prev_status != ProjectStatus.COMPLETED.value and project.status == ProjectStatus.COMPLETED.value:
        from app.db.enums import SequenceTriggerType
        from app.graphql.contacts.repository import get_contacts_by_company_ids
        from app.graphql.retention.service import try_auto_enroll

        contacts = await get_contacts_by_company_ids(db, [project.company_id])
        primary = next((c for c in contacts if c.is_primary and c.deleted_at is None), None)
        if primary:
            await try_auto_enroll(
                db,
                org_id=actor.org_id,
                trigger_type=SequenceTriggerType.ON_PROJECT_COMPLETED.value,
                company_id=project.company_id,
                contact_id=primary.id,
                project_id=project.id,
                actor_id=actor.id,
            )
    return project


async def delete_project_record(db: AsyncSession, *, actor: User, project_id: UUID) -> Project:
    project = await get_project_by_id(db, project_id)
    before = _project_to_dict(project)
    await soft_delete_project(db, project)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="delete",
        entity_type="project",
        entity_id=project.id,
        diff={"before": before},
    )
    return project
