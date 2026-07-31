"""Phase 5 retention sequences, enrollments, touchpoints, job runs."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_phase5_retention"
down_revision: Union[str, None] = "006_phase4_change_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RLS_TABLES = (
    "email_templates",
    "retention_sequences",
    "retention_sequence_steps",
    "retention_enrollments",
    "touchpoints",
    "job_runs",
)


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_templates_org_id", "email_templates", ["org_id"])

    op.create_table(
        "retention_sequences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_retention_sequences_org_id", "retention_sequences", ["org_id"])
    op.create_index("ix_retention_sequences_trigger", "retention_sequences", ["org_id", "trigger_type", "is_active"])

    op.create_table(
        "retention_sequence_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("sequence_id", sa.UUID(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("offset_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("assignee_role", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["sequence_id"], ["retention_sequences.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["email_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sequence_id", "step_order", name="uq_retention_sequence_steps_order"),
    )
    op.create_index("ix_retention_sequence_steps_org_id", "retention_sequence_steps", ["org_id"])

    op.create_table(
        "retention_enrollments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("sequence_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["sequence_id"], ["retention_sequences.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_retention_enrollments_org_id", "retention_enrollments", ["org_id"])
    op.create_index("ix_retention_enrollments_company_status", "retention_enrollments", ["company_id", "status"])

    op.create_table(
        "touchpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("enrollment_id", sa.UUID(), nullable=True),
        sa.Column("sequence_step_id", sa.UUID(), nullable=True),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["enrollment_id"], ["retention_enrollments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["sequence_step_id"], ["retention_sequence_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enrollment_id", "sequence_step_id", name="uq_touchpoints_enrollment_step"),
    )
    op.create_index("ix_touchpoints_org_id", "touchpoints", ["org_id"])
    op.create_index("ix_touchpoints_scheduled_status", "touchpoints", ["scheduled_at", "status"])

    op.create_table(
        "job_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_name", "org_id", "run_date", name="uq_job_runs_name_org_date"),
    )
    op.create_index("ix_job_runs_org_id", "job_runs", ["org_id"])

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
    op.drop_table("job_runs")
    op.drop_table("touchpoints")
    op.drop_table("retention_enrollments")
    op.drop_table("retention_sequence_steps")
    op.drop_table("retention_sequences")
    op.drop_table("email_templates")
