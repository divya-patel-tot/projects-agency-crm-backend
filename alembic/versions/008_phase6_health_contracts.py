"""Phase 6 client health scores and contracts."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_phase6_health_contracts"
down_revision: Union[str, None] = "007_phase5_retention"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RLS_TABLES = ("client_health_scores", "contracts")


def upgrade() -> None:
    op.create_table(
        "client_health_scores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("factors", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_client_health_scores_org_id", "client_health_scores", ["org_id"])
    op.create_index("ix_client_health_scores_org_company", "client_health_scores", ["org_id", "company_id"])
    op.create_index("ix_client_health_scores_org_calculated", "client_health_scores", ["org_id", "calculated_at"])
    op.create_index("ix_client_health_scores_company_id", "client_health_scores", ["company_id"])

    op.create_table(
        "contracts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contracts_org_id", "contracts", ["org_id"])
    op.create_index("ix_contracts_org_company", "contracts", ["org_id", "company_id"])
    op.create_index("ix_contracts_org_status", "contracts", ["org_id", "status"])
    op.create_index("ix_contracts_end_date", "contracts", ["org_id", "end_date"])
    op.create_index("ix_contracts_company_id", "contracts", ["company_id"])

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

    op.drop_index("ix_contracts_company_id", table_name="contracts")
    op.drop_index("ix_contracts_end_date", table_name="contracts")
    op.drop_index("ix_contracts_org_status", table_name="contracts")
    op.drop_index("ix_contracts_org_company", table_name="contracts")
    op.drop_index("ix_contracts_org_id", table_name="contracts")
    op.drop_table("contracts")

    op.drop_index("ix_client_health_scores_company_id", table_name="client_health_scores")
    op.drop_index("ix_client_health_scores_org_calculated", table_name="client_health_scores")
    op.drop_index("ix_client_health_scores_org_company", table_name="client_health_scores")
    op.drop_index("ix_client_health_scores_org_id", table_name="client_health_scores")
    op.drop_table("client_health_scores")
