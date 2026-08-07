"""Retention sequence workflow: company link, status, approval, AI metadata, step messaging."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_retention_sequence_workflow"
down_revision: Union[str, None] = "017_contact_best_time_to_contact"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "retention_sequences",
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=True),
    )
    op.add_column("retention_sequences", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "retention_sequences",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
    )
    op.add_column(
        "retention_sequences",
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
    )
    op.add_column(
        "retention_sequences",
        sa.Column("created_by_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "retention_sequences",
        sa.Column("approved_by_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column("retention_sequences", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("retention_sequences", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("retention_sequences", sa.Column("ai_rationale", sa.Text(), nullable=True))

    op.add_column("retention_sequence_steps", sa.Column("name", sa.String(length=255), nullable=True))
    op.add_column("retention_sequence_steps", sa.Column("action_message", sa.Text(), nullable=True))

    op.create_index("ix_retention_sequences_company_status", "retention_sequences", ["company_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_retention_sequences_company_status", table_name="retention_sequences")
    op.drop_column("retention_sequence_steps", "action_message")
    op.drop_column("retention_sequence_steps", "name")
    op.drop_column("retention_sequences", "ai_rationale")
    op.drop_column("retention_sequences", "rejection_reason")
    op.drop_column("retention_sequences", "approved_at")
    op.drop_column("retention_sequences", "approved_by_id")
    op.drop_column("retention_sequences", "created_by_id")
    op.drop_column("retention_sequences", "source")
    op.drop_column("retention_sequences", "status")
    op.drop_column("retention_sequences", "description")
    op.drop_column("retention_sequences", "company_id")
