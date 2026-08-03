from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from uuid import UUID

import jwt
from fastapi import Request

from app.core.config import get_settings
from app.core.deps import (
    PORTAL_REFRESH_COOKIE_NAME,
    clear_portal_refresh_cookie,
    set_portal_refresh_cookie,
)
from app.core.exceptions import AuthenticationError, DomainError
from app.core.security import (
    ActorType,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_refresh_token,
    verify_password,
    verify_refresh_token_hash,
)
from app.db.models.contact import Contact
from app.graphql.auth.repository import find_valid_refresh_token, revoke_refresh_token, store_refresh_token
from app.graphql.portal.auth.repository import find_portal_contact_by_email
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class PortalAuthResult:
    access_token: str
    refresh_token: str


def _check_portal_rate_limit(request: Request, bucket: str) -> None:
    from limits import parse
    from limits.storage import storage_from_string
    from limits.strategies import MovingWindowRateLimiter
    from slowapi.util import get_remote_address

    settings = get_settings()
    storage_uri = "memory://"
    limiter = MovingWindowRateLimiter(storage_from_string(storage_uri))
    rate = parse("10/minute" if bucket == "login" else "20/minute")
    if not limiter.hit(rate, f"portal_{bucket}", get_remote_address(request)):
        raise DomainError("Rate limit exceeded", code="rate_limit_exceeded")


async def _issue_portal_tokens(db: AsyncSession, contact: Contact) -> tuple[str, str]:
    settings = get_settings()
    access = create_access_token(
        sub=contact.id,
        org_id=contact.org_id,
        company_id=contact.company_id,
        actor_type=ActorType.PORTAL,
    )
    refresh = create_refresh_token(
        sub=contact.id,
        org_id=contact.org_id,
        company_id=contact.company_id,
        actor_type=ActorType.PORTAL,
    )
    await store_refresh_token(
        db,
        user_id=contact.id,
        token_hash=hash_refresh_token(refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days),
        actor_type=ActorType.PORTAL.value,
    )
    return access, refresh


async def portal_login(db: AsyncSession, *, email: str, password: str, request: Request) -> PortalAuthResult:
    _check_portal_rate_limit(request, "login")
    normalized_email = email.lower().strip()
    contact = await find_portal_contact_by_email(db, normalized_email)
    if contact is None:
        logger.warning("Portal login failed: no active portal contact for email=%s", normalized_email)
        raise AuthenticationError("Invalid credentials")
    if not contact.password_hash:
        logger.warning("Portal login failed: portal password not set contact_id=%s", contact.id)
        raise AuthenticationError("Invalid credentials")
    if not verify_password(password, contact.password_hash):
        logger.warning("Portal login failed: password mismatch contact_id=%s", contact.id)
        raise AuthenticationError("Invalid credentials")
    access, refresh = await _issue_portal_tokens(db, contact)
    return PortalAuthResult(access_token=access, refresh_token=refresh)


async def portal_refresh_session(
    db: AsyncSession,
    *,
    refresh_token: str,
    request: Request,
) -> tuple[str, str]:
    _check_portal_rate_limit(request, "refresh")
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid refresh token") from exc
    if payload.get("token_type") != TokenType.REFRESH.value:
        raise AuthenticationError("Invalid refresh token")
    if payload.get("actor_type") != ActorType.PORTAL.value:
        raise AuthenticationError("Invalid refresh token")

    contact_id = UUID(payload["sub"])
    contact = await db.get(Contact, contact_id)
    if (
        contact is None
        or contact.deleted_at is not None
        or not contact.portal_access_enabled
        or contact.status != "active"
    ):
        raise AuthenticationError("Portal contact not found")

    valid_rows = await find_valid_refresh_token(db, contact_id, actor_type=ActorType.PORTAL.value)
    matched = None
    for row in valid_rows:
        if verify_refresh_token_hash(refresh_token, row.token_hash):
            matched = row
            break
    if matched is None:
        raise AuthenticationError("Refresh token revoked or expired")

    await revoke_refresh_token(db, matched)
    return await _issue_portal_tokens(db, contact)


async def portal_logout(db: AsyncSession, *, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError:
        return
    if payload.get("actor_type") != ActorType.PORTAL.value:
        return
    contact_id = UUID(payload["sub"])
    valid_rows = await find_valid_refresh_token(db, contact_id, actor_type=ActorType.PORTAL.value)
    for row in valid_rows:
        if verify_refresh_token_hash(refresh_token, row.token_hash):
            await revoke_refresh_token(db, row)
            break


def apply_portal_refresh_cookie(response, refresh_token: str) -> None:
    settings = get_settings()
    set_portal_refresh_cookie(
        response,
        refresh_token,
        secure=settings.cookie_secure,
        domain=settings.cookie_domain,
    )


def clear_portal_refresh_cookie_on_response(response) -> None:
    settings = get_settings()
    clear_portal_refresh_cookie(response, domain=settings.cookie_domain)


def get_portal_refresh_token_from_request(request) -> str | None:
    return request.cookies.get(PORTAL_REFRESH_COOKIE_NAME)
