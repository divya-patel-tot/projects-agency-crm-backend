from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import Request

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, get_auth_db, get_tenant_db
from app.core.deps import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from app.core.exceptions import AuthenticationError, DomainError
from app.core.security import (
    ActorType,
    TokenType,
    create_access_token,
    create_challenge_token,
    create_refresh_token,
    decode_token,
    generate_totp_secret,
    get_totp_provisioning_uri,
    hash_password,
    hash_refresh_token,
    verify_password,
    verify_refresh_token_hash,
    verify_totp_code,
)
from app.db.enums import UserRole, UserStatus
from app.db.models.organization import Organization
from app.db.models.user import User
from app.graphql.auth.repository import (
    find_active_users_by_email,
    find_valid_refresh_token,
    revoke_refresh_token,
    store_refresh_token,
)
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AuthResult:
    access_token: str | None = None
    refresh_token: str | None = None
    requires_2fa: bool = False
    challenge_token: str | None = None


def _check_auth_rate_limit(request: Request, bucket: str) -> None:
    from limits import parse
    from limits.storage import storage_from_string
    from limits.strategies import MovingWindowRateLimiter
    from slowapi.util import get_remote_address

    settings = get_settings()
    storage_uri = "memory://"
    limiter = MovingWindowRateLimiter(storage_from_string(storage_uri))
    rate = parse("10/minute" if bucket == "login" else "5/minute" if bucket == "signup" else "20/minute")
    if not limiter.hit(rate, bucket, get_remote_address(request)):
        raise DomainError("Rate limit exceeded", code="rate_limit_exceeded")


async def _issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    settings = get_settings()
    access = create_access_token(sub=user.id, org_id=user.org_id, role=user.role)
    refresh = create_refresh_token(sub=user.id, org_id=user.org_id, role=user.role)
    await store_refresh_token(
        db,
        user_id=user.id,
        token_hash=hash_refresh_token(refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days),
    )
    return access, refresh


async def login(db: AsyncSession, *, email: str, password: str, request: Request) -> AuthResult:
    _check_auth_rate_limit(request, "login")
    users = await find_active_users_by_email(db, email)
    if len(users) != 1:
        raise AuthenticationError("Invalid credentials")
    user = users[0]
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid credentials")
    if user.totp_enabled and user.totp_secret:
        challenge = create_challenge_token(sub=user.id, org_id=user.org_id, role=user.role)
        return AuthResult(requires_2fa=True, challenge_token=challenge)
    access, refresh = await _issue_tokens(db, user)
    return AuthResult(access_token=access, refresh_token=refresh)


async def register_organization(
    *,
    organization_name: str,
    full_name: str,
    email: str,
    password: str,
    request: Request,
) -> AuthResult:
    """Create a new org + admin user, then issue session tokens (no email verification)."""
    _check_auth_rate_limit(request, "signup")
    normalized_email = email.lower().strip()
    org_label = organization_name.strip()
    display_name = full_name.strip()

    if len(org_label) < 2:
        raise DomainError("Organization name must be at least 2 characters.", code="bad_user_input")
    if len(display_name) < 2:
        raise DomainError("Full name must be at least 2 characters.", code="bad_user_input")
    if len(password) < 12:
        raise DomainError("Password must be at least 12 characters.", code="bad_user_input")

    async with get_auth_db() as db:
        existing = await find_active_users_by_email(db, normalized_email)
        if existing:
            raise DomainError("An account with this email already exists.", code="bad_user_input")

    org_id = uuid4()
    user_id = uuid4()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_id, name=org_label, plan="trial", settings={}))

    async with get_tenant_db(org_id) as db:
        db.add(
            User(
                id=user_id,
                org_id=org_id,
                name=display_name,
                email=normalized_email,
                password_hash=hash_password(password),
                role=UserRole.ADMIN.value,
                status=UserStatus.ACTIVE.value,
            )
        )

    async with get_auth_db() as db:
        users = await find_active_users_by_email(db, normalized_email)
        if len(users) != 1:
            raise DomainError("Registration could not be completed.", code="domain_error")
        access, refresh = await _issue_tokens(db, users[0])
        return AuthResult(access_token=access, refresh_token=refresh)


async def verify_totp_login(
    db: AsyncSession,
    *,
    challenge_token: str,
    code: str,
    request: Request,
) -> tuple[str, str]:
    _check_auth_rate_limit(request, "login")
    try:
        payload = decode_token(challenge_token)
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid challenge token") from exc
    if payload.get("token_type") != TokenType.CHALLENGE.value:
        raise AuthenticationError("Invalid challenge token")
    user = await db.get(User, UUID(payload["sub"]))
    if user is None or not user.totp_enabled or not user.totp_secret:
        raise AuthenticationError("2FA not enabled")
    if not verify_totp_code(secret=user.totp_secret, code=code):
        raise AuthenticationError("Invalid TOTP code")
    return await _issue_tokens(db, user)


async def refresh_session(
    db: AsyncSession,
    *,
    refresh_token: str,
    request: Request,
) -> tuple[str, str]:
    _check_auth_rate_limit(request, "refresh")
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid refresh token") from exc
    if payload.get("token_type") != TokenType.REFRESH.value:
        raise AuthenticationError("Invalid refresh token")

    user_id = UUID(payload["sub"])
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AuthenticationError("User not found")

    valid_rows = await find_valid_refresh_token(db, user_id, actor_type=ActorType.INTERNAL.value)
    matched = None
    for row in valid_rows:
        if verify_refresh_token_hash(refresh_token, row.token_hash):
            matched = row
            break
    if matched is None:
        raise AuthenticationError("Refresh token revoked or expired")

    await revoke_refresh_token(db, matched)
    return await _issue_tokens(db, user)


async def logout(db: AsyncSession, *, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError:
        return
    user_id = UUID(payload["sub"])
    valid_rows = await find_valid_refresh_token(db, user_id, actor_type=ActorType.INTERNAL.value)
    for row in valid_rows:
        if verify_refresh_token_hash(refresh_token, row.token_hash):
            await revoke_refresh_token(db, row)
            break


async def enable_totp(db: AsyncSession, user: User) -> tuple[str, str]:
    secret = generate_totp_secret()
    user.totp_secret = secret
    user.totp_enabled = False
    await db.flush()
    uri = get_totp_provisioning_uri(secret=secret, email=user.email)
    return secret, uri


async def confirm_totp(db: AsyncSession, user: User, code: str) -> None:
    if not user.totp_secret:
        raise DomainError("TOTP setup not started")
    if not verify_totp_code(secret=user.totp_secret, code=code):
        raise AuthenticationError("Invalid TOTP code")
    user.totp_enabled = True
    await db.flush()


async def disable_totp(db: AsyncSession, user: User) -> None:
    user.totp_secret = None
    user.totp_enabled = False
    user.totp_backup_codes = None
    await db.flush()


def apply_refresh_cookie(response, refresh_token: str) -> None:
    settings = get_settings()
    set_refresh_cookie(
        response,
        refresh_token,
        secure=settings.cookie_secure,
        domain=settings.cookie_domain,
    )


def clear_refresh_cookie_on_response(response) -> None:
    settings = get_settings()
    clear_refresh_cookie(response, domain=settings.cookie_domain)


def get_refresh_token_from_request(request: Request) -> str | None:
    return request.cookies.get(REFRESH_COOKIE_NAME)
