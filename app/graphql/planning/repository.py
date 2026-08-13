from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError, NotFoundError
from app.db.models.planning import Milestone, ProjectColumn, ProjectPhase, Task, TaskDependency
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember


async def list_phases_for_project(db: AsyncSession, project_id: UUID) -> list[ProjectPhase]:
    result = await db.execute(
        select(ProjectPhase)
        .where(ProjectPhase.project_id == project_id, ProjectPhase.deleted_at.is_(None))
        .order_by(ProjectPhase.order_index)
    )
    return list(result.scalars().all())


async def get_phases_by_project_ids(db: AsyncSession, project_ids: list[UUID]) -> list[ProjectPhase]:
    if not project_ids:
        return []
    result = await db.execute(
        select(ProjectPhase)
        .where(ProjectPhase.project_id.in_(project_ids), ProjectPhase.deleted_at.is_(None))
        .order_by(ProjectPhase.order_index)
    )
    return list(result.scalars().all())


async def get_phase(db: AsyncSession, phase_id: UUID) -> ProjectPhase | None:
    result = await db.execute(
        select(ProjectPhase).where(ProjectPhase.id == phase_id, ProjectPhase.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def list_milestones_for_phase(db: AsyncSession, phase_id: UUID) -> list[Milestone]:
    result = await db.execute(
        select(Milestone)
        .where(Milestone.phase_id == phase_id, Milestone.deleted_at.is_(None))
        .order_by(Milestone.order_index)
    )
    return list(result.scalars().all())


async def get_milestones_by_phase_ids(db: AsyncSession, phase_ids: list[UUID]) -> list[Milestone]:
    if not phase_ids:
        return []
    result = await db.execute(
        select(Milestone)
        .where(Milestone.phase_id.in_(phase_ids), Milestone.deleted_at.is_(None))
        .order_by(Milestone.order_index)
    )
    return list(result.scalars().all())


async def get_milestone(db: AsyncSession, milestone_id: UUID) -> Milestone | None:
    result = await db.execute(
        select(Milestone).where(Milestone.id == milestone_id, Milestone.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_tasks_by_project_ids(db: AsyncSession, project_ids: list[UUID]) -> list[Task]:
    if not project_ids:
        return []
    result = await db.execute(
        select(Task).where(Task.project_id.in_(project_ids), Task.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_tasks_by_phase_ids(db: AsyncSession, phase_ids: list[UUID]) -> list[Task]:
    if not phase_ids:
        return []
    result = await db.execute(
        select(Task).where(Task.phase_id.in_(phase_ids), Task.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_tasks_by_milestone_ids(db: AsyncSession, milestone_ids: list[UUID]) -> list[Task]:
    if not milestone_ids:
        return []
    result = await db.execute(
        select(Task).where(Task.milestone_id.in_(milestone_ids), Task.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_subtasks_by_parent_ids(db: AsyncSession, parent_ids: list[UUID]) -> list[Task]:
    if not parent_ids:
        return []
    result = await db.execute(
        select(Task).where(Task.parent_task_id.in_(parent_ids), Task.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_tasks_by_change_request_ids(db: AsyncSession, change_request_ids: list[UUID]) -> list[Task]:
    if not change_request_ids:
        return []
    result = await db.execute(
        select(Task).where(Task.change_request_id.in_(change_request_ids), Task.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_task(db: AsyncSession, task_id: UUID) -> Task | None:
    result = await db.execute(select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)))
    return result.scalar_one_or_none()


async def list_dependencies_for_project(db: AsyncSession, project_id: UUID) -> list[TaskDependency]:
    result = await db.execute(
        select(TaskDependency)
        .join(Task, TaskDependency.task_id == Task.id)
        .where(Task.project_id == project_id, Task.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_dependencies_by_task_ids(db: AsyncSession, task_ids: list[UUID]) -> list[TaskDependency]:
    if not task_ids:
        return []
    result = await db.execute(select(TaskDependency).where(TaskDependency.task_id.in_(task_ids)))
    return list(result.scalars().all())


async def soft_delete_entity(db: AsyncSession, entity) -> None:
    entity.deleted_at = datetime.now(UTC)
    await db.flush()


async def delete_dependencies_for_task(db: AsyncSession, task_id: UUID) -> None:
    """Dependency rows are just links, not real content — deleting the task
    they point to or from should clean them up rather than leave a dangling
    reference to a task that no longer exists.
    """
    result = await db.execute(
        select(TaskDependency).where(
            (TaskDependency.task_id == task_id) | (TaskDependency.depends_on_task_id == task_id)
        )
    )
    for row in result.scalars().all():
        await db.delete(row)
    await db.flush()


def _would_create_cycle(
    graph: dict[UUID, list[UUID]],
    task_id: UUID,
    depends_on_task_id: UUID,
) -> bool:
    visited: set[UUID] = set()

    def dfs(node: UUID) -> bool:
        if node == task_id:
            return True
        if node in visited:
            return False
        visited.add(node)
        for neighbor in graph.get(node, []):
            if dfs(neighbor):
                return True
        return False

    return dfs(depends_on_task_id)


async def validate_dependency_insert(
    db: AsyncSession,
    *,
    project_id: UUID,
    task_id: UUID,
    depends_on_task_id: UUID,
) -> None:
    if task_id == depends_on_task_id:
        raise DomainError("A task cannot depend on itself", code="dependency_cycle")

    task = await get_task(db, task_id)
    dep_task = await get_task(db, depends_on_task_id)
    if task is None or dep_task is None:
        raise NotFoundError("Task not found")
    if task.project_id != project_id or dep_task.project_id != project_id:
        raise DomainError("Tasks must belong to the same project", code="dependency_invalid")

    existing = await list_dependencies_for_project(db, project_id)
    graph: dict[UUID, list[UUID]] = defaultdict(list)
    for row in existing:
        graph[row.task_id].append(row.depends_on_task_id)
    graph[task_id].append(depends_on_task_id)

    if _would_create_cycle(graph, task_id, depends_on_task_id):
        raise DomainError("Dependency would create a cycle", code="dependency_cycle")


async def reorder_phase_indices(db: AsyncSession, project_id: UUID, ordered_ids: list[UUID]) -> list[ProjectPhase]:
    phases = await list_phases_for_project(db, project_id)
    current_ids = {phase.id for phase in phases}
    if set(ordered_ids) != current_ids or len(ordered_ids) != len(phases):
        raise DomainError("orderedPhaseIds must match the exact current phase set", code="reorder_invalid")

    phase_map = {phase.id: phase for phase in phases}
    for index, phase_id in enumerate(ordered_ids):
        phase_map[phase_id].order_index = index
    await db.flush()
    return [phase_map[pid] for pid in ordered_ids]


async def reorder_milestone_indices(db: AsyncSession, phase_id: UUID, ordered_ids: list[UUID]) -> list[Milestone]:
    milestones = await list_milestones_for_phase(db, phase_id)
    current_ids = {m.id for m in milestones}
    if set(ordered_ids) != current_ids or len(ordered_ids) != len(milestones):
        raise DomainError("orderedMilestoneIds must match the exact current milestone set", code="reorder_invalid")

    milestone_map = {m.id: m for m in milestones}
    for index, milestone_id in enumerate(ordered_ids):
        milestone_map[milestone_id].order_index = index
    await db.flush()
    return [milestone_map[mid] for mid in ordered_ids]


async def compute_workload(
    db: AsyncSession,
    *,
    project_id: UUID | None = None,
) -> list[dict]:
    # "Open" means not sitting in its own project's terminal column — a plain
    # per-project outer join rather than a literal status string, since
    # columns (and which one is terminal) are per-project configuration now.
    terminal_columns = select(ProjectColumn.project_id, ProjectColumn.code).where(
        ProjectColumn.is_terminal.is_(True)
    ).subquery()
    task_stmt = (
        select(
            Task.assignee_id,
            func.coalesce(func.sum(Task.estimated_hours), 0),
            func.coalesce(func.sum(Task.actual_hours), 0),
            func.count(Task.id),
        )
        .outerjoin(
            terminal_columns,
            and_(
                terminal_columns.c.project_id == Task.project_id,
                terminal_columns.c.code == Task.status,
            ),
        )
        .where(
            Task.deleted_at.is_(None),
            Task.assignee_id.is_not(None),
            terminal_columns.c.code.is_(None),
        )
        .group_by(Task.assignee_id)
    )
    if project_id:
        task_stmt = task_stmt.where(Task.project_id == project_id)
    task_result = await db.execute(task_stmt)
    task_stats = {
        assignee_id: {
            "total_estimated_hours": float(est or 0),
            "total_actual_hours": float(act or 0),
            "open_task_count": int(count or 0),
        }
        for assignee_id, est, act, count in task_result.all()
    }

    # Project/client counts come from membership, not tasks, so someone on a
    # project with no open tasks yet still shows up with a real project count
    # instead of being absent from the roster entirely.
    member_stmt = select(ProjectMember.user_id, ProjectMember.project_id, Project.company_id).join(
        Project, Project.id == ProjectMember.project_id
    ).where(Project.deleted_at.is_(None))
    if project_id:
        member_stmt = member_stmt.where(ProjectMember.project_id == project_id)
    member_result = await db.execute(member_stmt)
    projects_by_user: dict[UUID, set[UUID]] = defaultdict(set)
    companies_by_user: dict[UUID, set[UUID]] = defaultdict(set)
    for user_id, member_project_id, company_id in member_result.all():
        projects_by_user[user_id].add(member_project_id)
        companies_by_user[user_id].add(company_id)

    all_user_ids = set(task_stats) | set(projects_by_user)
    rows = []
    for user_id in all_user_ids:
        stats = task_stats.get(
            user_id, {"total_estimated_hours": 0.0, "total_actual_hours": 0.0, "open_task_count": 0}
        )
        user_project_ids = projects_by_user.get(user_id, set())
        user_company_ids = companies_by_user.get(user_id, set())
        rows.append(
            {
                "assignee_id": user_id,
                **stats,
                "project_count": len(user_project_ids),
                "client_count": len(user_company_ids),
                "project_ids": list(user_project_ids),
                "client_ids": list(user_company_ids),
            }
        )
    return rows
