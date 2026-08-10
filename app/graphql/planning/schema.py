from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import require_authenticated, require_role
from app.core.exceptions import DomainError, NotFoundError
from app.graphql.loaders import (
    get_dependencies_by_task_loader,
    get_milestones_by_phase_loader,
    get_subtasks_by_parent_loader,
    get_tasks_by_milestone_loader,
    get_tasks_by_phase_loader,
)
from app.graphql.planning.repository import get_phase, list_milestones_for_phase, list_phases_for_project
from app.graphql.projects.service import actor_can_access_project
from app.graphql.users.schema import UserSummaryType
from app.graphql.planning.service import (
    add_task_dependency_record,
    create_milestone_record,
    create_phase_record,
    create_task_record,
    delete_milestone_record,
    delete_phase_record,
    delete_task_record,
    get_workload_rows,
    remove_task_dependency_record,
    reorder_milestones,
    reorder_phases,
    update_milestone_record,
    update_phase_record,
    update_task_record,
)


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, NotFoundError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class TaskDependencyType:
    id: strawberry.ID
    task_id: strawberry.ID
    depends_on_task_id: strawberry.ID
    type: str

    @classmethod
    def from_model(cls, row) -> "TaskDependencyType":
        return cls(
            id=strawberry.ID(str(row.id)),
            task_id=strawberry.ID(str(row.task_id)),
            depends_on_task_id=strawberry.ID(str(row.depends_on_task_id)),
            type=row.type,
        )


@strawberry.type
class TaskType:
    id: strawberry.ID
    project_id: strawberry.ID
    phase_id: strawberry.ID
    milestone_id: strawberry.ID | None
    parent_task_id: strawberry.ID | None
    change_request_id: strawberry.ID | None
    title: str
    description: str | None
    assignee_id: strawberry.ID | None
    status: str
    priority: str
    estimated_hours: float | None
    actual_hours: float | None
    start_date: date | None
    due_date: date | None

    @classmethod
    def from_model(cls, task) -> "TaskType":
        return cls(
            id=strawberry.ID(str(task.id)),
            project_id=strawberry.ID(str(task.project_id)),
            phase_id=strawberry.ID(str(task.phase_id)),
            milestone_id=strawberry.ID(str(task.milestone_id)) if task.milestone_id else None,
            parent_task_id=strawberry.ID(str(task.parent_task_id)) if task.parent_task_id else None,
            change_request_id=strawberry.ID(str(task.change_request_id)) if task.change_request_id else None,
            title=task.title,
            description=task.description,
            assignee_id=strawberry.ID(str(task.assignee_id)) if task.assignee_id else None,
            status=task.status,
            priority=task.priority,
            estimated_hours=float(task.estimated_hours) if task.estimated_hours is not None else None,
            actual_hours=float(task.actual_hours) if task.actual_hours is not None else None,
            start_date=task.start_date,
            due_date=task.due_date,
        )

    @strawberry.field
    async def assignee(self, info: Info) -> UserSummaryType | None:
        from app.db.models.user import User

        if self.assignee_id is None or info.context.db is None:
            return None
        user = await info.context.db.get(User, UUID(str(self.assignee_id)))
        if user is None or user.deleted_at is not None:
            return None
        return UserSummaryType.from_model(user)

    @strawberry.field
    async def subtasks(self, info: Info) -> list[TaskType]:
        loader = get_subtasks_by_parent_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [TaskType.from_model(row) for row in rows]

    @strawberry.field
    async def dependencies(self, info: Info) -> list[TaskDependencyType]:
        loader = get_dependencies_by_task_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [TaskDependencyType.from_model(row) for row in rows]


@strawberry.type
class MilestoneApprovalType:
    id: strawberry.ID
    approver_type: str
    status: str
    comment: str | None
    decided_at: datetime | None
    approver_name: str | None

    @classmethod
    def from_model(cls, approval) -> MilestoneApprovalType:
        return cls(
            id=strawberry.ID(str(approval.id)),
            approver_type=approval.approver_type.upper(),
            status=approval.status.upper(),
            comment=approval.comment,
            decided_at=approval.decided_at,
            approver_name="Client contact" if approval.approver_type == "client" else "Delivery team",
        )


@strawberry.type
class MilestoneType:
    id: strawberry.ID
    phase_id: strawberry.ID
    title: str
    description: str | None
    status: str
    order_index: int
    requires_client_approval: bool
    due_date: date | None
    approved_at: datetime | None

    @classmethod
    def from_model(cls, milestone) -> "MilestoneType":
        return cls(
            id=strawberry.ID(str(milestone.id)),
            phase_id=strawberry.ID(str(milestone.phase_id)),
            title=milestone.title,
            description=milestone.description,
            status=milestone.status,
            order_index=milestone.order_index,
            requires_client_approval=milestone.requires_client_approval,
            due_date=milestone.due_date,
            approved_at=milestone.approved_at,
        )

    @strawberry.field
    async def tasks(self, info: Info) -> list[TaskType]:
        loader = get_tasks_by_milestone_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [TaskType.from_model(row) for row in rows]

    @strawberry.field
    async def approvals(self, info: Info) -> list[MilestoneApprovalType]:
        from app.graphql.approvals.repository import list_approvals_for_milestone

        rows = await list_approvals_for_milestone(info.context.db, UUID(str(self.id)))
        return [MilestoneApprovalType.from_model(row) for row in rows]


@strawberry.type
class PhaseType:
    id: strawberry.ID
    project_id: strawberry.ID
    name: str
    order_index: int
    status: str
    start_date: date | None
    due_date: date | None

    @classmethod
    def from_model(cls, phase) -> "PhaseType":
        return cls(
            id=strawberry.ID(str(phase.id)),
            project_id=strawberry.ID(str(phase.project_id)),
            name=phase.name,
            order_index=phase.order_index,
            status=phase.status,
            start_date=phase.start_date,
            due_date=phase.due_date,
        )

    @strawberry.field
    async def milestones(self, info: Info) -> list[MilestoneType]:
        loader = get_milestones_by_phase_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [MilestoneType.from_model(row) for row in rows]

    @strawberry.field
    async def tasks(self, info: Info) -> list[TaskType]:
        loader = get_tasks_by_phase_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [TaskType.from_model(row) for row in rows]


@strawberry.type
class WorkloadType:
    assignee_id: strawberry.ID
    total_estimated_hours: float
    total_actual_hours: float
    open_task_count: int


@strawberry.type
class PlanningQuery:
    @strawberry.field
    async def phases(self, info: Info, project_id: strawberry.ID) -> list[PhaseType]:
        ctx = require_authenticated(info.context)
        pid = UUID(str(project_id))
        if not await actor_can_access_project(ctx.db, ctx.user, pid):
            return []
        rows = await list_phases_for_project(ctx.db, pid)
        return [PhaseType.from_model(row) for row in rows]

    @strawberry.field
    async def milestones(self, info: Info, phase_id: strawberry.ID) -> list[MilestoneType]:
        ctx = require_authenticated(info.context)
        phase_uuid = UUID(str(phase_id))
        phase = await get_phase(ctx.db, phase_uuid)
        if phase is not None and not await actor_can_access_project(ctx.db, ctx.user, phase.project_id):
            return []
        rows = await list_milestones_for_phase(ctx.db, phase_uuid)
        return [MilestoneType.from_model(row) for row in rows]

    @strawberry.field
    async def workload(self, info: Info, project_id: strawberry.ID | None = None) -> list[WorkloadType]:
        ctx = require_role(info.context, "admin", "project_manager")
        pid = UUID(str(project_id)) if project_id else None
        rows = await get_workload_rows(ctx.db, project_id=pid)
        return [
            WorkloadType(
                assignee_id=strawberry.ID(str(row["assignee_id"])),
                total_estimated_hours=row["total_estimated_hours"],
                total_actual_hours=row["total_actual_hours"],
                open_task_count=row["open_task_count"],
            )
            for row in rows
        ]


@strawberry.type
class PlanningMutation:
    @strawberry.mutation
    async def create_phase(
        self,
        info: Info,
        project_id: strawberry.ID,
        name: str,
        order_index: int,
        status: str = "not_started",
        start_date: date | None = None,
        due_date: date | None = None,
    ) -> PhaseType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await create_phase_record(
                ctx.db,
                actor=ctx.user,
                project_id=UUID(str(project_id)),
                name=name,
                order_index=order_index,
                status=status,
                start_date=start_date,
                due_date=due_date,
            )
            return PhaseType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def update_phase(
        self,
        info: Info,
        id: strawberry.ID,
        name: str | None = None,
        order_index: int | None = None,
        status: str | None = None,
        start_date: date | None = None,
        due_date: date | None = None,
    ) -> PhaseType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await update_phase_record(
                ctx.db,
                actor=ctx.user,
                phase_id=UUID(str(id)),
                updates={
                    "name": name,
                    "order_index": order_index,
                    "status": status,
                    "start_date": start_date,
                    "due_date": due_date,
                },
            )
            return PhaseType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def delete_phase(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            await delete_phase_record(ctx.db, actor=ctx.user, phase_id=UUID(str(id)))
            return True
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def reorder_phases(self, info: Info, project_id: strawberry.ID, ordered_phase_ids: list[strawberry.ID]) -> list[PhaseType]:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            rows = await reorder_phases(
                ctx.db,
                actor=ctx.user,
                project_id=UUID(str(project_id)),
                ordered_ids=[UUID(str(i)) for i in ordered_phase_ids],
            )
            return [PhaseType.from_model(row) for row in rows]
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def create_milestone(
        self,
        info: Info,
        phase_id: strawberry.ID,
        title: str,
        order_index: int,
        status: str = "not_started",
        description: str | None = None,
        due_date: date | None = None,
        requires_client_approval: bool = False,
    ) -> MilestoneType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await create_milestone_record(
                ctx.db,
                actor=ctx.user,
                phase_id=UUID(str(phase_id)),
                title=title,
                order_index=order_index,
                status=status,
                description=description,
                due_date=due_date,
                requires_client_approval=requires_client_approval,
            )
            return MilestoneType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def update_milestone(
        self,
        info: Info,
        id: strawberry.ID,
        title: str | None = None,
        order_index: int | None = None,
        status: str | None = None,
        description: str | None = None,
        due_date: date | None = None,
        requires_client_approval: bool | None = None,
    ) -> MilestoneType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await update_milestone_record(
                ctx.db,
                actor=ctx.user,
                milestone_id=UUID(str(id)),
                updates={
                    "title": title,
                    "order_index": order_index,
                    "status": status,
                    "description": description,
                    "due_date": due_date,
                    "requires_client_approval": requires_client_approval,
                },
            )
            return MilestoneType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def delete_milestone(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            await delete_milestone_record(ctx.db, actor=ctx.user, milestone_id=UUID(str(id)))
            return True
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def reorder_milestones(
        self,
        info: Info,
        phase_id: strawberry.ID,
        ordered_milestone_ids: list[strawberry.ID],
    ) -> list[MilestoneType]:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            rows = await reorder_milestones(
                ctx.db,
                actor=ctx.user,
                phase_id=UUID(str(phase_id)),
                ordered_ids=[UUID(str(i)) for i in ordered_milestone_ids],
            )
            return [MilestoneType.from_model(row) for row in rows]
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def create_task(
        self,
        info: Info,
        project_id: strawberry.ID,
        phase_id: strawberry.ID,
        title: str,
        milestone_id: strawberry.ID | None = None,
        parent_task_id: strawberry.ID | None = None,
        change_request_id: strawberry.ID | None = None,
        description: str | None = None,
        assignee_id: strawberry.ID | None = None,
        status: str = "todo",
        priority: str = "medium",
        start_date: date | None = None,
        due_date: date | None = None,
        estimated_hours: float | None = None,
    ) -> TaskType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await create_task_record(
                ctx.db,
                actor=ctx.user,
                project_id=UUID(str(project_id)),
                phase_id=UUID(str(phase_id)),
                title=title,
                milestone_id=UUID(str(milestone_id)) if milestone_id else None,
                parent_task_id=UUID(str(parent_task_id)) if parent_task_id else None,
                change_request_id=UUID(str(change_request_id)) if change_request_id else None,
                description=description,
                assignee_id=UUID(str(assignee_id)) if assignee_id else None,
                status=status,
                priority=priority,
                start_date=start_date,
                due_date=due_date,
                estimated_hours=estimated_hours,
            )
            return TaskType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def update_task(
        self,
        info: Info,
        id: strawberry.ID,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        phase_id: strawberry.ID | None = None,
        milestone_id: strawberry.ID | None = None,
        parent_task_id: strawberry.ID | None = None,
        assignee_id: strawberry.ID | None = None,
        start_date: date | None = None,
        due_date: date | None = None,
        estimated_hours: float | None = None,
        actual_hours: float | None = None,
    ) -> TaskType:
        ctx = require_authenticated(info.context)
        try:
            row = await update_task_record(
                ctx.db,
                actor=ctx.user,
                task_id=UUID(str(id)),
                updates={
                    "title": title,
                    "description": description,
                    "status": status,
                    "priority": priority,
                    "phase_id": UUID(str(phase_id)) if phase_id else None,
                    "milestone_id": UUID(str(milestone_id)) if milestone_id else None,
                    "parent_task_id": UUID(str(parent_task_id)) if parent_task_id else None,
                    "assignee_id": UUID(str(assignee_id)) if assignee_id else None,
                    "start_date": start_date,
                    "due_date": due_date,
                    "estimated_hours": estimated_hours,
                    "actual_hours": actual_hours,
                },
            )
            return TaskType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def delete_task(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            await delete_task_record(ctx.db, actor=ctx.user, task_id=UUID(str(id)))
            return True
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def add_task_dependency(
        self,
        info: Info,
        project_id: strawberry.ID,
        task_id: strawberry.ID,
        depends_on_task_id: strawberry.ID,
        type: str = "finish_to_start",
    ) -> TaskDependencyType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            row = await add_task_dependency_record(
                ctx.db,
                actor=ctx.user,
                project_id=UUID(str(project_id)),
                task_id=UUID(str(task_id)),
                depends_on_task_id=UUID(str(depends_on_task_id)),
                dep_type=type,
            )
            return TaskDependencyType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def remove_task_dependency(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            await remove_task_dependency_record(ctx.db, actor=ctx.user, dependency_id=UUID(str(id)))
            return True
        except Exception as exc:
            _gql_error(exc)
