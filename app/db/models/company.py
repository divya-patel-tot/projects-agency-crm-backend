import uuid

from sqlalchemy import Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.enums import CompanyStatus
from app.db.models.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Company(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_org_status", "org_id", "status"),
        Index("ix_companies_org_company", "org_id", "id"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    website: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    size: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=CompanyStatus.LEAD.value)
    account_owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    health_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="company")
