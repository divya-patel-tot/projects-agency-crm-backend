"""Verify documents table schema and metadata integrity."""

from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url_sync)
    insp = inspect(engine)
    cols = sorted(c["name"] for c in insp.get_columns("documents"))
    expected = {
        "id",
        "org_id",
        "entity_type",
        "entity_id",
        "file_url",
        "filename",
        "content_type",
        "size_bytes",
        "encoding",
        "thumbnail_path",
        "preview_path",
        "preview_status",
        "category",
        "checksum_sha256",
        "line_count",
        "version",
        "uploaded_by",
        "uploaded_by_actor_type",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    missing = expected - set(cols)
    extra = set(cols) - expected

    with engine.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        total = conn.execute(text("SELECT COUNT(*) FROM documents")).scalar()
        active = conn.execute(
            text("SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL")
        ).scalar()
        null_meta = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM documents
                WHERE deleted_at IS NULL
                  AND (
                    filename IS NULL
                    OR content_type IS NULL
                    OR size_bytes IS NULL
                    OR preview_status IS NULL
                  )
                """
            )
        ).scalar()

    print("alembic_version:", rev)
    print("documents columns:", cols)
    print("missing expected columns:", sorted(missing) or "none")
    print("unexpected columns:", sorted(extra) or "none")
    print("total documents:", total)
    print("active documents:", active)
    print("active rows with null metadata:", null_meta)
    if missing or null_meta:
        raise SystemExit(1)
    print("OK")


if __name__ == "__main__":
    main()
