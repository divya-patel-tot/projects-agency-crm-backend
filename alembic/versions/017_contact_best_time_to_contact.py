"""Add best_time_to_contact to contacts."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_contact_best_time_to_contact"
down_revision: Union[str, None] = "016_merge_015_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("best_time_to_contact", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("contacts", "best_time_to_contact")
