import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ProjectContact(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    """A client contact listed on a project's roster — who to reach out to.

    Purely informational: it does not gate what a contact can see in the
    client portal (that stays scoped to "all of their company's projects",
    unchanged), it just shows up in the project's Team tab.
    """

    __tablename__ = "project_contacts"
    __table_args__ = (UniqueConstraint("project_id", "contact_id", name="uq_project_contacts_project_contact"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False, index=True
    )
