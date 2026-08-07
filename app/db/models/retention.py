import uuid
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.enums import (
    EnrollmentStatus,
    SequenceSource,
    SequenceStatus,
    SequenceTriggerType,
    TouchpointChannel,
    TouchpointOutcome,
    TouchpointStatus,
)
from app.db.models.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class EmailTemplate(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "email_templates"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class RetentionSequence(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "retention_sequences"
    __table_args__ = (Index("ix_retention_sequences_company_status", "company_id", "status"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False, default=SequenceTriggerType.MANUAL.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SequenceStatus.DRAFT.value)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default=SequenceSource.MANUAL.value)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    steps: Mapped[list["RetentionSequenceStep"]] = relationship(
        back_populates="sequence",
        order_by="RetentionSequenceStep.step_order",
    )


class RetentionSequenceStep(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "retention_sequence_steps"
    __table_args__ = (
        UniqueConstraint("sequence_id", "step_order", name="uq_retention_sequence_steps_order"),
        Index("ix_retention_sequence_steps_sequence_order", "sequence_id", "step_order"),
    )

    sequence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("retention_sequences.id"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default=TouchpointChannel.EMAIL.value)
    offset_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("email_templates.id"), nullable=True)
    assignee_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    sequence: Mapped["RetentionSequence"] = relationship(back_populates="steps")


class RetentionEnrollment(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "retention_enrollments"
    __table_args__ = (Index("ix_retention_enrollments_company_status", "company_id", "status"),)

    sequence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("retention_sequences.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=EnrollmentStatus.ACTIVE.value)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    touchpoints: Mapped[list["Touchpoint"]] = relationship(back_populates="enrollment")


class Touchpoint(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "touchpoints"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "sequence_step_id", name="uq_touchpoints_enrollment_step"),
        Index("ix_touchpoints_scheduled_status", "scheduled_at", "status"),
    )

    enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("retention_enrollments.id"),
        nullable=True,
    )
    sequence_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("retention_sequence_steps.id"),
        nullable=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TouchpointStatus.SCHEDULED.value)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    enrollment: Mapped["RetentionEnrollment | None"] = relationship(back_populates="touchpoints")


class JobRun(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    __tablename__ = "job_runs"
    __table_args__ = (UniqueConstraint("job_name", "org_id", "run_date", name="uq_job_runs_name_org_date"),)

    job_name: Mapped[str] = mapped_column(String(128), nullable=False)
    run_date: Mapped[Date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
