"""Allow portal login to resolve contacts under auth_mode (mirrors users RLS)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_contacts_login_rls"
down_revision: Union[str, None] = "004_phase3_portal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS contacts_tenant_isolation ON contacts"))
    op.execute(
        sa.text(
            """
            CREATE POLICY contacts_tenant_isolation ON contacts
            USING (
                current_setting('app.auth_mode', true) = 'login'
                OR org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
            )
            WITH CHECK (
                org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS contacts_tenant_isolation ON contacts"))
    op.execute(
        sa.text(
            """
            CREATE POLICY contacts_tenant_isolation ON contacts
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            """
        )
    )
