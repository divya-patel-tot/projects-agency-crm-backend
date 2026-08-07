"""Link tasks back to the change request they were created from."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_task_change_request_link"
down_revision: Union[str, None] = "019_align_model_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("change_request_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_change_request_id",
        "tasks",
        "change_requests",
        ["change_request_id"],
        ["id"],
    )
    op.create_index(
        "ix_tasks_change_request_id",
        "tasks",
        ["change_request_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_change_request_id", table_name="tasks", if_exists=True)
    op.drop_constraint("fk_tasks_change_request_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "change_request_id")
