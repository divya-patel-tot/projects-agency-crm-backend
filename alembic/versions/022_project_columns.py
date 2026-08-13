"""Per-project board columns — replaces the hardcoded 4-stage task-status
pipeline with real, project-owned, reorderable columns. Backfills every
existing project with the same 4 default columns (todo/in_progress/review/
done, done marked terminal) so existing task data resolves unchanged, and
defensively materializes a column for any stray task.status value that
doesn't match one of the 4 defaults (status has never had DB or schema-level
enum enforcement, so this is a real possibility, not just paranoia).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022_project_columns"
down_revision: Union[str, None] = "021_document_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_COLUMNS = [
    ("todo", "To do", 0, False),
    ("in_progress", "In progress", 1, False),
    ("review", "In review", 2, False),
    ("done", "Done", 3, True),
]


def _humanize(code: str) -> str:
    return " ".join(word.capitalize() for word in code.replace("-", "_").split("_")) or code


def upgrade() -> None:
    op.create_table(
        "project_columns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "code", name="uq_project_columns_project_code"),
    )
    op.create_index("ix_project_columns_org_id", "project_columns", ["org_id"])
    op.create_index("ix_project_columns_project_order", "project_columns", ["project_id", "order_index"])
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX ux_project_columns_one_terminal
              ON project_columns (project_id) WHERE is_terminal = true
            """
        )
    )

    op.execute(sa.text("ALTER TABLE project_columns ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE project_columns FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            """
            CREATE POLICY project_columns_tenant_isolation ON project_columns
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
            """
        )
    )

    # Backfill, per-org (every table involved is RLS-protected, so this has to
    # run per-org with app.current_org_id set — same pattern as 013).
    conn = op.get_bind()
    org_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM organizations"))]
    for org_id in org_ids:
        conn.execute(sa.text("SELECT set_config('app.current_org_id', :oid, false)"), {"oid": str(org_id)})

        # `Task.status` has always been written lowercase by the app layer
        # (`_normalize_task_updates`), but nothing ever enforced that at the
        # DB level — fold any historical mixed-case rows (e.g. "DONE") to
        # lowercase first, so they land on the real "done" column below
        # instead of spawning a spurious duplicate stray column.
        conn.execute(
            sa.text(
                "UPDATE tasks SET status = lower(status) WHERE deleted_at IS NULL AND status <> lower(status)"
            )
        )

        project_ids = [
            row[0] for row in conn.execute(sa.text("SELECT id FROM projects WHERE deleted_at IS NULL"))
        ]
        for project_id in project_ids:
            for code, label, order_index, is_terminal in DEFAULT_COLUMNS:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO project_columns
                            (id, org_id, project_id, code, label, order_index, is_terminal, created_at, updated_at)
                        VALUES
                            (gen_random_uuid(), :org_id, :project_id, :code, :label, :order_index, :is_terminal, now(), now())
                        ON CONFLICT (project_id, code) DO NOTHING
                        """
                    ),
                    {
                        "org_id": str(org_id),
                        "project_id": str(project_id),
                        "code": code,
                        "label": label,
                        "order_index": order_index,
                        "is_terminal": is_terminal,
                    },
                )

            # Defensive sweep: any task.status value that isn't one of the 4
            # defaults gets its own non-terminal column, inserted just before
            # "done" (which gets bumped from order_index 3 to 4).
            stray = conn.execute(
                sa.text(
                    """
                    SELECT DISTINCT status FROM tasks
                    WHERE project_id = :project_id
                      AND deleted_at IS NULL
                      AND status NOT IN ('todo', 'in_progress', 'review', 'done')
                    """
                ),
                {"project_id": str(project_id)},
            ).scalars().all()

            if stray:
                conn.execute(
                    sa.text(
                        "UPDATE project_columns SET order_index = 4 WHERE project_id = :project_id AND code = 'done'"
                    ),
                    {"project_id": str(project_id)},
                )
                for status_value in stray:
                    conn.execute(
                        sa.text(
                            """
                            INSERT INTO project_columns
                                (id, org_id, project_id, code, label, order_index, is_terminal, created_at, updated_at)
                            VALUES
                                (gen_random_uuid(), :org_id, :project_id, :code, :label, 3, false, now(), now())
                            ON CONFLICT (project_id, code) DO NOTHING
                            """
                        ),
                        {
                            "org_id": str(org_id),
                            "project_id": str(project_id),
                            "code": status_value,
                            "label": _humanize(status_value),
                        },
                    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS project_columns_tenant_isolation ON project_columns"))
    op.execute(sa.text("ALTER TABLE project_columns NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE project_columns DISABLE ROW LEVEL SECURITY"))
    op.drop_table("project_columns")
