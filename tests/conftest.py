from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.db.models.auth import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_TEST_PATH = BACKEND_ROOT / ".env.test"


def _load_env_test() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_TEST_PATH.exists():
        return values
    for raw_line in ENV_TEST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


@pytest.fixture(scope="session", autouse=True)
def test_settings() -> Settings:
    env_values = _load_env_test()
    for key, value in env_values.items():
        os.environ[key] = value
    get_settings.cache_clear()
    settings = Settings(_env_file=str(ENV_TEST_PATH))
    get_settings.cache_clear()
    return settings


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
    get_settings.cache_clear()
    os.environ.update(_load_env_test())
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    get_settings.cache_clear()
