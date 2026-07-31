from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import require_authenticated
from app.core.exceptions import DomainError, NotFoundError
from app.graphql.loaders import get_phases_by_project_loader, get_tasks_by_project_loader
from app.graphql.planning.schema import PhaseType, TaskType
from app.graphql.projects.service import (
    create_project_record,
    delete_project_record,
    get_project_by_id,
    get_projects,
    update_project_record,
)


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, NotFoundError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class ProjectType:
    id: strawberry.ID
    company_id: strawberry.ID
    name: str
    description: str | None
    status: str
    priority: str | None
    project_manager_id: strawberry.ID | None
    budget: float | None
    actual_cost: float | None
    health: str | None

    @classmethod
    def from_model(cls, project) -> "ProjectType":
        return cls(
            id=strawberry.ID(str(project.id)),
            company_id=strawberry.ID(str(project.company_id)),
            name=project.name,
            description=project.description,
            status=project.status,
            priority=project.priority,
            project_manager_id=strawberry.ID(str(project.project_manager_id))
            if project.project_manager_id
            else None,
            budget=float(project.budget) if project.budget is not None else None,
            actual_cost=float(project.actual_cost) if project.actual_cost is not None else None,
            health=project.health,
        )

    @strawberry.field
    async def phases(self, info: Info) -> list[PhaseType]:
        loader = get_phases_by_project_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [PhaseType.from_model(row) for row in rows]

    @strawberry.field
    async def tasks(self, info: Info) -> list[TaskType]:
        loader = get_tasks_by_project_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [TaskType.from_model(row) for row in rows]


@strawberry.type
class ProjectQuery:
    @strawberry.field
    async def projects(self, info: Info, company_id: strawberry.ID | None = None) -> list[ProjectType]:
        ctx = require_authenticated(info.context)
        cid = UUID(str(company_id)) if company_id else None
        rows = await get_projects(ctx.db, company_id=cid)
        return [ProjectType.from_model(row) for row in rows]

    @strawberry.field
    async def project(self, info: Info, id: strawberry.ID) -> ProjectType | None:
        ctx = require_authenticated(info.context)
        try:
            row = await get_project_by_id(ctx.db, UUID(str(id)))
        except NotFoundError:
            return None
        return ProjectType.from_model(row)


@strawberry.type
class ProjectMutation:
    @strawberry.mutation
    async def create_project(
        self,
        info: Info,
        company_id: strawberry.ID,
        name: str,
        description: str | None = None,
        status: str = "planning",
        priority: str | None = None,
        project_manager_id: strawberry.ID | None = None,
        budget: float | None = None,
        health: str | None = "on_track",
    ) -> ProjectType:
        ctx = require_authenticated(info.context)
        try:
            row = await create_project_record(
                ctx.db,
                actor=ctx.user,
                company_id=UUID(str(company_id)),
                name=name,
                description=description,
                status=status,
                priority=priority,
                project_manager_id=UUID(str(project_manager_id)) if project_manager_id else None,
                budget=budget,
                health=health,
            )
            return ProjectType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def update_project(
        self,
        info: Info,
        id: strawberry.ID,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        budget: float | None = None,
        health: str | None = None,
    ) -> ProjectType:
        ctx = require_authenticated(info.context)
        try:
            row = await update_project_record(
                ctx.db,
                actor=ctx.user,
                project_id=UUID(str(id)),
                updates={
                    "name": name,
                    "description": description,
                    "status": status,
                    "priority": priority,
                    "budget": budget,
                    "health": health,
                },
            )
            return ProjectType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def delete_project(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_authenticated(info.context)
        try:
            await delete_project_record(ctx.db, actor=ctx.user, project_id=UUID(str(id)))
            return True
        except Exception as exc:
            _gql_error(exc)
