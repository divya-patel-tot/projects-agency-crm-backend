from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import AuthorizationError, DomainError, NotFoundError
from app.db.enums import ProjectStatus, UserRole
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember
from app.db.models.user import User
from app.graphql.projects.repository import (
    create_project,
    get_project,
    get_project_member,
    list_projects,
    soft_delete_project,
)


def _project_to_dict(project: Project) -> dict:
    return {
        "id": str(project.id),
        "company_id": str(project.company_id),
        "name": project.name,
        "status": project.status,
        "health": project.health,
        "budget": float(project.budget) if project.budget is not None else None,
        "currency": project.currency,
    }


async def get_projects(
    db: AsyncSession, company_id: UUID | None = None, *, actor: User | None = None
) -> list[Project]:
    member_user_id = actor.id if actor is not None and actor.role == UserRole.TEAM_MEMBER.value else None
    return await list_projects(db, company_id, member_user_id)


async def get_project_by_id(db: AsyncSession, project_id: UUID, *, actor: User | None = None) -> Project:
    member_user_id = actor.id if actor is not None and actor.role == UserRole.TEAM_MEMBER.value else None
    project = await get_project(db, project_id, member_user_id)
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
    currency: str = "GBP",
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
        currency=currency,
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


async def _get_org_user(db: AsyncSession, user_id: UUID, org_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None or user.org_id != org_id:
        raise NotFoundError("User not found")
    return user


def _require_can_manage_membership(actor: User, target: User) -> None:
    # Same split as team invites: admins can put anyone on a project, project
    # managers can only add a team member — not another PM, not an admin.
    is_admin = actor.role == UserRole.ADMIN.value
    is_pm_adding_team_member = (
        actor.role == UserRole.PROJECT_MANAGER.value and target.role == UserRole.TEAM_MEMBER.value
    )
    if not (is_admin or is_pm_adding_team_member):
        raise AuthorizationError(
            "Only admins can add any role to a project, or project managers adding a team member"
        )


async def add_project_member_record(
    db: AsyncSession, *, actor: User, project_id: UUID, user_id: UUID
) -> User:
    project = await get_project_by_id(db, project_id)
    target = await _get_org_user(db, user_id, actor.org_id)
    _require_can_manage_membership(actor, target)

    existing = await get_project_member(db, project.id, target.id)
    if existing is not None:
        raise DomainError("This person is already on the project.", code="bad_user_input")

    db.add(ProjectMember(org_id=actor.org_id, project_id=project.id, user_id=target.id))
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="project",
        entity_id=project.id,
        diff={"member_added": target.name},
    )
    return target


async def remove_project_member_record(
    db: AsyncSession, *, actor: User, project_id: UUID, user_id: UUID
) -> bool:
    project = await get_project_by_id(db, project_id)
    target = await _get_org_user(db, user_id, actor.org_id)
    _require_can_manage_membership(actor, target)

    membership = await get_project_member(db, project.id, target.id)
    if membership is None:
        raise NotFoundError("This person isn't on the project.")

    await db.delete(membership)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="project",
        entity_id=project.id,
        diff={"member_removed": target.name},
    )
    return True
