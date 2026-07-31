"""Seed a dev organization and admin user for Phase 1 testing."""

import asyncio
import uuid

from sqlalchemy import select, text

from app.core.db import AsyncSessionLocal, get_auth_db, get_tenant_db
from app.core.security import hash_password
from app.db.enums import UserRole, UserStatus
from app.db.models.organization import Organization
from app.db.models.user import User

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "ChangeMe123!"
ORG_NAME = "Demo Agency"


async def seed() -> None:
    async with get_auth_db() as session:
        existing = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
        if existing.scalar_one_or_none():
            print(f"Seed skipped — admin {ADMIN_EMAIL} already exists.")
            return

    org_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_id, name=ORG_NAME, plan="trial", settings={}))

    async with get_tenant_db(org_id) as session:
        session.add(
            User(
                id=uuid.uuid4(),
                org_id=org_id,
                name="Admin User",
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                role=UserRole.ADMIN.value,
                status=UserStatus.ACTIVE.value,
            )
        )

    print(f"Seeded org '{ORG_NAME}' with admin {ADMIN_EMAIL} / {ADMIN_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
