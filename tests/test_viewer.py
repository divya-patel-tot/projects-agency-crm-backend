import pytest
from httpx import ASGITransport, AsyncClient

from tests.credentials import seed_admin_email, seed_admin_password


@pytest.mark.asyncio
async def test_me_requires_authentication():
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/graphql", json={"query": "{ me { id email scope } }"})
        body = resp.json()
        assert body["data"]["me"] is None


@pytest.mark.asyncio
async def test_me_returns_internal_viewer():
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_resp = await client.post(
            "/graphql",
            json={
                "query": """
                mutation Login($email: String!, $password: String!) {
                  login(email: $email, password: $password) { accessToken }
                }
                """,
                "variables": {"email": seed_admin_email(), "password": seed_admin_password()},
            },
        )
        access = login_resp.json()["data"]["login"]["accessToken"]
        assert access

        me_resp = await client.post(
            "/graphql",
            headers={"Authorization": f"Bearer {access}"},
            json={
                "query": """
                {
                  me {
                    id
                    email
                    scope
                    role
                    organization { id name plan }
                  }
                }
                """
            },
        )
        body = me_resp.json()
        assert "errors" not in body, body
        me = body["data"]["me"]
        assert me["scope"] == "INTERNAL"
        assert me["email"] == seed_admin_email()
        assert me["organization"]["name"]


@pytest.mark.asyncio
async def test_login_rejects_invalid_credentials():
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/graphql",
            json={
                "query": """
                mutation Login($email: String!, $password: String!) {
                  login(email: $email, password: $password) { accessToken }
                }
                """,
                "variables": {"email": seed_admin_email(), "password": "wrong-password-value"},
            },
        )
        body = resp.json()
        assert body.get("errors"), body
        assert body["data"] is None or body["data"]["login"] is None
