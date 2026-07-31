import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from app.core.db import get_auth_db
from app.core.deps import GraphQLContext, require_authenticated
from app.core.exceptions import AuthenticationError, DomainError
from app.graphql.auth.service import (
    apply_refresh_cookie,
    clear_refresh_cookie_on_response,
    confirm_totp,
    disable_totp,
    enable_totp,
    get_refresh_token_from_request,
    login as login_service,
    logout,
    refresh_session,
    verify_totp_login,
)


def _to_graphql_error(exc: Exception) -> None:
    if isinstance(exc, (AuthenticationError, DomainError)):
        raise GraphQLError(exc.message, extensions={"code": exc.code}) from exc
    raise exc


@strawberry.type
class AuthPayload:
    access_token: str | None
    requires_2fa: bool = False
    challenge_token: str | None = None


@strawberry.type
class TotpSetupPayload:
    secret: str
    provisioning_uri: str


@strawberry.type
class AuthMutation:
    @strawberry.mutation
    async def login(self, info: Info, email: str, password: str) -> AuthPayload:
        ctx: GraphQLContext = info.context
        try:
            async with get_auth_db() as db:
                result = await login_service(db, email=email.lower(), password=password, request=ctx.request)
                if result.access_token and result.refresh_token:
                    apply_refresh_cookie(ctx.response, result.refresh_token)
                    return AuthPayload(access_token=result.access_token, requires_2fa=False)
                return AuthPayload(
                    access_token=None,
                    requires_2fa=result.requires_2fa,
                    challenge_token=result.challenge_token,
                )
        except Exception as exc:
            _to_graphql_error(exc)

    @strawberry.mutation
    async def verify_totp(self, info: Info, challenge_token: str, code: str) -> AuthPayload:
        ctx: GraphQLContext = info.context
        async with get_auth_db() as db:
            access, refresh = await verify_totp_login(
                db,
                challenge_token=challenge_token,
                code=code,
                request=ctx.request,
            )
            apply_refresh_cookie(ctx.response, refresh)
            return AuthPayload(access_token=access, requires_2fa=False)

    @strawberry.mutation
    async def refresh_token(self, info: Info) -> AuthPayload:
        ctx: GraphQLContext = info.context
        token = get_refresh_token_from_request(ctx.request)
        if not token:
            raise DomainError("Missing refresh token", code="authentication_error")
        async with get_auth_db() as db:
            access, refresh = await refresh_session(db, refresh_token=token, request=ctx.request)
            apply_refresh_cookie(ctx.response, refresh)
            return AuthPayload(access_token=access, requires_2fa=False)

    @strawberry.mutation
    async def logout(self, info: Info) -> bool:
        ctx: GraphQLContext = info.context
        token = get_refresh_token_from_request(ctx.request)
        async with get_auth_db() as db:
            await logout(db, refresh_token=token)
        clear_refresh_cookie_on_response(ctx.response)
        return True

    @strawberry.mutation
    async def enable_totp(self, info: Info) -> TotpSetupPayload:
        ctx = require_authenticated(info.context)
        secret, uri = await enable_totp(ctx.db, ctx.user)
        return TotpSetupPayload(secret=secret, provisioning_uri=uri)

    @strawberry.mutation
    async def confirm_totp(self, info: Info, code: str) -> bool:
        ctx = require_authenticated(info.context)
        await confirm_totp(ctx.db, ctx.user, code)
        return True

    @strawberry.mutation
    async def disable_totp(self, info: Info) -> bool:
        ctx = require_authenticated(info.context)
        await disable_totp(ctx.db, ctx.user)
        return True
