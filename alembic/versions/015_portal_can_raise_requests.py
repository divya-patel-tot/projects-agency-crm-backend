"""Backfill portal_can_raise_requests for existing portal contacts.

The column has existed since contacts got portal login, but nothing ever
read it, so it was always left at its default (False) regardless of what a
contact could actually do. Now that create_change_request/resubmit_change_request
enforce it, any contact who already has portal access needs the flag flipped
on too — otherwise everyone who could raise a request yesterday gets locked
out today, which is a regression, not a fix.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_portal_can_raise_requests"
down_revision: Union[str, None] = "014_project_contacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    org_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM organizations"))]
    for org_id in org_ids:
        conn.execute(sa.text("SELECT set_config('app.current_org_id', :oid, false)"), {"oid": str(org_id)})
        conn.execute(
            sa.text(
                """
                UPDATE contacts
                SET portal_can_raise_requests = true
                WHERE portal_access_enabled = true AND portal_can_raise_requests = false
                """
            )
        )


def downgrade() -> None:
    # Data backfill only — nothing structural to reverse, and reversing it
    # would re-introduce the regression this migration exists to avoid.
    pass
