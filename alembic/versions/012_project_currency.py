"""Per-project currency, replacing the hardcoded GBP assumption in the frontend."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_project_currency"
down_revision: Union[str, None] = "011_lookup_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default backfills existing rows; dropped after so future inserts
    # rely on the ORM-level default (Project.currency), matching how `status`
    # and other enum-like columns on this table are handled.
    op.add_column(
        "projects",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'GBP'")),
    )
    op.alter_column("projects", "currency", server_default=None)


def downgrade() -> None:
    op.drop_column("projects", "currency")
