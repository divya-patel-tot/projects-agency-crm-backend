from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

import jwt
import pyotp
from pwdlib import PasswordHash

from app.core.config import Settings, get_settings

_password_hasher = PasswordHash.recommended()


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    CHALLENGE = "challenge"
    UPLOAD = "upload"


class ActorType(StrEnum):
    INTERNAL = "internal"
    PORTAL = "portal"


def hash_password(plain_password: str) -> str:
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _password_hasher.verify(plain_password, password_hash)


def hash_refresh_token(token: str) -> str:
    return hash_password(token)


def verify_refresh_token_hash(token: str, token_hash: str) -> bool:
    return verify_password(token, token_hash)


def _encode_token(
    payload: dict[str, Any],
    *,
    expires_delta: timedelta,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    to_encode = payload.copy()
    now = datetime.now(UTC)
    to_encode.update(
        {
            "iat": now,
            "exp": now + expires_delta,
            "jti": str(uuid4()),
        }
    )
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(
    *,
    sub: UUID,
    org_id: UUID,
    role: str | None = None,
    company_id: UUID | None = None,
    actor_type: ActorType = ActorType.INTERNAL,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    payload: dict[str, Any] = {
        "sub": str(sub),
        "org_id": str(org_id),
        "actor_type": actor_type.value,
        "token_type": TokenType.ACCESS.value,
    }
    if actor_type == ActorType.INTERNAL:
        if role is None:
            raise ValueError("role is required for internal access tokens")
        payload["role"] = role
    elif actor_type == ActorType.PORTAL:
        if company_id is None:
            raise ValueError("company_id is required for portal access tokens")
        payload["company_id"] = str(company_id)
    return _encode_token(
        payload,
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
        settings=settings,
    )


def create_refresh_token(
    *,
    sub: UUID,
    org_id: UUID,
    role: str | None = None,
    company_id: UUID | None = None,
    actor_type: ActorType = ActorType.INTERNAL,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    payload: dict[str, Any] = {
        "sub": str(sub),
        "org_id": str(org_id),
        "actor_type": actor_type.value,
        "token_type": TokenType.REFRESH.value,
    }
    if actor_type == ActorType.INTERNAL:
        if role is None:
            raise ValueError("role is required for internal refresh tokens")
        payload["role"] = role
    elif actor_type == ActorType.PORTAL:
        if company_id is None:
            raise ValueError("company_id is required for portal refresh tokens")
        payload["company_id"] = str(company_id)
    return _encode_token(
        payload,
        expires_delta=timedelta(days=settings.jwt_refresh_token_expire_days),
        settings=settings,
    )


def create_challenge_token(
    *,
    sub: UUID,
    org_id: UUID,
    role: str,
    settings: Settings | None = None,
) -> str:
    return _encode_token(
        {
            "sub": str(sub),
            "org_id": str(org_id),
            "role": role,
            "actor_type": ActorType.INTERNAL.value,
            "token_type": TokenType.CHALLENGE.value,
        },
        expires_delta=timedelta(minutes=5),
        settings=settings,
    )


def create_upload_token(
    *,
    org_id: UUID,
    relative_path: str,
    content_type: str,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    return _encode_token(
        {
            "org_id": str(org_id),
            "relative_path": relative_path,
            "content_type": content_type,
            "token_type": TokenType.UPLOAD.value,
        },
        expires_delta=timedelta(minutes=settings.assets_upload_token_expire_minutes),
        settings=settings,
    )


def decode_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_provisioning_uri(*, secret: str, email: str, issuer: str = "Agency CRM") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp_code(*, secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
