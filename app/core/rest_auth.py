"""Authenticate REST requests using internal JWT bearer tokens."""

from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.core.security import ActorType, TokenType, decode_token
from app.db.models.user import User


def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return header.split(" ", 1)[1].strip()


async def require_internal_admin(request: Request) -> tuple[User, AsyncSession]:
    token = _extract_bearer_token(request)
    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc

    if payload.get("token_type") != TokenType.ACCESS.value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token type")
    if payload.get("actor_type") != ActorType.INTERNAL.value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Internal authentication required")

    user_id = UUID(payload["sub"])
    org_id = UUID(payload["org_id"])
    role = payload.get("role")
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")

    session = AsyncSessionLocal()
    await session.begin()
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )
    await session.execute(
        text("SELECT set_config('app.current_user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )
    await session.execute(
        text("SELECT set_config('app.current_role', :role, true)"),
        {"role": role},
    )

    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None or user.status != "active":
        await session.close()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user, session
