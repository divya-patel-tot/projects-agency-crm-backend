"""Add rich metadata fields to documents for professional viewer."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021_document_metadata"
down_revision: Union[str, None] = "020_task_change_request_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("filename", sa.String(length=512), nullable=True))
    op.add_column("documents", sa.Column("content_type", sa.String(length=128), nullable=True))
    op.add_column("documents", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("encoding", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("thumbnail_path", sa.String(length=2048), nullable=True))
    op.add_column("documents", sa.Column("preview_path", sa.String(length=2048), nullable=True))
    op.add_column(
        "documents",
        sa.Column("preview_status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column("documents", sa.Column("category", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("checksum_sha256", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("line_count", sa.Integer(), nullable=True))

    # RLS blocks updates when app.current_org_id is unset (Alembic runs without tenant context).
    op.execute("ALTER TABLE documents DISABLE ROW LEVEL SECURITY")

    op.execute(
        """
        UPDATE documents
        SET filename = CASE
            WHEN file_url IS NULL OR btrim(file_url) = '' THEN 'document'
            ELSE COALESCE(
                NULLIF(
                    regexp_replace(
                        split_part(
                            replace(file_url, '\\', '/'),
                            '/',
                            GREATEST(array_length(string_to_array(replace(file_url, '\\', '/'), '/'), 1), 1)
                        ),
                        '^[^_]+_',
                        ''
                    ),
                    ''
                ),
                NULLIF(
                    split_part(
                        replace(file_url, '\\', '/'),
                        '/',
                        GREATEST(array_length(string_to_array(replace(file_url, '\\', '/'), '/'), 1), 1)
                    ),
                    ''
                ),
                'document'
            )
        END,
        preview_status = COALESCE(preview_status, 'pending'),
        content_type = COALESCE(content_type, 'application/octet-stream'),
        size_bytes = COALESCE(size_bytes, 0)
        """
    )

    op.execute("UPDATE documents SET filename = 'document' WHERE filename IS NULL OR btrim(filename) = ''")

    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")

    op.alter_column("documents", "filename", nullable=False)
    op.alter_column("documents", "content_type", nullable=False)
    op.alter_column("documents", "size_bytes", nullable=False)


def downgrade() -> None:
    op.drop_column("documents", "line_count")
    op.drop_column("documents", "checksum_sha256")
    op.drop_column("documents", "category")
    op.drop_column("documents", "preview_status")
    op.drop_column("documents", "preview_path")
    op.drop_column("documents", "thumbnail_path")
    op.drop_column("documents", "encoding")
    op.drop_column("documents", "size_bytes")
    op.drop_column("documents", "content_type")
    op.drop_column("documents", "filename")
