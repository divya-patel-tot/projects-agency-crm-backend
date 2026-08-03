"""User and contact notification preferences."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "010_user_contact_preferences"
down_revision: Union[str, None] = "009_phase7_invoices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferences", JSONB, nullable=True))
    op.add_column("contacts", sa.Column("preferences", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("contacts", "preferences")
    op.drop_column("users", "preferences")
