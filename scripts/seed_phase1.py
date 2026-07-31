"""Seed a dev organization and admin user for Phase 1 testing."""

import asyncio
import uuid

from sqlalchemy import select

from app.core.bootstrap import bootstrap_env
from app.core.db import AsyncSessionLocal, get_auth_db, get_tenant_db
from app.core.env_file import optional_env, require_env
from app.core.security import hash_password
from app.db.enums import UserRole, UserStatus
from app.db.models.organization import Organization
from app.db.models.user import User

bootstrap_env()


async def seed() -> None:
    admin_email = require_env("SEED_ADMIN_EMAIL")
    admin_password = require_env("SEED_ADMIN_PASSWORD")
    org_name = optional_env("SEED_ORG_NAME", "Demo Agency") or "Demo Agency"

    async with get_auth_db() as session:
        existing = await session.execute(select(User).where(User.email == admin_email))
        if existing.scalar_one_or_none():
            print(f"Seed skipped — admin {admin_email} already exists.")
            return

    org_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_id, name=org_name, plan="trial", settings={}))

    async with get_tenant_db(org_id) as session:
        session.add(
            User(
                id=uuid.uuid4(),
                org_id=org_id,
                name="Admin User",
                email=admin_email,
                password_hash=hash_password(admin_password),
                role=UserRole.ADMIN.value,
                status=UserStatus.ACTIVE.value,
            )
        )

    print(f"Seeded org '{org_name}' with admin {admin_email}")


if __name__ == "__main__":
    asyncio.run(seed())
