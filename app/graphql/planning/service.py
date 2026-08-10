from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import AuthorizationError, DomainError, NotFoundError
from app.db.enums import UserRole
from app.db.models.change_request import ChangeRequest
from app.db.models.planning import Milestone, ProjectPhase, Task, TaskDependency
from app.db.models.project import Project
from app.db.models.user import User
from app.graphql.notifications.service import notify
from app.graphql.planning.repository import (
    compute_workload,
    get_milestone,
    get_phase,
    get_task,
    list_milestones_for_phase,
    list_phases_for_project,
    reorder_milestone_indices,
    reorder_phase_indices,
    soft_delete_entity,
    validate_dependency_insert,
)
from app.graphql.projects.repository import ensure_project_member
from app.graphql.projects.service import actor_can_access_project, actor_can_mutate_project


def _phase_dict(phase: ProjectPhase) -> dict:
    return {
        "id": str(phase.id),
        "name": phase.name,
        "status": phase.status,
        "order_index": phase.order_index,
        "start_date": phase.start_date.isoformat() if phase.start_date else None,
        "due_date": phase.due_date.isoformat() if phase.due_date else None,
    }


def _milestone_dict(milestone: Milestone) -> dict:
    return {
        "id": str(milestone.id),
        "title": milestone.title,
        "status": milestone.status,
        "due_date": milestone.due_date.isoformat() if milestone.due_date else None,
        "requires_client_approval": milestone.requires_client_approval,
    }


def _task_dict(task: Task) -> dict:
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "assignee_id": str(task.assignee_id) if task.assignee_id else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
        "actual_hours": float(task.actual_hours) if task.actual_hours is not None else None,
    }


async def _notify_task_assignee(db: AsyncSession, *, actor: User, task: Task) -> None:
    if task.assignee_id is None:
        return

    # Being assigned a task puts you on the project, whether or not you get
    # notified about it — that's a preference, this is just accurate roster.
    await ensure_project_member(db, org_id=actor.org_id, project_id=task.project_id, user_id=task.assignee_id)

    if task.assignee_id == actor.id:
        return
    assignee = await db.get(User, task.assignee_id)
    if assignee is None or assignee.deleted_at is not None:
        return
    project = await db.get(Project, task.project_id)
    await notify(
        db,
        org_id=actor.org_id,
        recipient=assignee,
        category="task_assignments",
        type_="task.assigned",
        title="You were assigned a task",
        message=f'{actor.name} assigned you "{task.title}"' + (f" on {project.name}" if project else ""),
        link=f"/projects/{task.project_id}/board",
    )


async def create_phase_record(
    db: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    name: str,
    order_index: int,
    start_date=None,
    due_date=None,
    status: str = "not_started",
) -> ProjectPhase:
    if not await actor_can_mutate_project(db, actor, project_id):
        raise AuthorizationError("You're not assigned to this project.")
    phase = ProjectPhase(
        org_id=actor.org_id,
        project_id=project_id,
        name=name,
        order_index=order_index,
        start_date=start_date,
        due_date=due_date,
        status=status,
    )
    db.add(phase)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="project_phase",
        entity_id=phase.id,
        diff={"after": _phase_dict(phase)},
    )
    return phase


async def update_phase_record(db: AsyncSession, *, actor: User, phase_id: UUID, updates: dict) -> ProjectPhase:
    phase = await get_phase(db, phase_id)
    if phase is None:
        raise NotFoundError("Phase not found")
    if not await actor_can_mutate_project(db, actor, phase.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    before = _phase_dict(phase)
    for key, value in updates.items():
        if value is not None and hasattr(phase, key):
            setattr(phase, key, value)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="project_phase",
        entity_id=phase.id,
        diff={"before": before, "after": _phase_dict(phase)},
    )
    return phase


async def delete_phase_record(db: AsyncSession, *, actor: User, phase_id: UUID) -> ProjectPhase:
    phase = await get_phase(db, phase_id)
    if phase is None:
        raise NotFoundError("Phase not found")
    if not await actor_can_mutate_project(db, actor, phase.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    before = _phase_dict(phase)
    await soft_delete_entity(db, phase)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="delete",
        entity_type="project_phase",
        entity_id=phase.id,
        diff={"before": before},
    )
    return phase


async def create_milestone_record(
    db: AsyncSession,
    *,
    actor: User,
    phase_id: UUID,
    title: str,
    order_index: int,
    description: str | None = None,
    due_date=None,
    status: str = "not_started",
    requires_client_approval: bool = False,
) -> Milestone:
    phase = await get_phase(db, phase_id)
    if phase is None:
        raise NotFoundError("Phase not found")
    if not await actor_can_mutate_project(db, actor, phase.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    milestone = Milestone(
        org_id=actor.org_id,
        phase_id=phase_id,
        title=title,
        order_index=order_index,
        description=description,
        due_date=due_date,
        status=status,
        requires_client_approval=requires_client_approval,
    )
    db.add(milestone)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="milestone",
        entity_id=milestone.id,
        diff={"after": _milestone_dict(milestone)},
    )
    return milestone


async def update_milestone_record(
    db: AsyncSession,
    *,
    actor: User,
    milestone_id: UUID,
    updates: dict,
) -> Milestone:
    milestone = await get_milestone(db, milestone_id)
    if milestone is None:
        raise NotFoundError("Milestone not found")
    phase = await get_phase(db, milestone.phase_id)
    if phase is not None and not await actor_can_mutate_project(db, actor, phase.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    before = _milestone_dict(milestone)
    for key, value in updates.items():
        if value is not None and hasattr(milestone, key):
            setattr(milestone, key, value)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="milestone",
        entity_id=milestone.id,
        diff={"before": before, "after": _milestone_dict(milestone)},
    )
    return milestone


async def delete_milestone_record(db: AsyncSession, *, actor: User, milestone_id: UUID) -> Milestone:
    milestone = await get_milestone(db, milestone_id)
    if milestone is None:
        raise NotFoundError("Milestone not found")
    phase = await get_phase(db, milestone.phase_id)
    if phase is not None and not await actor_can_mutate_project(db, actor, phase.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    before = _milestone_dict(milestone)
    await soft_delete_entity(db, milestone)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="delete",
        entity_type="milestone",
        entity_id=milestone.id,
        diff={"before": before},
    )
    return milestone


async def create_task_record(
    db: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    phase_id: UUID,
    title: str,
    milestone_id: UUID | None = None,
    parent_task_id: UUID | None = None,
    change_request_id: UUID | None = None,
    description: str | None = None,
    assignee_id: UUID | None = None,
    status: str = "todo",
    priority: str = "medium",
    start_date=None,
    due_date=None,
    estimated_hours: float | None = None,
    actual_hours: float | None = None,
) -> Task:
    if not await actor_can_mutate_project(db, actor, project_id):
        raise AuthorizationError("You're not assigned to this project.")
    if change_request_id is not None:
        cr = await db.get(ChangeRequest, change_request_id)
        if cr is None or cr.project_id != project_id:
            raise DomainError(
                "That change request isn't on this project.", code="bad_user_input"
            )

    task = Task(
        org_id=actor.org_id,
        project_id=project_id,
        phase_id=phase_id,
        milestone_id=milestone_id,
        parent_task_id=parent_task_id,
        change_request_id=change_request_id,
        title=title,
        description=description,
        assignee_id=assignee_id,
        status=status,
        priority=priority,
        start_date=start_date,
        due_date=due_date,
        estimated_hours=estimated_hours,
        actual_hours=actual_hours,
    )
    db.add(task)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="task",
        entity_id=task.id,
        diff={"after": _task_dict(task)},
    )
    await _notify_task_assignee(db, actor=actor, task=task)
    return task


TEAM_MEMBER_EDITABLE_TASK_FIELDS = {"status"}


def _normalize_task_updates(updates: dict) -> dict:
    normalized = dict(updates)
    if normalized.get("status") is not None:
        normalized["status"] = str(normalized["status"]).lower()
    if normalized.get("priority") is not None:
        normalized["priority"] = str(normalized["priority"]).lower()
    return normalized


async def update_task_record(db: AsyncSession, *, actor: User, task_id: UUID, updates: dict) -> Task:
    task = await get_task(db, task_id)
    if task is None:
        raise NotFoundError("Task not found")
    if actor.role == UserRole.TEAM_MEMBER.value:
        if not await actor_can_access_project(db, actor, task.project_id):
            raise AuthorizationError("You don't have access to this project.")
        if task.assignee_id != actor.id:
            raise AuthorizationError("You can only update tasks assigned to you.")
        disallowed = {
            key
            for key, value in updates.items()
            if value is not None and key not in TEAM_MEMBER_EDITABLE_TASK_FIELDS
        }
        if disallowed:
            raise AuthorizationError("You can only update the status of your own tasks.")
    elif actor.role == UserRole.PROJECT_MANAGER.value:
        # Unlike team_member, a PM who passes this gets the full field set —
        # they're just restricted to projects they're actually assigned to.
        if not await actor_can_mutate_project(db, actor, task.project_id):
            raise AuthorizationError("You're not assigned to this project.")
    before = _task_dict(task)
    prev_assignee_id = task.assignee_id
    normalized = _normalize_task_updates(updates)
    for key, value in normalized.items():
        if value is not None and hasattr(task, key):
            setattr(task, key, value)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="task",
        entity_id=task.id,
        diff={"before": before, "after": _task_dict(task)},
    )
    if task.assignee_id != prev_assignee_id:
        await _notify_task_assignee(db, actor=actor, task=task)
    return task


async def delete_task_record(db: AsyncSession, *, actor: User, task_id: UUID) -> Task:
    task = await get_task(db, task_id)
    if task is None:
        raise NotFoundError("Task not found")
    if not await actor_can_mutate_project(db, actor, task.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    before = _task_dict(task)
    await soft_delete_entity(db, task)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="delete",
        entity_type="task",
        entity_id=task.id,
        diff={"before": before},
    )
    return task


async def add_task_dependency_record(
    db: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    task_id: UUID,
    depends_on_task_id: UUID,
    dep_type: str = "finish_to_start",
) -> TaskDependency:
    if not await actor_can_mutate_project(db, actor, project_id):
        raise AuthorizationError("You're not assigned to this project.")
    await validate_dependency_insert(
        db,
        project_id=project_id,
        task_id=task_id,
        depends_on_task_id=depends_on_task_id,
    )
    row = TaskDependency(
        org_id=actor.org_id,
        task_id=task_id,
        depends_on_task_id=depends_on_task_id,
        type=dep_type,
    )
    db.add(row)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="task_dependency",
        entity_id=row.id,
        diff={"after": {"task_id": str(task_id), "depends_on_task_id": str(depends_on_task_id)}},
    )
    return row


async def remove_task_dependency_record(db: AsyncSession, *, actor: User, dependency_id: UUID) -> None:
    row = await db.get(TaskDependency, dependency_id)
    if row is None:
        raise NotFoundError("Dependency not found")
    task = await get_task(db, row.task_id)
    if task is not None and not await actor_can_mutate_project(db, actor, task.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    await db.delete(row)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="delete",
        entity_type="task_dependency",
        entity_id=dependency_id,
        diff={"before": {"task_id": str(row.task_id), "depends_on_task_id": str(row.depends_on_task_id)}},
    )


async def reorder_phases(db: AsyncSession, *, actor: User, project_id: UUID, ordered_ids: list[UUID]) -> list[ProjectPhase]:
    if not await actor_can_mutate_project(db, actor, project_id):
        raise AuthorizationError("You're not assigned to this project.")
    phases = await reorder_phase_indices(db, project_id, ordered_ids)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="reorder",
        entity_type="project",
        entity_id=project_id,
        diff={"ordered_phase_ids": [str(i) for i in ordered_ids]},
    )
    return phases


async def reorder_milestones(
    db: AsyncSession,
    *,
    actor: User,
    phase_id: UUID,
    ordered_ids: list[UUID],
) -> list[Milestone]:
    phase = await get_phase(db, phase_id)
    if phase is not None and not await actor_can_mutate_project(db, actor, phase.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    milestones = await reorder_milestone_indices(db, phase_id, ordered_ids)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="reorder",
        entity_type="project_phase",
        entity_id=phase_id,
        diff={"ordered_milestone_ids": [str(i) for i in ordered_ids]},
    )
    return milestones


async def get_workload_rows(db: AsyncSession, project_id: UUID | None = None) -> list[dict]:
    return await compute_workload(db, project_id=project_id)
