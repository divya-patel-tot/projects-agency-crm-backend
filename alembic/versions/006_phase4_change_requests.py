"""Phase 4 change requests, attachments, and notifications."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_phase4_change_requests"
down_revision: Union[str, None] = "005_contacts_login_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RLS_TABLES = ("change_requests", "change_request_attachments", "notifications")


def upgrade() -> None:
    op.create_table(
        "change_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_contact_id", sa.UUID(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("impact_hours", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("impact_cost", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("impact_timeline_days", sa.Integer(), nullable=True),
        sa.Column("assessment_notes", sa.Text(), nullable=True),
        sa.Column("assigned_pm_id", sa.UUID(), nullable=True),
        sa.Column("requires_client_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_internal_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("revision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manager_escalation_flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("desired_due_date", sa.Date(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_pm_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["requested_by_contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_change_requests_org_id", "change_requests", ["org_id"])
    op.create_index("ix_change_requests_project_status", "change_requests", ["project_id", "status"])
    op.create_index("ix_change_requests_org_status", "change_requests", ["org_id", "status"])

    op.create_table(
        "change_request_attachments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("change_request_id", sa.UUID(), nullable=False),
        sa.Column("file_url", sa.String(length=2048), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["change_request_id"], ["change_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_change_request_attachments_org_id", "change_request_attachments", ["org_id"])
    op.create_index("ix_change_request_attachments_cr_id", "change_request_attachments", ["change_request_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("link", sa.String(length=2048), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_org_id", "notifications", ["org_id"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

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
    op.drop_table("notifications")
    op.drop_table("change_request_attachments")
    op.drop_table("change_requests")
