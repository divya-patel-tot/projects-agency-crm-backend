from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_async_engine = None
_sync_engine = None
_async_session_local = None
_sync_session_local = None


def _ensure_engines() -> None:
    global _async_engine, _sync_engine, _async_session_local, _sync_session_local
    if _async_engine is not None:
        return
    settings = get_settings()
    _async_engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
    )
    _async_session_local = async_sessionmaker(
        bind=_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    _sync_engine = create_engine(
        settings.database_url_sync,
        pool_pre_ping=True,
    )
    _sync_session_local = sessionmaker(
        bind=_sync_engine,
        class_=Session,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


def reset_db_engines() -> None:
    global _async_engine, _sync_engine, _async_session_local, _sync_session_local
    if _async_engine is not None:
        _async_engine.sync_engine.dispose()
    if _sync_engine is not None:
        _sync_engine.dispose()
    _async_engine = None
    _sync_engine = None
    _async_session_local = None
    _sync_session_local = None


class _AsyncSessionLocalFactory:
    def __call__(self, *args, **kwargs):
        _ensure_engines()
        return _async_session_local(*args, **kwargs)


AsyncSessionLocal = _AsyncSessionLocalFactory()


def __getattr__(name: str):
    if name == "async_engine":
        _ensure_engines()
        return _async_engine
    if name == "sync_engine":
        _ensure_engines()
        return _sync_engine
    if name == "SyncSessionLocal":
        _ensure_engines()
        return _sync_session_local
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
