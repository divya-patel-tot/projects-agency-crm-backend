"""Merge parallel 015 heads (portal_can_raise_requests + user_job_title)."""

from typing import Sequence, Union

revision: str = "016_merge_015_heads"
down_revision: Union[str, Sequence[str], None] = (
    "015_portal_can_raise_requests",
    "015_user_job_title",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
