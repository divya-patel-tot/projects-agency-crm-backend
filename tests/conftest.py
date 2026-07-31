from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.bootstrap import bootstrap_test_env, reload_runtime_config
from app.core.config import Settings, get_settings


@pytest.fixture(scope="session", autouse=True)
def test_settings() -> Settings:
    bootstrap_test_env(force=True)
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(autouse=True)
async def reset_db_pool():
    yield
    from app.core.db import async_engine

    await async_engine.dispose()


@pytest.fixture(scope="session")
def test_engine(test_settings: Settings):
    engine = create_async_engine(test_settings.database_url, pool_pre_ping=True)
    yield engine
    engine.sync_engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        async with session_factory(bind=connection) as session:
            yield session
        await transaction.rollback()


@pytest_asyncio.fixture
async def client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    reload_runtime_config()
    bootstrap_test_env(force=True)
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    get_settings.cache_clear()
