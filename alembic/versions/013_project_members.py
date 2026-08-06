"""Project membership — who's on a project's delivery team, and the basis for
scoping a team member's visibility to only the projects (and clients) they're
actually assigned to.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_project_members"
down_revision: Union[str, None] = "012_project_currency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )
    op.create_index("ix_project_members_org_id", "project_members", ["org_id"])
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])

    op.execute(sa.text("ALTER TABLE project_members ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE project_members FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            """
            CREATE POLICY project_members_tenant_isolation ON project_members
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            """
        )
    )

    # Backfill so nobody's project visibility regresses the moment this table
    # starts being enforced: everyone already assigned a task on a project, or
    # set as its project manager, becomes a member of that project. Every
    # table involved is RLS-protected, so the backfill has to run per-org with
    # app.current_org_id set — an unscoped INSERT...SELECT would silently see
    # zero source rows and insert nothing.
    conn = op.get_bind()
    org_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM organizations"))]
    for org_id in org_ids:
        conn.execute(sa.text("SELECT set_config('app.current_org_id', :oid, false)"), {"oid": str(org_id)})
        conn.execute(
            sa.text(
                """
                INSERT INTO project_members (id, org_id, project_id, user_id, created_at, updated_at)
                SELECT gen_random_uuid(), t.org_id, t.project_id, t.assignee_id, now(), now()
                FROM tasks t
                WHERE t.assignee_id IS NOT NULL
                ON CONFLICT (project_id, user_id) DO NOTHING
                """
            )
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO project_members (id, org_id, project_id, user_id, created_at, updated_at)
                SELECT gen_random_uuid(), p.org_id, p.id, p.project_manager_id, now(), now()
                FROM projects p
                WHERE p.project_manager_id IS NOT NULL
                ON CONFLICT (project_id, user_id) DO NOTHING
                """
            )
        )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS project_members_tenant_isolation ON project_members"))
    op.execute(sa.text("ALTER TABLE project_members NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE project_members DISABLE ROW LEVEL SECURITY"))
    op.drop_table("project_members")
