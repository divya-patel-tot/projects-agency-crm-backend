from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import AuthorizationError, DomainError, NotFoundError
from app.db.enums import UserRole, UserStatus
from app.db.models.user import User
from app.core.security import hash_password


_VALID_ROLES = frozenset(role.value for role in UserRole)


def _validate_role(role: str) -> str:
    normalized = role.lower().strip()
    if normalized not in _VALID_ROLES:
        raise DomainError(f"Invalid role: {role}", code="bad_user_input")
    return normalized


async def _get_org_user(db: AsyncSession, user_id: UUID, org_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None or user.org_id != org_id:
        raise NotFoundError("User not found")
    return user


async def create_user_record(
    db: AsyncSession,
    *,
    actor: User,
    name: str,
    email: str,
    password: str,
    role: str,
) -> User:
    if actor.role != UserRole.ADMIN.value:
        raise AuthorizationError("Only admins can invite team members")

    display_name = name.strip()
    normalized_email = email.lower().strip()
    role_value = _validate_role(role)

    if len(display_name) < 2:
        raise DomainError("Name must be at least 2 characters.", code="bad_user_input")
    if len(password) < 12:
        raise DomainError("Password must be at least 12 characters.", code="bad_user_input")

    existing = await db.execute(
        select(User.id).where(
            User.org_id == actor.org_id,
            User.email == normalized_email,
            User.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise DomainError("A user with this email already exists in your organization.", code="bad_user_input")

    user = User(
        org_id=actor.org_id,
        name=display_name,
        email=normalized_email,
        password_hash=hash_password(password),
        role=role_value,
        status=UserStatus.ACTIVE.value,
    )
    db.add(user)
    await db.flush()

    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="user",
        entity_id=user.id,
        diff={"after": {"id": str(user.id), "email": user.email, "role": user.role}},
    )
    return user


async def update_user_record(
    db: AsyncSession,
    *,
    actor: User,
    user_id: UUID,
    name: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> User:
    if actor.role != UserRole.ADMIN.value:
        raise AuthorizationError("Only admins can update team members")

    user = await _get_org_user(db, user_id, actor.org_id)
    before = {"name": user.name, "role": user.role, "status": user.status}

    if name is not None:
        cleaned = name.strip()
        if len(cleaned) < 2:
            raise DomainError("Name must be at least 2 characters.", code="bad_user_input")
        user.name = cleaned

    if role is not None:
        role_value = _validate_role(role)
        if user.id == actor.id and role_value != UserRole.ADMIN.value:
            raise DomainError("You cannot remove your own admin role.", code="bad_user_input")
        user.role = role_value

    if status is not None:
        normalized = status.lower().strip()
        if normalized not in {UserStatus.ACTIVE.value, UserStatus.INACTIVE.value, UserStatus.INVITED.value}:
            raise DomainError("Invalid user status.", code="bad_user_input")
        if user.id == actor.id and normalized != UserStatus.ACTIVE.value:
            raise DomainError("You cannot deactivate your own account.", code="bad_user_input")
        user.status = normalized

    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="user",
        entity_id=user.id,
        diff={"before": before, "after": {"name": user.name, "role": user.role, "status": user.status}},
    )
    return user
