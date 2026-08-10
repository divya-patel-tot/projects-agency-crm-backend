"""Inspect org/companies/projects for retention seeding."""

import asyncio

from sqlalchemy import text

from app.core.bootstrap import bootstrap_env

bootstrap_env()

from app.core.db import AsyncSessionLocal  # noqa: E402


async def main() -> None:
    email = "divyeshgohil123@gmail.com"
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT set_config('app.auth_mode', 'login', true)"))
        result = await session.execute(
            text(
                """
                SELECT u.id, u.org_id, u.name, u.email, u.role, o.name AS org_name
                FROM users u
                JOIN organizations o ON o.id = u.org_id
                WHERE lower(u.email) = lower(:email)
                """
            ),
            {"email": email},
        )
        user = result.first()
        if not user:
            print(f"User not found: {email}")
            return

        user_id, org_id, user_name, user_email, role, org_name = user
        print(f"User: {user_name} ({user_email}) role={role}")
        print(f"Org:  {org_name} ({org_id})")

        await session.execute(
            text("SELECT set_config('app.current_org_id', :oid, true)"),
            {"oid": str(org_id)},
        )

        companies = await session.execute(
            text(
                """
                SELECT id, name, status, health_score, industry
                FROM companies
                WHERE deleted_at IS NULL
                ORDER BY name
                """
            )
        )
        print("\n=== Companies ===")
        for row in companies.all():
            print(f"  {row}")

        projects = await session.execute(
            text(
                """
                SELECT p.id, c.name AS company, p.name, p.status, p.health,
                       p.budget, p.actual_cost, p.start_date, p.end_date
                FROM projects p
                JOIN companies c ON c.id = p.company_id
                WHERE p.deleted_at IS NULL
                ORDER BY c.name, p.name
                """
            )
        )
        print("\n=== Projects ===")
        for row in projects.all():
            print(f"  {row}")

        contacts = await session.execute(
            text(
                """
                SELECT co.id, c.name AS company, co.first_name, co.last_name,
                       co.is_primary, co.email, co.phone
                FROM contacts co
                JOIN companies c ON c.id = co.company_id
                WHERE co.deleted_at IS NULL
                ORDER BY c.name, co.is_primary DESC
                """
            )
        )
        print("\n=== Contacts ===")
        for row in contacts.all():
            print(f"  {row}")

        sequences = await session.execute(
            text(
                """
                SELECT id, name, status, trigger_type, company_id, is_active
                FROM retention_sequences
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
        )
        print("\n=== Retention sequences ===")
        for row in sequences.all():
            print(f"  {row}")


if __name__ == "__main__":
    asyncio.run(main())
