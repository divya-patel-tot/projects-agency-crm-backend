from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.contact import Contact


def _normalize_email(email: str) -> str:
    return email.lower().strip()


async def find_portal_contact_by_email(db: AsyncSession, email: str) -> Contact | None:
    normalized = _normalize_email(email)
    result = await db.execute(
        select(Contact).where(
            func.lower(Contact.email) == normalized,
            Contact.deleted_at.is_(None),
            Contact.portal_access_enabled.is_(True),
            Contact.status == "active",
        )
    )
    return result.scalar_one_or_none()
