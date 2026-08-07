import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    # Postgres supports RETURNING, so make the ORM fetch server-generated
    # columns (like TimestampMixin.updated_at's onupdate=func.now()) as part
    # of the same INSERT/UPDATE statement rather than marking them expired.
    # Without this, reading such a column right after a flush — outside of a
    # further awaited DB call — throws sqlalchemy.exc.MissingGreenlet, since
    # the lazy re-fetch needed to un-expire it can't run outside the async
    # greenlet context an ORM attribute access isn't itself wrapped in.
    __abstract__ = True
    __mapper_args__ = {"eager_defaults": True}


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrgScopedMixin:
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
