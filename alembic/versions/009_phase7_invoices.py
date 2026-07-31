"""Phase 7 invoices module."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_phase7_invoices"
down_revision: Union[str, None] = "008_phase6_health_contracts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RLS_TABLES = ("invoices",)


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("invoice_number", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column("paid_at", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoices_org_id", "invoices", ["org_id"])
    op.create_index("ix_invoices_org_company", "invoices", ["org_id", "company_id"])
    op.create_index("ix_invoices_org_status", "invoices", ["org_id", "status"])
    op.create_index("ix_invoices_due_date", "invoices", ["org_id", "due_date"])
    op.create_index("ix_invoices_company_id", "invoices", ["company_id"])
    op.create_index("ix_invoices_project_id", "invoices", ["project_id"])

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (org_id = current_setting('app.current_org_id')::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id')::uuid)
            """
        )


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_invoices_project_id", table_name="invoices")
    op.drop_index("ix_invoices_company_id", table_name="invoices")
    op.drop_index("ix_invoices_due_date", table_name="invoices")
    op.drop_index("ix_invoices_org_status", table_name="invoices")
    op.drop_index("ix_invoices_org_company", table_name="invoices")
    op.drop_index("ix_invoices_org_id", table_name="invoices")
    op.drop_table("invoices")
