import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Tag(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_tags_org_name"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)


class EntityTag(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "entity_tags"
    __table_args__ = (
        UniqueConstraint("org_id", "entity_type", "entity_id", "tag_id", name="uq_entity_tags"),
    )

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tags.id"), nullable=False)
