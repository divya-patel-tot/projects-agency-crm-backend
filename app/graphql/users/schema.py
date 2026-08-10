from __future__ import annotations

from uuid import UUID

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.deps import GraphQLContext, require_authenticated
from app.core.exceptions import AuthorizationError, DomainError, NotFoundError
from app.db.models.user import User
from app.graphql.users.service import create_user_record, delete_user_record, update_user_record
from sqlalchemy import select


def _gql_error(exc: Exception) -> None:
    if isinstance(exc, (DomainError, NotFoundError, AuthorizationError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class UserSummaryType:
    id: strawberry.ID
    name: str
    email: str
    role: str
    job_title: str | None = None
    avatar_url: str | None = None
    status: str | None = None

    @classmethod
    def from_model(cls, user: User) -> "UserSummaryType":
        return cls(
            id=strawberry.ID(str(user.id)),
            name=user.name,
            email=user.email,
            role=user.role,
            job_title=user.job_title,
            avatar_url=user.avatar_url,
            status=user.status,
        )


@strawberry.type
class UserQuery:
    @strawberry.field
    async def users(self, info: Info) -> list[UserSummaryType]:
        ctx = require_authenticated(info.context)
        result = await ctx.db.execute(
            select(User)
            .where(User.org_id == ctx.user.org_id, User.deleted_at.is_(None))
            .order_by(User.name)
        )
        return [UserSummaryType.from_model(row) for row in result.scalars().all()]

    @strawberry.field
    async def user(self, info: Info, id: strawberry.ID) -> UserSummaryType | None:
        ctx = require_authenticated(info.context)
        row = await ctx.db.get(User, UUID(str(id)))
        if row is None or row.deleted_at is not None or row.org_id != ctx.user.org_id:
            return None
        return UserSummaryType.from_model(row)


@strawberry.type
class UserMutation:
    @strawberry.mutation(
        description="Invite a team member. Admins can invite any role; project managers can only invite a team member."
    )
    async def create_user(
        self,
        info: Info,
        name: str,
        email: str,
        password: str,
        role: str,
    ) -> UserSummaryType:
        ctx: GraphQLContext = require_authenticated(info.context)
        try:
            row = await create_user_record(
                ctx.db,
                actor=ctx.user,
                name=name,
                email=email,
                password=password,
                role=role,
            )
            return UserSummaryType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation(description="Update a team member role or status (admin only).")
    async def update_user(
        self,
        info: Info,
        id: strawberry.ID,
        name: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> UserSummaryType:
        ctx: GraphQLContext = require_authenticated(info.context)
        try:
            row = await update_user_record(
                ctx.db,
                actor=ctx.user,
                user_id=UUID(str(id)),
                name=name,
                role=role,
                status=status,
            )
            return UserSummaryType.from_model(row)
        except Exception as exc:
            _gql_error(exc)

    @strawberry.mutation(
        description="Permanently delete a team member. Admins can delete anyone; project managers "
        "can only delete a team member. Cannot be undone."
    )
    async def delete_user(self, info: Info, id: strawberry.ID) -> bool:
        ctx: GraphQLContext = require_authenticated(info.context)
        try:
            await delete_user_record(ctx.db, actor=ctx.user, user_id=UUID(str(id)))
            return True
        except Exception as exc:
            _gql_error(exc)
