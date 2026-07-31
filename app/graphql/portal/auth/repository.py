from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.contact import Contact


async def find_portal_contact_by_email(db: AsyncSession, email: str) -> Contact | None:
    result = await db.execute(
        select(Contact).where(
            Contact.email == email.lower(),
            Contact.deleted_at.is_(None),
            Contact.portal_access_enabled.is_(True),
            Contact.status == "active",
        )
    )
    return result.scalar_one_or_none()
