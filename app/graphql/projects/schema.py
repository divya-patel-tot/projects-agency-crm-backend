from datetime import date
from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import require_authenticated, require_role
from app.core.exceptions import DomainError, NotFoundError
from app.graphql.companies.schema import CompanyType, company_from_model
from app.graphql.companies.service import get_company_by_id
from app.graphql.contacts.schema import ContactType
from app.graphql.loaders import (
    get_contacts_by_project_loader,
    get_members_by_project_loader,
    get_phases_by_project_loader,
    get_tags_by_project_loader,
    get_tasks_by_project_loader,
)
from app.graphql.planning.schema import PhaseType, TaskType
from app.graphql.projects.service import (
    add_project_contact_record,
    add_project_member_record,
    create_project_record,
    delete_project_record,
    get_project_by_id,
    get_projects,
    remove_project_contact_record,
    remove_project_member_record,
    update_project_record,
)
from app.graphql.tags.schema import TagType
from app.graphql.users.schema import UserSummaryType


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
    currency: str
    health: str | None
    start_date: date | None
    end_date: date | None

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
            currency=project.currency,
            health=project.health,
            start_date=project.start_date,
            end_date=project.end_date,
        )

    @strawberry.field
    async def company(self, info: Info) -> CompanyType | None:
        if info.context.db is None:
            return None
        ctx = require_authenticated(info.context)
        try:
            row = await get_company_by_id(ctx.db, UUID(str(self.company_id)), actor=ctx.user)
        except NotFoundError:
            return None
        return company_from_model(row)

    @strawberry.field
    async def project_manager(self, info: Info) -> UserSummaryType | None:
        from app.db.models.user import User

        if self.project_manager_id is None or info.context.db is None:
            return None
        user = await info.context.db.get(User, UUID(str(self.project_manager_id)))
        if user is None or user.deleted_at is not None:
            return None
        return UserSummaryType.from_model(user)

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

    @strawberry.field
    async def members(self, info: Info) -> list[UserSummaryType]:
        loader = get_members_by_project_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [UserSummaryType.from_model(row) for row in rows]

    @strawberry.field
    async def client_contacts(self, info: Info) -> list[ContactType]:
        loader = get_contacts_by_project_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [ContactType.from_model(row) for row in rows]

    @strawberry.field
    async def tags(self, info: Info) -> list[TagType]:
        loader = get_tags_by_project_loader(info.context)
        rows = await loader.load(UUID(str(self.id)))
        return [TagType(id=strawberry.ID(str(row.id)), name=row.name) for row in rows]


@strawberry.type
class ProjectQuery:
    @strawberry.field
    async def projects(self, info: Info, company_id: strawberry.ID | None = None) -> list[ProjectType]:
        ctx = require_authenticated(info.context)
        cid = UUID(str(company_id)) if company_id else None
        rows = await get_projects(ctx.db, company_id=cid, actor=ctx.user)
        return [ProjectType.from_model(row) for row in rows]

    @strawberry.field
    async def project(self, info: Info, id: strawberry.ID) -> ProjectType | None:
        ctx = require_authenticated(info.context)
        try:
            row = await get_project_by_id(ctx.db, UUID(str(id)), actor=ctx.user)
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
        start_date: date | None = None,
        end_date: date | None = None,
        budget: float | None = None,
        currency: str = "GBP",
        health: str | None = "on_track",
    ) -> ProjectType:
        ctx = require_role(info.context, "admin", "project_manager")
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
                start_date=start_date,
                end_date=end_date,
                budget=budget,
                currency=currency,
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
        project_manager_id: strawberry.ID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        budget: float | None = None,
        currency: str | None = None,
        health: str | None = None,
    ) -> ProjectType:
        ctx = require_role(info.context, "admin", "project_manager")
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
                    "project_manager_id": UUID(str(project_manager_id)) if project_manager_id else None,
                    "start_date": start_date,
                    "end_date": end_date,
                    "budget": budget,
                    "currency": currency,
                    "health": health,
                },
            )
            return ProjectType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def delete_project(self, info: Info, id: strawberry.ID) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            await delete_project_record(ctx.db, actor=ctx.user, project_id=UUID(str(id)))
            return True
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def add_project_member(
        self, info: Info, project_id: strawberry.ID, user_id: strawberry.ID
    ) -> UserSummaryType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            user = await add_project_member_record(
                ctx.db, actor=ctx.user, project_id=UUID(str(project_id)), user_id=UUID(str(user_id))
            )
            return UserSummaryType.from_model(user)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def remove_project_member(
        self, info: Info, project_id: strawberry.ID, user_id: strawberry.ID
    ) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            return await remove_project_member_record(
                ctx.db, actor=ctx.user, project_id=UUID(str(project_id)), user_id=UUID(str(user_id))
            )
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def add_project_contact(
        self, info: Info, project_id: strawberry.ID, contact_id: strawberry.ID
    ) -> ContactType:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            contact = await add_project_contact_record(
                ctx.db, actor=ctx.user, project_id=UUID(str(project_id)), contact_id=UUID(str(contact_id))
            )
            return ContactType.from_model(contact)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation
    async def remove_project_contact(
        self, info: Info, project_id: strawberry.ID, contact_id: strawberry.ID
    ) -> bool:
        ctx = require_role(info.context, "admin", "project_manager")
        try:
            return await remove_project_contact_record(
                ctx.db, actor=ctx.user, project_id=UUID(str(project_id)), contact_id=UUID(str(contact_id))
            )
        except Exception as exc:
            _gql_error(exc)
