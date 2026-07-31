from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import RefreshToken
from app.db.models.user import User


async def find_active_users_by_email(db: AsyncSession, email: str) -> list[User]:
    result = await db.execute(
        select(User).where(
            User.email == email.lower(),
            User.deleted_at.is_(None),
            User.status == "active",
        )
    )
    return list(result.scalars().all())


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    return await db.get(User, user_id)


async def store_refresh_token(
    db: AsyncSession,
    *,
    user_id: UUID,
    token_hash: str,
    expires_at: datetime,
    actor_type: str = "internal",
) -> RefreshToken:
    row = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        actor_type=actor_type,
    )
    db.add(row)
    await db.flush()
    return row


async def find_valid_refresh_token(
    db: AsyncSession,
    user_id: UUID,
    *,
    actor_type: str = "internal",
) -> list[RefreshToken]:
    now = datetime.now(UTC)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.actor_type == actor_type,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
    )
    return list(result.scalars().all())


async def revoke_refresh_token(db: AsyncSession, token_row: RefreshToken) -> None:
    token_row.revoked_at = datetime.now(UTC)
    await db.flush()
