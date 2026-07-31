"""Phase 7 — invoices, audit export, 2FA, GROQ CR assist, overdue invoice job."""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import AsyncSessionLocal, get_auth_db, get_tenant_db
from app.core.security import hash_password
from app.db.enums import ChangeRequestStatus, InvoiceStatus
from app.db.models.change_request import ChangeRequest
from app.db.models.company import Company
from app.db.models.organization import Organization
from app.db.models.project import Project
from app.db.models.user import User
from app.graphql.audit.service import activity_logs_to_csv, get_audit_logs
from app.graphql.auth.service import confirm_totp, enable_totp, login, verify_totp_login
from app.graphql.change_requests.ai_assist import draft_impact_assessment
from app.db.models.invoice import Invoice
from app.graphql.invoices.service import create_invoice_record, update_invoice_record
from app.scheduler.jobs import flag_overdue_invoices
from tests.credentials import fixture_password


async def _seed_phase7_fixture() -> dict:
    org_id = uuid.uuid4()
    company_id = uuid.uuid4()
    project_id = uuid.uuid4()
    user_id = uuid.uuid4()
    password = fixture_password()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_id, name="Phase7 Org", plan="trial", settings={}))

    async with get_tenant_db(org_id) as db:
        db.add(Company(id=company_id, org_id=org_id, name="Invoice Co", status="active"))
        db.add(
            User(
                id=user_id,
                org_id=org_id,
                name="Admin",
                email=f"admin-p7-{user_id.hex[:8]}@example.com",
                password_hash=hash_password(password),
                role="admin",
                status="active",
            )
        )
        db.add(
            Project(
                id=project_id,
                org_id=org_id,
                company_id=company_id,
                name="Billing Project",
                status="active",
            )
        )

    return {
        "org_id": org_id,
        "company_id": company_id,
        "project_id": project_id,
        "user_id": user_id,
        "password": password,
    }


@pytest.mark.asyncio
async def test_invoice_crud_and_overdue_job():
    data = await _seed_phase7_fixture()

    async with get_tenant_db(data["org_id"], user_id=data["user_id"], role="admin") as db:
        admin = await db.get(User, data["user_id"])
        invoice = await create_invoice_record(
            db,
            actor=admin,
            company_id=data["company_id"],
            amount=1500.0,
            due_date=date.today() - timedelta(days=3),
            project_id=data["project_id"],
            status=InvoiceStatus.SENT.value,
        )
        assert float(invoice.amount) == 1500.0

        updated = await update_invoice_record(
            db,
            actor=admin,
            invoice_id=invoice.id,
            status=InvoiceStatus.PAID.value,
        )
        assert updated.status == InvoiceStatus.PAID.value
        assert updated.paid_at == date.today()

    async with get_tenant_db(data["org_id"], user_id=data["user_id"], role="admin") as db:
        admin = await db.get(User, data["user_id"])
        overdue = await create_invoice_record(
            db,
            actor=admin,
            company_id=data["company_id"],
            amount=500.0,
            due_date=date.today() - timedelta(days=1),
            status=InvoiceStatus.SENT.value,
        )

    result = await flag_overdue_invoices(run_date=date.today())
    assert result["flagged"] >= 1

    async with get_tenant_db(data["org_id"]) as db:
        row = await db.get(Invoice, overdue.id)
        assert row.status == InvoiceStatus.OVERDUE.value


@pytest.mark.asyncio
async def test_activity_logs_and_csv_export():
    data = await _seed_phase7_fixture()

    async with get_tenant_db(data["org_id"], user_id=data["user_id"], role="admin") as db:
        admin = await db.get(User, data["user_id"])
        await create_invoice_record(
            db,
            actor=admin,
            company_id=data["company_id"],
            amount=99.0,
            due_date=date.today() + timedelta(days=30),
        )
        logs = await get_audit_logs(db, entity_type="invoice", limit=10)
        assert len(logs) >= 1
        csv_text = activity_logs_to_csv(logs)
        assert "entity_type" in csv_text.splitlines()[0]
        assert "invoice" in csv_text


@pytest.mark.asyncio
async def test_totp_enroll_confirm_and_login():
    data = await _seed_phase7_fixture()

    class FakeRequest:
        client = type("C", (), {"host": "127.0.0.1"})()

    request = FakeRequest()

    async with get_tenant_db(data["org_id"], user_id=data["user_id"], role="admin") as db:
        user = await db.get(User, data["user_id"])
        secret, _uri = await enable_totp(db, user)
        totp = pyotp.TOTP(secret)
        await confirm_totp(db, user, totp.now())

    async with get_auth_db() as db:
        user = await db.get(User, data["user_id"])
        result = await login(db, email=user.email, password=data["password"], request=request)
        assert result.requires_2fa is True
        assert result.challenge_token

        access, refresh = await verify_totp_login(
            db,
            challenge_token=result.challenge_token,
            code=totp.now(),
            request=request,
        )
        assert access
        assert refresh


@pytest.mark.asyncio
async def test_draft_impact_assessment_advisory_only():
    data = await _seed_phase7_fixture()
    cr_id = uuid.uuid4()

    async with get_tenant_db(data["org_id"]) as db:
        db.add(
            ChangeRequest(
                id=cr_id,
                org_id=data["org_id"],
                project_id=data["project_id"],
                company_id=data["company_id"],
                type="scope_addition",
                title="Add reporting module",
                description="Client wants weekly PDF reports",
                status=ChangeRequestStatus.UNDER_REVIEW.value,
            )
        )
        admin = await db.get(User, data["user_id"])

    groq_json = (
        '{"impact_hours": 12, "impact_cost": 2400, "impact_timeline_days": 14, '
        '"assessment_notes": "Advisory estimate for reporting scope."}'
    )
    with patch("app.graphql.change_requests.ai_assist.generate_text", new_callable=AsyncMock, return_value=groq_json):
        async with get_tenant_db(data["org_id"], user_id=data["user_id"], role="admin") as db:
            admin = await db.get(User, data["user_id"])
            draft = await draft_impact_assessment(db, actor=admin, cr_id=cr_id)
            assert draft is not None
            assert draft.advisory is True
            assert draft.impact_hours == 12.0
            assert draft.impact_cost == 2400.0

        async with get_tenant_db(data["org_id"]) as db:
            cr = await db.get(ChangeRequest, cr_id)
            assert cr.impact_hours is None
            assert cr.assessment_notes is None


@pytest.mark.asyncio
async def test_audit_csv_rest_route(client: AsyncClient, test_settings):
    data = await _seed_phase7_fixture()

    login_resp = await client.post(
        "/graphql",
        json={
            "query": """
                mutation Login($email: String!, $password: String!) {
                  login(email: $email, password: $password) { accessToken }
                }
            """,
            "variables": {"email": f"admin-p7-{data['user_id'].hex[:8]}@example.com", "password": data["password"]},
        },
    )
    token = login_resp.json()["data"]["login"]["accessToken"]

    async with get_tenant_db(data["org_id"], user_id=data["user_id"], role="admin") as db:
        admin = await db.get(User, data["user_id"])
        await create_invoice_record(
            db,
            actor=admin,
            company_id=data["company_id"],
            amount=10.0,
            due_date=date.today(),
        )

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/exports/audit.csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "entity_type" in resp.text


@pytest.mark.asyncio
async def test_non_admin_cannot_export_audit_csv():
    data = await _seed_phase7_fixture()
    member_id = uuid.uuid4()

    async with get_tenant_db(data["org_id"]) as db:
        db.add(
            User(
                id=member_id,
                org_id=data["org_id"],
                name="Member",
                email=f"member-p7-{member_id.hex[:8]}@example.com",
                password_hash=hash_password(fixture_password()),
                role="team_member",
                status="active",
            )
        )

    from app.core.security import create_access_token
    from app.main import create_app

    token = create_access_token(sub=member_id, org_id=data["org_id"], role="team_member")
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/exports/audit.csv", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
