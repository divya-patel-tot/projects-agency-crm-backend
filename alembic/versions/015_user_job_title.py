"""Optional delivery discipline for team members (designer, developer, qa)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_user_job_title"
down_revision: Union[str, None] = "014_project_contacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("job_title", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "job_title")
