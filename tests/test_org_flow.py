import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from tests.credentials import fixture_password, seed_admin_email, seed_admin_password


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/graphql",
        json={
            "query": """
            mutation Login($email: String!, $password: String!) {
              login(email: $email, password: $password) { accessToken }
            }
            """,
            "variables": {"email": email, "password": password},
        },
    )
    body = resp.json()
    assert "errors" not in body, body
    return body["data"]["login"]["accessToken"]


async def _gql(client: AsyncClient, query: str, *, token: str | None = None, variables: dict | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = await client.post(
        "/graphql",
        headers=headers,
        json={"query": query, "variables": variables or {}},
    )
    return resp.json()


@pytest.mark.asyncio
async def test_admin_invites_pm_creates_company_contact_project_portal_sees_it():
    from app.main import create_app

    suffix = uuid.uuid4().hex[:8]
    pm_email = f"pm-{suffix}@example.com"
    client_email = f"client-{suffix}@example.com"
    portal_password = fixture_password()
    company_name = f"Client Co {suffix}"
    project_name = f"Portal Project {suffix}"

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await _login(client, seed_admin_email(), seed_admin_password())

        invite = await _gql(
            client,
            """
            mutation Invite($name: String!, $email: String!, $password: String!, $role: String!) {
              createUser(name: $name, email: $email, password: $password, role: $role) {
                id email role status
              }
            }
            """,
            token=admin_token,
            variables={
                "name": "Project Manager",
                "email": pm_email,
                "password": fixture_password(),
                "role": "project_manager",
            },
        )
        assert "errors" not in invite, invite
        assert invite["data"]["createUser"]["role"] == "project_manager"

        pm_token = await _login(client, pm_email, fixture_password())

        company = await _gql(
            client,
            """
            mutation CreateCo($name: String!) {
              createCompany(name: $name, status: "active") { id name }
            }
            """,
            token=admin_token,
            variables={"name": company_name},
        )
        assert "errors" not in company, company
        company_id = company["data"]["createCompany"]["id"]

        contact = await _gql(
            client,
            """
            mutation CreateContact(
              $companyId: ID!
              $firstName: String!
              $lastName: String!
              $email: String!
              $portalAccessEnabled: Boolean!
              $portalPassword: String!
            ) {
              createContact(
                companyId: $companyId
                firstName: $firstName
                lastName: $lastName
                email: $email
                isPrimary: true
                portalAccessEnabled: $portalAccessEnabled
                portalPassword: $portalPassword
                status: "active"
              ) { id email portalAccessEnabled }
            }
            """,
            token=admin_token,
            variables={
                "companyId": company_id,
                "firstName": "Client",
                "lastName": "User",
                "email": client_email,
                "portalAccessEnabled": True,
                "portalPassword": portal_password,
            },
        )
        assert "errors" not in contact, contact

        project = await _gql(
            client,
            """
            mutation CreateProject($companyId: ID!, $name: String!) {
              createProject(companyId: $companyId, name: $name, status: "active") {
                id name companyId
              }
            }
            """,
            token=pm_token,
            variables={"companyId": company_id, "name": project_name},
        )
        assert "errors" not in project, project

        portal_login = await _gql(
            client,
            """
            mutation PortalLogin($email: String!, $password: String!) {
              portalLogin(email: $email, password: $password) { accessToken }
            }
            """,
            variables={"email": client_email, "password": portal_password},
        )
        assert "errors" not in portal_login, portal_login
        portal_token = portal_login["data"]["portalLogin"]["accessToken"]

        portal_projects = await _gql(
            client,
            """
            query { portalProjects { id name } }
            """,
            token=portal_token,
        )
        assert "errors" not in portal_projects, portal_projects
        names = [row["name"] for row in portal_projects["data"]["portalProjects"]]
        assert project_name in names


@pytest.mark.asyncio
async def test_portal_login_is_case_insensitive_for_contact_email():
    from app.main import create_app

    suffix = uuid.uuid4().hex[:8]
    client_email = f"Client.Mixed.{suffix}@Example.COM"
    portal_password = fixture_password()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await _login(client, seed_admin_email(), seed_admin_password())

        company = await _gql(
            client,
            """
            mutation CreateCo($name: String!) {
              createCompany(name: $name, status: "active") { id }
            }
            """,
            token=admin_token,
            variables={"name": f"Mixed Case Co {suffix}"},
        )
        company_id = company["data"]["createCompany"]["id"]

        contact = await _gql(
            client,
            """
            mutation CreateContact(
              $companyId: ID!
              $email: String!
              $portalAccessEnabled: Boolean!
              $portalPassword: String!
            ) {
              createContact(
                companyId: $companyId
                firstName: "Case"
                lastName: "Test"
                email: $email
                isPrimary: true
                portalAccessEnabled: $portalAccessEnabled
                portalPassword: $portalPassword
                status: "active"
              ) { id email portalAccessEnabled }
            }
            """,
            token=admin_token,
            variables={
                "companyId": company_id,
                "email": client_email,
                "portalAccessEnabled": True,
                "portalPassword": portal_password,
            },
        )
        assert "errors" not in contact, contact

        portal_login = await _gql(
            client,
            """
            mutation PortalLogin($email: String!, $password: String!) {
              portalLogin(email: $email, password: $password) { accessToken }
            }
            """,
            variables={
                "email": client_email.upper(),
                "password": portal_password,
            },
        )
        assert "errors" not in portal_login, portal_login
        assert portal_login["data"]["portalLogin"]["accessToken"]


@pytest.mark.asyncio
async def test_team_member_cannot_create_company():
    from app.main import create_app

    suffix = uuid.uuid4().hex[:8]
    member_email = f"member-{suffix}@example.com"

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await _login(client, seed_admin_email(), seed_admin_password())

        invite = await _gql(
            client,
            """
            mutation Invite($name: String!, $email: String!, $password: String!, $role: String!) {
              createUser(name: $name, email: $email, password: $password, role: $role) { id }
            }
            """,
            token=admin_token,
            variables={
                "name": "Team Member",
                "email": member_email,
                "password": fixture_password(),
                "role": "team_member",
            },
        )
        assert "errors" not in invite, invite

        member_token = await _login(client, member_email, fixture_password())
        denied = await _gql(
            client,
            """
            mutation { createCompany(name: "Blocked Co", status: "active") { id } }
            """,
            token=member_token,
        )
        assert denied.get("errors"), denied
        assert denied["errors"][0]["extensions"]["code"] == "authorization_error"


@pytest.mark.asyncio
async def test_portal_password_required_when_enabling_access():
    from app.main import create_app

    suffix = uuid.uuid4().hex[:8]

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_token = await _login(client, seed_admin_email(), seed_admin_password())

        company = await _gql(
            client,
            """
            mutation { createCompany(name: "No Portal PW Co", status: "active") { id } }
            """,
            token=admin_token,
        )
        company_id = company["data"]["createCompany"]["id"]

        blocked = await _gql(
            client,
            """
            mutation CreateContact($companyId: ID!) {
              createContact(
                companyId: $companyId
                firstName: "A"
                lastName: "B"
                email: "nopw@example.com"
                isPrimary: false
                portalAccessEnabled: true
                status: "active"
              ) { id }
            }
            """,
            token=admin_token,
            variables={"companyId": company_id},
        )
        assert blocked.get("errors"), blocked
        assert blocked["errors"][0]["extensions"]["code"] == "bad_user_input"
