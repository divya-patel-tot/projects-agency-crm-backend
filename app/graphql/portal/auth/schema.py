from __future__ import annotations

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.db import get_auth_db
from app.core.deps import GraphQLContext
from app.core.exceptions import AuthenticationError, DomainError
from app.graphql.portal.auth.service import (
    apply_portal_refresh_cookie,
    clear_portal_refresh_cookie_on_response,
    get_portal_refresh_token_from_request,
    portal_login as portal_login_service,
    portal_logout,
    portal_refresh_session,
)


def _to_graphql_error(exc: Exception) -> None:
    if isinstance(exc, (AuthenticationError, DomainError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class PortalAuthPayload:
    access_token: str


@strawberry.type
class PortalAuthMutation:
    @strawberry.mutation
    async def portal_login(self, info: Info, email: str, password: str) -> PortalAuthPayload:
        ctx: GraphQLContext = info.context
        try:
            async with get_auth_db() as db:
                result = await portal_login_service(
                    db,
                    email=email.lower().strip(),
                    password=password,
                    request=ctx.request,
                )
                apply_portal_refresh_cookie(ctx.response, result.refresh_token)
                return PortalAuthPayload(access_token=result.access_token)
        except Exception as exc:
            _to_graphql_error(exc)

    @strawberry.mutation
    async def portal_refresh_token(self, info: Info) -> PortalAuthPayload:
        ctx: GraphQLContext = info.context
        token = get_portal_refresh_token_from_request(ctx.request)
        if not token:
            raise GraphQLError("Missing refresh token", extensions={"code": "authentication_error"})
        try:
            async with get_auth_db() as db:
                access, refresh = await portal_refresh_session(db, refresh_token=token, request=ctx.request)
                apply_portal_refresh_cookie(ctx.response, refresh)
                return PortalAuthPayload(access_token=access)
        except Exception as exc:
            _to_graphql_error(exc)

    @strawberry.mutation
    async def portal_logout(self, info: Info) -> bool:
        ctx: GraphQLContext = info.context
        token = get_portal_refresh_token_from_request(ctx.request)
        async with get_auth_db() as db:
            await portal_logout(db, refresh_token=token)
        clear_portal_refresh_cookie_on_response(ctx.response)
        return True
