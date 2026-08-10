from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import AuthorizationError, DomainError, NotFoundError
from app.db.enums import ProjectStatus, UserRole
from app.db.models.contact import Contact
from app.db.models.planning import Task
from app.db.models.project import Project
from app.db.models.project_contact import ProjectContact
from app.db.models.project_member import ProjectMember
from app.db.models.user import User
from app.graphql.notifications.service import notify
from app.graphql.projects.repository import (
    create_project,
    ensure_project_member,
    get_project,
    get_project_contact,
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


_PROJECT_SCOPED_ROLES = (UserRole.TEAM_MEMBER.value, UserRole.PROJECT_MANAGER.value)


async def get_projects(
    db: AsyncSession, company_id: UUID | None = None, *, actor: User | None = None
) -> list[Project]:
    member_user_id = actor.id if actor is not None and actor.role in _PROJECT_SCOPED_ROLES else None
    return await list_projects(db, company_id, member_user_id)


async def actor_can_access_project(db: AsyncSession, actor: User, project_id: UUID) -> bool:
    """Whether `actor` can see data scoped to `project_id` — admins see
    everything; a team member or project manager only what they're on.
    Mirrors the scoping in `get_projects`/`get_project_by_id`, for the
    project-scoped endpoints (change requests, phases, workload) that don't
    go through those two directly.
    """
    if actor.role not in _PROJECT_SCOPED_ROLES:
        return True
    member = await get_project_member(db, project_id, actor.id)
    return member is not None


async def get_project_by_id(db: AsyncSession, project_id: UUID, *, actor: User | None = None) -> Project:
    member_user_id = actor.id if actor is not None and actor.role in _PROJECT_SCOPED_ROLES else None
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
    if project_manager_id is not None:
        await ensure_project_member(db, org_id=actor.org_id, project_id=project.id, user_id=project_manager_id)
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
    prev_pm_id = project.project_manager_id
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
    if project.project_manager_id is not None and project.project_manager_id != prev_pm_id:
        await ensure_project_member(db, org_id=actor.org_id, project_id=project.id, user_id=project.project_manager_id)
    if prev_pm_id is not None and prev_pm_id != project.project_manager_id:
        await _remove_stale_pm_membership(db, actor=actor, project=project, old_pm_id=prev_pm_id)
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


async def _remove_stale_pm_membership(db: AsyncSession, *, actor: User, project: Project, old_pm_id: UUID) -> None:
    """When a project gets a new PM, the outgoing one keeps their team
    membership unless we clean it up here — otherwise they silently keep
    seeing a project they no longer manage. Skipped if they still have an
    open task on it, so real work in progress doesn't just vanish from their
    view.
    """
    still_has_open_task = await db.scalar(
        select(Task.id).where(
            Task.project_id == project.id,
            Task.assignee_id == old_pm_id,
            Task.deleted_at.is_(None),
            Task.status != "done",
        ).limit(1)
    )
    if still_has_open_task is not None:
        return

    membership = await get_project_member(db, project.id, old_pm_id)
    if membership is None:
        return

    old_pm = await db.get(User, old_pm_id)
    await db.delete(membership)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="project",
        entity_id=project.id,
        diff={"member_removed": old_pm.name if old_pm else str(old_pm_id), "reason": "no longer project manager"},
    )


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
    if target.id != actor.id:
        await notify(
            db,
            org_id=actor.org_id,
            recipient=target,
            category="project_updates",
            type_="project.member_added",
            title="You were added to a project",
            message=f"{actor.name} added you to {project.name}",
            link=f"/projects/{project.id}",
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
    if project.project_manager_id == target.id:
        raise DomainError(
            "Reassign the project manager before removing them from the project.",
            code="bad_user_input",
        )

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


async def _get_org_contact(db: AsyncSession, contact_id: UUID, org_id: UUID) -> Contact:
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.deleted_at is not None or contact.org_id != org_id:
        raise NotFoundError("Contact not found")
    return contact


async def add_project_contact_record(
    db: AsyncSession, *, actor: User, project_id: UUID, contact_id: UUID
) -> Contact:
    project = await get_project_by_id(db, project_id)
    contact = await _get_org_contact(db, contact_id, actor.org_id)
    if contact.company_id != project.company_id:
        raise DomainError("This contact isn't at the project's client.", code="bad_user_input")

    existing = await get_project_contact(db, project.id, contact.id)
    if existing is not None:
        raise DomainError("This contact is already on the project.", code="bad_user_input")

    db.add(ProjectContact(org_id=actor.org_id, project_id=project.id, contact_id=contact.id))
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="project",
        entity_id=project.id,
        diff={"contact_added": f"{contact.first_name} {contact.last_name}"},
    )
    return contact


async def remove_project_contact_record(
    db: AsyncSession, *, actor: User, project_id: UUID, contact_id: UUID
) -> bool:
    project = await get_project_by_id(db, project_id)
    contact = await _get_org_contact(db, contact_id, actor.org_id)

    roster_entry = await get_project_contact(db, project.id, contact.id)
    if roster_entry is None:
        raise NotFoundError("This contact isn't on the project.")

    await db.delete(roster_entry)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="project",
        entity_id=project.id,
        diff={"contact_removed": f"{contact.first_name} {contact.last_name}"},
    )
    return True
