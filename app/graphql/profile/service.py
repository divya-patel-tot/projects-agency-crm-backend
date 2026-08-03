from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import AuthenticationError, DomainError
from app.core.security import hash_password, verify_password
from app.db.models.contact import Contact
from app.db.models.user import User
from app.graphql.profile.preferences import normalize_preferences, preferences_for_storage


async def get_notification_preferences(
    *,
    user: User | None = None,
    contact: Contact | None = None,
) -> dict[str, dict[str, bool]]:
    if user is not None:
        return normalize_preferences(user.preferences, portal=False)
    if contact is not None:
        return normalize_preferences(contact.preferences, portal=True)
    return {}


async def update_internal_profile(
    db: AsyncSession,
    *,
    user: User,
    name: str | None = None,
    avatar_url: str | None = None,
) -> User:
    if name is not None:
        cleaned = name.strip()
        if len(cleaned) < 2:
            raise DomainError("Name must be at least 2 characters.", code="bad_user_input")
        user.name = cleaned

    if avatar_url is not None:
        cleaned = avatar_url.strip()
        user.avatar_url = cleaned or None

    await db.flush()
    return user


async def update_portal_profile(
    db: AsyncSession,
    *,
    contact: Contact,
    first_name: str | None = None,
    last_name: str | None = None,
    title: str | None = None,
) -> Contact:
    if first_name is not None:
        cleaned = first_name.strip()
        if len(cleaned) < 1:
            raise DomainError("First name is required.", code="bad_user_input")
        contact.first_name = cleaned

    if last_name is not None:
        cleaned = last_name.strip()
        if len(cleaned) < 1:
            raise DomainError("Last name is required.", code="bad_user_input")
        contact.last_name = cleaned

    if title is not None:
        contact.title = title.strip() or None

    await db.flush()
    return contact


async def change_internal_password(
    db: AsyncSession,
    *,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise AuthenticationError("Current password is incorrect.")
    if len(new_password) < 12:
        raise DomainError("New password must be at least 12 characters.", code="bad_user_input")
    if current_password == new_password:
        raise DomainError("Choose a password different from your current one.", code="bad_user_input")

    user.password_hash = hash_password(new_password)
    await db.flush()

    await write_activity_log(
        db,
        org_id=user.org_id,
        actor_id=user.id,
        action="update",
        entity_type="user",
        entity_id=user.id,
        diff={"after": {"password_changed": True}},
    )


async def change_portal_password(
    db: AsyncSession,
    *,
    contact: Contact,
    current_password: str,
    new_password: str,
) -> None:
    if not contact.password_hash:
        raise DomainError("Portal password is not set.", code="bad_user_input")
    if not verify_password(current_password, contact.password_hash):
        raise AuthenticationError("Current password is incorrect.")
    if len(new_password) < 12:
        raise DomainError("New password must be at least 12 characters.", code="bad_user_input")
    if current_password == new_password:
        raise DomainError("Choose a password different from your current one.", code="bad_user_input")

    contact.password_hash = hash_password(new_password)
    await db.flush()


async def update_notification_preferences(
    db: AsyncSession,
    *,
    user: User | None = None,
    contact: Contact | None = None,
    preferences: dict[str, dict[str, bool]],
) -> dict[str, dict[str, bool]]:
    if user is not None:
        user.preferences = preferences_for_storage(preferences, portal=False)
        await db.flush()
        return normalize_preferences(user.preferences, portal=False)

    if contact is not None:
        contact.preferences = preferences_for_storage(preferences, portal=True)
        await db.flush()
        return normalize_preferences(contact.preferences, portal=True)

    return {}
