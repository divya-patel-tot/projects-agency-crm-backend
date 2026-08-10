import uuid

from sqlalchemy import BigInteger, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.enums import DocumentCategory, PreviewStatus
from app.db.models.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Document(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_entity_version", "entity_type", "entity_id", "version"),)

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    encoding: Mapped[str | None] = mapped_column(String(32), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    preview_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    preview_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PreviewStatus.PENDING.value,
    )
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    line_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    uploaded_by_actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="internal")
