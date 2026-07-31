import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.enums import ApprovalStatus, ApproverType
from app.db.models.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Approval(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_entity", "entity_type", "entity_id"),)

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    approver_type: Mapped[str] = mapped_column(String(32), nullable=False, default=ApproverType.CLIENT.value)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ApprovalStatus.PENDING.value)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
