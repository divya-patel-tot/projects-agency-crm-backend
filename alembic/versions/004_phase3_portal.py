"""Phase 3 portal auth, approvals, and documents."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_phase3_portal"
down_revision: Union[str, None] = "003_phase2_projects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RLS_TABLES = ("approvals", "documents")


def upgrade() -> None:
    op.add_column("contacts", sa.Column("password_hash", sa.String(length=512), nullable=True))
    op.add_column(
        "contacts",
        sa.Column("portal_can_raise_requests", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("approver_type", sa.String(length=32), nullable=False),
        sa.Column("approver_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_org_id", "approvals", ["org_id"])
    op.create_index("ix_approvals_entity_id", "approvals", ["entity_id"])
    op.create_index("ix_approvals_entity", "approvals", ["entity_type", "entity_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("file_url", sa.String(length=2048), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("uploaded_by_actor_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_org_id", "documents", ["org_id"])
    op.create_index("ix_documents_entity_id", "documents", ["entity_id"])
    op.create_index("ix_documents_entity_version", "documents", ["entity_type", "entity_id", "version"])

    for table in RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"""
                CREATE POLICY {table}_tenant_isolation ON {table}
                USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
                WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
                """
            )
        )


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

    op.drop_table("documents")
    op.drop_table("approvals")
    op.drop_column("contacts", "portal_can_raise_requests")
    op.drop_column("contacts", "password_hash")
