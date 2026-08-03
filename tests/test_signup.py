import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import get_auth_db
from app.graphql.auth.repository import find_active_users_by_email


@pytest.mark.asyncio
async def test_signup_creates_org_and_returns_token():
    from app.main import create_app

    suffix = uuid.uuid4().hex[:8]
    email = f"signup-{suffix}@example.com"
    password = "SecurePass123!"

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/graphql",
            json={
                "query": """
                mutation Signup($organizationName: String!, $fullName: String!, $email: String!, $password: String!) {
                  signup(
                    organizationName: $organizationName
                    fullName: $fullName
                    email: $email
                    password: $password
                  ) {
                    accessToken
                    requires2fa
                  }
                }
                """,
                "variables": {
                    "organizationName": f"Agency {suffix}",
                    "fullName": "Test Admin",
                    "email": email,
                    "password": password,
                },
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "errors" not in body, body
        assert body["data"]["signup"]["accessToken"]
        assert body["data"]["signup"]["requires2fa"] is False

    async with get_auth_db() as db:
        users = await find_active_users_by_email(db, email)
        assert len(users) == 1
        assert users[0].role == "admin"
