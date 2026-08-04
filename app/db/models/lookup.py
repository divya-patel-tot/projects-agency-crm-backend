from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CompanySize(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Global reference list backing the company-size picker. Not org-scoped — same
    category as `organizations` (universal platform data, not per-tenant data)."""

    __tablename__ = "company_sizes"
    __table_args__ = (UniqueConstraint("label", name="uq_company_sizes_label"),)

    label: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Industry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Global reference list backing the industry picker. Not org-scoped."""

    __tablename__ = "industries"
    __table_args__ = (UniqueConstraint("name", name="uq_industries_name"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
