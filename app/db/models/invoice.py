import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.enums import InvoiceStatus
from app.db.models.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Invoice(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_org_company", "org_id", "company_id"),
        Index("ix_invoices_org_status", "org_id", "status"),
        Index("ix_invoices_due_date", "org_id", "due_date"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=True,
        index=True,
    )
    invoice_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(precision=14, scale=2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=InvoiceStatus.DRAFT.value)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
