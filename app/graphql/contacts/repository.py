from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.contact import Contact


async def list_contacts(db: AsyncSession) -> list[Contact]:
    result = await db.execute(
        select(Contact).where(Contact.deleted_at.is_(None)).order_by(Contact.last_name, Contact.first_name)
    )
    return list(result.scalars().all())


async def get_contact(db: AsyncSession, contact_id: UUID) -> Contact | None:
    result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_contacts_by_company_ids(db: AsyncSession, company_ids: list[UUID]) -> list[Contact]:
    if not company_ids:
        return []
    result = await db.execute(
        select(Contact).where(
            Contact.company_id.in_(company_ids),
            Contact.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def unset_primary_for_company(db: AsyncSession, company_id: UUID, exclude_id: UUID | None = None) -> None:
    stmt = (
        update(Contact)
        .where(Contact.company_id == company_id, Contact.is_primary.is_(True))
        .values(is_primary=False)
    )
    if exclude_id:
        stmt = stmt.where(Contact.id != exclude_id)
    await db.execute(stmt)


async def create_contact(db: AsyncSession, contact: Contact) -> Contact:
    db.add(contact)
    await db.flush()
    return contact


async def soft_delete_contact(db: AsyncSession, contact: Contact) -> Contact:
    contact.deleted_at = datetime.now(UTC)
    await db.flush()
    return contact
