import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, OrgScopedMixin, UUIDPrimaryKeyMixin


class ClientHealthScore(Base, UUIDPrimaryKeyMixin, OrgScopedMixin):
    """Append-only health score history per company."""

    __tablename__ = "client_health_scores"
    __table_args__ = (
        Index("ix_client_health_scores_org_company", "org_id", "company_id"),
        Index("ix_client_health_scores_org_calculated", "org_id", "calculated_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    score: Mapped[float] = mapped_column(Numeric(precision=5, scale=2), nullable=False)
    factors: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
