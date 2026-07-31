from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import NotFoundError
from app.db.models.contact import Contact
from app.db.models.user import User
from app.graphql.contacts.repository import (
    create_contact,
    get_contact,
    list_contacts,
    soft_delete_contact,
    unset_primary_for_company,
)


def _contact_to_dict(contact: Contact) -> dict:
    return {
        "id": str(contact.id),
        "company_id": str(contact.company_id),
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "email": contact.email,
        "is_primary": contact.is_primary,
        "status": contact.status,
    }


async def get_contacts(db: AsyncSession) -> list[Contact]:
    return await list_contacts(db)


async def get_contact_by_id(db: AsyncSession, contact_id: UUID) -> Contact:
    contact = await get_contact(db, contact_id)
    if contact is None:
        raise NotFoundError("Contact not found")
    return contact


async def create_contact_record(
    db: AsyncSession,
    *,
    actor: User,
    company_id: UUID,
    first_name: str,
    last_name: str,
    email: str | None = None,
    phone: str | None = None,
    title: str | None = None,
    department: str | None = None,
    is_primary: bool = False,
    preferred_channel: str | None = None,
    timezone: str | None = None,
    portal_access_enabled: bool = False,
    linkedin_url: str | None = None,
    status: str = "active",
) -> Contact:
    if is_primary:
        await unset_primary_for_company(db, company_id)
    contact = Contact(
        org_id=actor.org_id,
        company_id=company_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        title=title,
        department=department,
        is_primary=is_primary,
        preferred_channel=preferred_channel,
        timezone=timezone,
        portal_access_enabled=portal_access_enabled,
        linkedin_url=linkedin_url,
        status=status,
    )
    await create_contact(db, contact)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="contact",
        entity_id=contact.id,
        diff={"after": _contact_to_dict(contact)},
    )
    if is_primary:
        from app.db.enums import SequenceTriggerType
        from app.graphql.retention.service import try_auto_enroll

        await try_auto_enroll(
            db,
            org_id=actor.org_id,
            trigger_type=SequenceTriggerType.ON_COMPANY_CREATED.value,
            company_id=company_id,
            contact_id=contact.id,
            actor_id=actor.id,
        )
    return contact


async def update_contact_record(
    db: AsyncSession,
    *,
    actor: User,
    contact_id: UUID,
    updates: dict,
) -> Contact:
    contact = await get_contact_by_id(db, contact_id)
    before = _contact_to_dict(contact)
    if updates.get("is_primary") is True:
        await unset_primary_for_company(db, contact.company_id, exclude_id=contact.id)
    for key, value in updates.items():
        if value is not None and hasattr(contact, key):
            setattr(contact, key, value)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="contact",
        entity_id=contact.id,
        diff={"before": before, "after": _contact_to_dict(contact)},
    )
    return contact


async def delete_contact_record(db: AsyncSession, *, actor: User, contact_id: UUID) -> Contact:
    contact = await get_contact_by_id(db, contact_id)
    before = _contact_to_dict(contact)
    await soft_delete_contact(db, contact)
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="delete",
        entity_type="contact",
        entity_id=contact.id,
        diff={"before": before},
    )
    return contact
