from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from app.core.config import get_settings

settings = get_settings()

async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Alembic runs in a separate sync process outside the asyncio event loop.
sync_engine = create_engine(
    settings.database_url_sync,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Unscoped session for auth lookups (uses app.auth_mode RLS policy)."""
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def get_auth_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SELECT set_config('app.auth_mode', 'login', true)"))
            yield session


@asynccontextmanager
async def get_tenant_db(
    org_id: UUID,
    user_id: UUID | None = None,
    role: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Open a tenant-scoped session with RLS context set via SET LOCAL inside the transaction."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(org_id)},
            )
            if user_id is not None:
                await session.execute(
                    text("SELECT set_config('app.current_user_id', :user_id, true)"),
                    {"user_id": str(user_id)},
                )
            if role is not None:
                await session.execute(
                    text("SELECT set_config('app.current_role', :role, true)"),
                    {"role": role},
                )
            yield session


async def check_database_connection() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — startup probe only
        return False
