"""Align database indexes with SQLAlchemy model definitions."""

from typing import Sequence, Union

from alembic import op

revision: str = "019_align_model_indexes"
down_revision: Union[str, None] = "018_retention_sequence_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_change_request_attachments_cr_id", table_name="change_request_attachments", if_exists=True)
    op.create_index(
        "ix_change_request_attachments_change_request_id",
        "change_request_attachments",
        ["change_request_id"],
        unique=False,
        if_not_exists=True,
    )

    op.create_index(
        "ix_companies_org_company",
        "companies",
        ["org_id", "id"],
        unique=False,
        if_not_exists=True,
    )

    op.create_index(
        "ix_retention_sequence_steps_sequence_order",
        "retention_sequence_steps",
        ["sequence_id", "step_order"],
        unique=False,
        if_not_exists=True,
    )

    op.drop_index("ix_retention_sequences_trigger", table_name="retention_sequences", if_exists=True)


def downgrade() -> None:
    op.create_index(
        "ix_retention_sequences_trigger",
        "retention_sequences",
        ["org_id", "trigger_type", "is_active"],
        unique=False,
        if_not_exists=True,
    )

    op.drop_index(
        "ix_retention_sequence_steps_sequence_order",
        table_name="retention_sequence_steps",
        if_exists=True,
    )

    op.drop_index("ix_companies_org_company", table_name="companies", if_exists=True)

    op.drop_index(
        "ix_change_request_attachments_change_request_id",
        table_name="change_request_attachments",
        if_exists=True,
    )
    op.create_index(
        "ix_change_request_attachments_cr_id",
        "change_request_attachments",
        ["change_request_id"],
        unique=False,
        if_not_exists=True,
    )
