from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

    users: Mapped[list["User"]] = relationship(back_populates="organization")
