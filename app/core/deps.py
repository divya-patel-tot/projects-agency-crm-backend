from typing import AsyncGenerator
from uuid import UUID

import jwt
from fastapi import Request, Response
from graphql import GraphQLError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.fastapi import BaseContext

from app.core.db import AsyncSessionLocal
from app.core.security import ActorType, TokenType, decode_token
from app.db.models.contact import Contact
from app.db.models.organization import Organization
from app.db.models.user import User

REFRESH_COOKIE_NAME = "refresh_token"
PORTAL_REFRESH_COOKIE_NAME = "portal_refresh_token"


class GraphQLContext(BaseContext):
    def __init__(self) -> None:
        super().__init__()
        self.db: AsyncSession | None = None
        self.user: User | None = None
        self.contact: Contact | None = None
        self.org: Organization | None = None
        self.company_id: UUID | None = None
        self.actor_type: ActorType | None = None


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip()


async def _set_tenant_session(
    session: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID | None = None,
    role: str | None = None,
    contact_id: UUID | None = None,
) -> None:
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )
    actor_id = user_id or contact_id
    if actor_id is not None:
        await session.execute(
            text("SELECT set_config('app.current_user_id', :user_id, true)"),
            {"user_id": str(actor_id)},
        )
    if role is not None:
        await session.execute(
            text("SELECT set_config('app.current_role', :role, true)"),
            {"role": role},
        )


async def _build_internal_context(
    session: AsyncSession,
    *,
    payload: dict,
    request: Request,
    response: Response,
) -> GraphQLContext:
    user_id = UUID(payload["sub"])
    org_id = UUID(payload["org_id"])
    role = payload["role"]

    await _set_tenant_session(session, org_id=org_id, user_id=user_id, role=role)
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None or user.status != "active":
        raise GraphQLError("User not found or inactive", extensions={"code": "authentication_error"})
    org = await session.get(Organization, org_id)
    if org is None:
        raise GraphQLError("Organization not found", extensions={"code": "authentication_error"})

    ctx = GraphQLContext()
    ctx.db = session
    ctx.user = user
    ctx.org = org
    ctx.actor_type = ActorType.INTERNAL
    ctx.request = request
    ctx.response = response
    return ctx


async def _build_portal_context(
    session: AsyncSession,
    *,
    payload: dict,
    request: Request,
    response: Response,
) -> GraphQLContext:
    contact_id = UUID(payload["sub"])
    org_id = UUID(payload["org_id"])
    company_id = UUID(payload["company_id"])

    await _set_tenant_session(session, org_id=org_id, contact_id=contact_id)
    contact = await session.get(Contact, contact_id)
    if (
        contact is None
        or contact.deleted_at is not None
        or not contact.portal_access_enabled
        or contact.status != "active"
        or contact.company_id != company_id
    ):
        raise GraphQLError("Portal contact not found or inactive", extensions={"code": "authentication_error"})
    org = await session.get(Organization, org_id)
    if org is None:
        raise GraphQLError("Organization not found", extensions={"code": "authentication_error"})

    ctx = GraphQLContext()
    ctx.db = session
    ctx.contact = contact
    ctx.org = org
    ctx.company_id = company_id
    ctx.actor_type = ActorType.PORTAL
    ctx.request = request
    ctx.response = response
    return ctx


async def get_graphql_context(
    request: Request,
    response: Response,
) -> AsyncGenerator[GraphQLContext, None]:
    token = _extract_bearer_token(request)
    if not token:
        ctx = GraphQLContext()
        ctx.request = request
        ctx.response = response
        yield ctx
        return

    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise GraphQLError("Invalid access token", extensions={"code": "authentication_error"}) from exc

    if payload.get("token_type") != TokenType.ACCESS.value:
        raise GraphQLError("Invalid access token type", extensions={"code": "authentication_error"})

    actor_type = payload.get("actor_type")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            if actor_type == ActorType.INTERNAL.value:
                ctx = await _build_internal_context(session, payload=payload, request=request, response=response)
            elif actor_type == ActorType.PORTAL.value:
                ctx = await _build_portal_context(session, payload=payload, request=request, response=response)
            else:
                raise GraphQLError("Invalid actor type", extensions={"code": "authentication_error"})
            yield ctx


def require_authenticated(ctx: GraphQLContext) -> GraphQLContext:
    if ctx.user is None or ctx.db is None:
        raise GraphQLError("Authentication required", extensions={"code": "authentication_error"})
    if ctx.actor_type != ActorType.INTERNAL:
        raise GraphQLError("Internal authentication required", extensions={"code": "authentication_error"})
    return ctx


def require_portal(ctx: GraphQLContext) -> GraphQLContext:
    if ctx.contact is None or ctx.db is None or ctx.company_id is None:
        raise GraphQLError("Portal authentication required", extensions={"code": "authentication_error"})
    if ctx.actor_type != ActorType.PORTAL:
        raise GraphQLError("Portal authentication required", extensions={"code": "authentication_error"})
    return ctx


def require_role(ctx: GraphQLContext, *roles: str) -> GraphQLContext:
    ctx = require_authenticated(ctx)
    if ctx.user.role not in roles:
        raise GraphQLError(
            f"Requires one of roles: {', '.join(roles)}",
            extensions={"code": "authorization_error"},
        )
    return ctx


def enforce_portal_company_id(ctx: GraphQLContext, company_id: UUID | None) -> UUID:
    """Return the portal actor's company_id; reject explicit mismatches."""
    ctx = require_portal(ctx)
    if company_id is not None and company_id != ctx.company_id:
        raise GraphQLError(
            "Cannot access data for another company",
            extensions={"code": "authorization_error"},
        )
    return ctx.company_id


def set_refresh_cookie(response: Response, token: str, *, secure: bool, domain: str | None) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        domain=domain or None,
        path="/",
    )


def set_portal_refresh_cookie(response: Response, token: str, *, secure: bool, domain: str | None) -> None:
    response.set_cookie(
        key=PORTAL_REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        domain=domain or None,
        path="/",
    )


def clear_refresh_cookie(response: Response, *, domain: str | None) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/", domain=domain or None)


def clear_portal_refresh_cookie(response: Response, *, domain: str | None) -> None:
    response.delete_cookie(key=PORTAL_REFRESH_COOKIE_NAME, path="/", domain=domain or None)
