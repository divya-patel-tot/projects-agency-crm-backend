import pytest
from httpx import ASGITransport, AsyncClient

from tests.credentials import seed_admin_email, seed_admin_password


@pytest.mark.asyncio
async def test_users_query_requires_auth():
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/graphql", json={"query": "{ users { id email } }"})
        body = resp.json()
        assert body.get("errors"), body


@pytest.mark.asyncio
async def test_users_query_returns_org_members():
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/graphql",
            json={
                "query": "mutation Login($email: String!, $password: String!) { login(email: $email, password: $password) { accessToken } }",
                "variables": {"email": seed_admin_email(), "password": seed_admin_password()},
            },
        )
        token = login.json()["data"]["login"]["accessToken"]
        resp = await client.post(
            "/graphql",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "{ users { id email name role } }"},
        )
        body = resp.json()
        assert "errors" not in body, body
        assert len(body["data"]["users"]) >= 1
