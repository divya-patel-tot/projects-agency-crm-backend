import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.enums import ChangeRequestPriority, ChangeRequestStatus, ChangeRequestType
from app.db.models.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ChangeRequest(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "change_requests"
    __table_args__ = (
        Index("ix_change_requests_project_status", "project_id", "status"),
        Index("ix_change_requests_org_status", "org_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    requested_by_contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default=ChangeRequestType.OTHER.value)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default=ChangeRequestPriority.MEDIUM.value)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default=ChangeRequestStatus.SUBMITTED.value)
    impact_hours: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    impact_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    impact_timeline_days: Mapped[int | None] = mapped_column(nullable=True)
    assessment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_pm_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    requires_client_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_internal_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision_count: Mapped[int] = mapped_column(nullable=False, default=0)
    manager_escalation_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    desired_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attachments: Mapped[list["ChangeRequestAttachment"]] = relationship(back_populates="change_request")


class ChangeRequestAttachment(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "change_request_attachments"

    change_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("change_requests.id"),
        nullable=False,
        index=True,
    )
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    change_request: Mapped["ChangeRequest"] = relationship(back_populates="attachments")
