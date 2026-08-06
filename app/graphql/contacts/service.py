from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.security import hash_password
from app.core.exceptions import DomainError, NotFoundError
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


async def _apply_portal_password(contact: Contact, *, portal_access_enabled: bool, portal_password: str | None) -> None:
    if portal_password:
        if len(portal_password) < 12:
            raise DomainError("Portal password must be at least 12 characters.", code="bad_user_input")
        contact.password_hash = hash_password(portal_password)
        return
    if portal_access_enabled and not contact.password_hash:
        raise DomainError(
            "Set a portal password when enabling client portal access.",
            code="bad_user_input",
        )


def _normalize_contact_email(email: str | None) -> str | None:
    if email is None:
        return None
    normalized = email.strip().lower()
    return normalized or None


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
    portal_can_raise_requests: bool = False,
    portal_password: str | None = None,
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
        email=_normalize_contact_email(email),
        phone=phone,
        title=title,
        department=department,
        is_primary=is_primary,
        preferred_channel=preferred_channel,
        timezone=timezone,
        portal_access_enabled=portal_access_enabled,
        portal_can_raise_requests=portal_can_raise_requests,
        linkedin_url=linkedin_url,
        status=status,
    )
    await _apply_portal_password(
        contact,
        portal_access_enabled=portal_access_enabled,
        portal_password=portal_password,
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


async def set_contact_portal_password_record(
    db: AsyncSession,
    *,
    actor: User,
    contact_id: UUID,
    password: str,
) -> Contact:
    if len(password) < 12:
        raise DomainError("Portal password must be at least 12 characters.", code="bad_user_input")
    contact = await get_contact_by_id(db, contact_id)
    contact.password_hash = hash_password(password)
    if not contact.portal_access_enabled:
        contact.portal_access_enabled = True
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="contact",
        entity_id=contact.id,
        diff={"after": {"portal_access_enabled": True, "portal_password_set": True}},
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

    portal_password = updates.pop("portal_password", None)
    if "email" in updates and updates["email"] is not None:
        updates["email"] = _normalize_contact_email(updates["email"])
    for key, value in updates.items():
        if value is not None and hasattr(contact, key):
            setattr(contact, key, value)

    if portal_password is not None:
        await _apply_portal_password(
            contact,
            portal_access_enabled=contact.portal_access_enabled,
            portal_password=portal_password,
        )
    elif contact.portal_access_enabled and not contact.password_hash:
        raise DomainError(
            "Set a portal password when enabling client portal access.",
            code="bad_user_input",
        )

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
