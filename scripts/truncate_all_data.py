"""Empty every table's data while keeping the schema — run: python scripts/truncate_all_data.py

Truncates all tables in the public schema (except alembic_version, so migration
history stays intact) via a single TRUNCATE ... RESTART IDENTITY CASCADE.
RLS does not filter TRUNCATE, so this empties every row regardless of org.

Requires typing the database name to confirm.
"""

import asyncio

from sqlalchemy import text

from app.core.bootstrap import bootstrap_env

bootstrap_env()

from app.core.config import get_settings  # noqa: E402
from app.core.db import AsyncSessionLocal  # noqa: E402


async def main() -> None:
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "AND table_name != 'alembic_version'"
            )
        )
        tables = [row[0] for row in result.all()]

    if not tables:
        print("No tables found.")
        return

    print(f"About to TRUNCATE {len(tables)} tables on {settings.database_url_sync}:")
    for t in sorted(tables):
        print(f"  - {t}")

    confirm = input("\nType the database name to confirm: ")
    if confirm != settings.postgres_db:
        print("Confirmation did not match. Aborting.")
        return

    async with AsyncSessionLocal() as session:
        async with session.begin():
            table_list = ", ".join(f'"{t}"' for t in tables)
            await session.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))

    print("Done. All tables truncated.")


if __name__ == "__main__":
    asyncio.run(main())
