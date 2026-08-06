"""Project client-contact roster — who the client-side point of contact is
for a project. Purely informational: it does not change what a contact can
see in the client portal (still scoped to "all of their company's
projects"), it just shows up in the project's Team tab.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_project_contacts"
down_revision: Union[str, None] = "013_project_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_contacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "contact_id", name="uq_project_contacts_project_contact"),
    )
    op.create_index("ix_project_contacts_org_id", "project_contacts", ["org_id"])
    op.create_index("ix_project_contacts_project_id", "project_contacts", ["project_id"])
    op.create_index("ix_project_contacts_contact_id", "project_contacts", ["contact_id"])

    op.execute(sa.text("ALTER TABLE project_contacts ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE project_contacts FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            """
            CREATE POLICY project_contacts_tenant_isolation ON project_contacts
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS project_contacts_tenant_isolation ON project_contacts"))
    op.execute(sa.text("ALTER TABLE project_contacts NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE project_contacts DISABLE ROW LEVEL SECURITY"))
    op.drop_table("project_contacts")
