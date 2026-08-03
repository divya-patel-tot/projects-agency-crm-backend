"""Inspect row counts and sample rows — run: python scripts/inspect_db.py

Beekeeper note: users/companies use PostgreSQL RLS. Plain SELECT count(*)
returns 0 even when rows exist. See scripts/beekeeper_rls_queries.sql.
"""

import asyncio

from sqlalchemy import text

from app.core.bootstrap import bootstrap_env

bootstrap_env()

from app.core.db import AsyncSessionLocal  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as session:
        print("=== Row counts (Beekeeper sees this without RLS session vars) ===")
        for table in ("organizations", "users", "companies", "contacts", "refresh_tokens", "tags"):
            result = await session.execute(text(f"SELECT count(*) FROM {table}"))
            print(f"  {table}: {result.scalar()}")

        print("\n=== organizations (no RLS — always visible) ===")
        result = await session.execute(
            text("SELECT id, name, plan, created_at FROM organizations ORDER BY created_at DESC LIMIT 15")
        )
        for row in result.all():
            print(f"  {row}")

        print("\n=== users with auth_mode=login (how login lookup works) ===")
        await session.execute(text("SELECT set_config('app.auth_mode', 'login', true)"))
        result = await session.execute(
            text(
                "SELECT id, org_id, name, email, role, status, created_at "
                "FROM users ORDER BY created_at DESC LIMIT 15"
            )
        )
        rows = result.all()
        if not rows:
            print("  (no rows — RLS may still block; try as superuser)")
        for row in rows:
            print(f"  {row}")

        print("\n=== companies per org (need app.current_org_id) ===")
        orgs = await session.execute(text("SELECT id, name FROM organizations ORDER BY created_at DESC LIMIT 5"))
        for org_id, org_name in orgs.all():
            await session.execute(
                text("SELECT set_config('app.current_org_id', :oid, true)"),
                {"oid": str(org_id)},
            )
            result = await session.execute(
                text(
                    "SELECT id, name, status, created_at FROM companies "
                    "WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 5"
                )
            )
            company_rows = result.all()
            print(f"  Org {org_name} ({org_id}): {len(company_rows)} companies")
            for row in company_rows:
                print(f"    {row}")


if __name__ == "__main__":
    asyncio.run(main())
