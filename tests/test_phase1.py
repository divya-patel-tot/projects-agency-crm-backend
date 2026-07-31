import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, get_tenant_db
from app.db.models.company import Company
from app.db.models.contact import Contact
from app.db.models.organization import Organization


@pytest.mark.asyncio
async def test_login_and_refresh_flow():
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_resp = await client.post(
            "/graphql",
            json={
                "query": """
                mutation Login($email: String!, $password: String!) {
                  login(email: $email, password: $password) {
                    accessToken
                    requires2fa
                  }
                }
                """,
                "variables": {"email": "admin@example.com", "password": "ChangeMe123!"},
            },
        )
        assert login_resp.status_code == 200
        body = login_resp.json()
        assert "errors" not in body, body
        access = body["data"]["login"]["accessToken"]
        assert access

        refresh_resp = await client.post(
            "/graphql",
            json={"query": "mutation { refreshToken { accessToken } }"},
        )
        assert refresh_resp.status_code == 200
        refresh_body = refresh_resp.json()
        assert "errors" not in refresh_body, refresh_body
        assert refresh_body["data"]["refreshToken"]["accessToken"]

        authed = await client.post(
            "/graphql",
            headers={"Authorization": f"Bearer {access}"},
            json={"query": "{ companies { id name } }"},
        )
        assert authed.status_code == 200
        assert "errors" not in authed.json()


@pytest.mark.asyncio
async def test_rls_isolation_between_orgs():
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    company_a_id = uuid.uuid4()
    company_b_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_a, name="Org A", plan="trial", settings={}))
            session.add(Organization(id=org_b, name="Org B", plan="trial", settings={}))

    async with get_tenant_db(org_a) as db:
        db.add(Company(id=company_a_id, org_id=org_a, name="Company A", status="active"))

    async with get_tenant_db(org_b) as db:
        db.add(Company(id=company_b_id, org_id=org_b, name="Company B", status="active"))

    async with get_tenant_db(org_a) as db:
        result = await db.execute(select(Company).where(Company.deleted_at.is_(None)))
        names = {row.name for row in result.scalars().all()}
        assert "Company A" in names
        assert "Company B" not in names


@pytest.mark.asyncio
async def test_primary_contact_uniqueness():
    org_id = uuid.uuid4()
    company_id = uuid.uuid4()
    c2_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_id, name="Primary Org", plan="trial", settings={}))

    async with get_tenant_db(org_id) as db:
        db.add(Company(id=company_id, org_id=org_id, name="Primary Co", status="active"))
        db.add(
            Contact(
                id=uuid.uuid4(),
                org_id=org_id,
                company_id=company_id,
                first_name="A",
                last_name="One",
                is_primary=True,
                status="active",
            )
        )
        c2 = Contact(
            id=c2_id,
            org_id=org_id,
            company_id=company_id,
            first_name="B",
            last_name="Two",
            is_primary=False,
            status="active",
        )
        db.add(c2)
        await db.flush()
        from app.graphql.contacts.repository import unset_primary_for_company

        await unset_primary_for_company(db, company_id, exclude_id=c2_id)
        c2.is_primary = True
        await db.flush()
        result = await db.execute(
            select(Contact).where(
                Contact.company_id == company_id,
                Contact.is_primary.is_(True),
                Contact.deleted_at.is_(None),
            )
        )
        primaries = list(result.scalars().all())
        assert len(primaries) == 1
        assert primaries[0].first_name == "B"
