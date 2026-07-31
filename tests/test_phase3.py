import uuid
from pathlib import Path

import pytest
from graphql import GraphQLError

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, get_tenant_db
from app.core.security import ActorType, create_access_token, hash_password
from app.db.enums import ApprovalStatus, MilestoneStatus
from app.db.models.approval import Approval
from app.db.models.company import Company
from app.db.models.contact import Contact
from app.db.models.organization import Organization
from app.db.models.planning import Milestone, ProjectPhase
from app.db.models.project import Project
from app.graphql.approvals.service import approve_milestone, mark_milestone_ready_for_review, request_milestone_changes
from app.graphql.documents.service import confirm_upload, request_upload_url
from app.integrations import asset_storage


async def _seed_portal_fixture() -> dict:
    org_id = uuid.uuid4()
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    contact_a = uuid.uuid4()
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()
    phase_a = uuid.uuid4()
    milestone_a = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_id, name="Portal Org", plan="trial", settings={}))

    async with get_tenant_db(org_id) as db:
        db.add(Company(id=company_a, org_id=org_id, name="Company A", status="active"))
        db.add(Company(id=company_b, org_id=org_id, name="Company B", status="active"))
        db.add(
            Contact(
                id=contact_a,
                org_id=org_id,
                company_id=company_a,
                first_name="Portal",
                last_name="User",
                email="portal@example.com",
                portal_access_enabled=True,
                password_hash=hash_password("PortalPass123!"),
                status="active",
            )
        )
        db.add(
            Project(
                id=project_a,
                org_id=org_id,
                company_id=company_a,
                name="Project A",
                status="active",
            )
        )
        db.add(
            Project(
                id=project_b,
                org_id=org_id,
                company_id=company_b,
                name="Project B",
                status="active",
            )
        )
        db.add(
            ProjectPhase(
                id=phase_a,
                org_id=org_id,
                project_id=project_a,
                name="Phase 1",
                order_index=0,
                status="in_progress",
            )
        )
        db.add(
            Milestone(
                id=milestone_a,
                org_id=org_id,
                phase_id=phase_a,
                title="Deliverable 1",
                status=MilestoneStatus.IN_PROGRESS.value,
                order_index=0,
                requires_client_approval=True,
            )
        )

    return {
        "org_id": org_id,
        "company_a": company_a,
        "company_b": company_b,
        "contact_a": contact_a,
        "project_a": project_a,
        "project_b": project_b,
        "milestone_a": milestone_a,
    }


def _portal_token(data: dict) -> str:
    return create_access_token(
        sub=data["contact_a"],
        org_id=data["org_id"],
        company_id=data["company_a"],
        actor_type=ActorType.PORTAL,
    )


@pytest.mark.asyncio
async def test_portal_cannot_read_other_company_project():
    data = await _seed_portal_fixture()
    from app.graphql.portal.repository import get_project_for_company

    async with get_tenant_db(data["org_id"], user_id=data["contact_a"]) as db:
        row = await get_project_for_company(db, project_id=data["project_b"], company_id=data["company_a"])
        assert row is None


@pytest.mark.asyncio
async def test_portal_company_id_mismatch_rejected():
    data = await _seed_portal_fixture()
    from app.core.deps import GraphQLContext, enforce_portal_company_id

    ctx = GraphQLContext()
    ctx.contact = type("C", (), {"id": data["contact_a"]})()
    ctx.company_id = data["company_a"]
    ctx.actor_type = ActorType.PORTAL
    ctx.db = object()

    with pytest.raises(GraphQLError) as exc:
        enforce_portal_company_id(ctx, data["company_b"])
    assert exc.value.extensions["code"] == "authorization_error"


@pytest.mark.asyncio
async def test_milestone_approve_updates_both_rows():
    data = await _seed_portal_fixture()

    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        approval = await mark_milestone_ready_for_review(db, org_id=data["org_id"], milestone_id=data["milestone_a"])
        approval_id = approval.id

    async with get_tenant_db(data["org_id"], user_id=data["contact_a"]) as db:
        await approve_milestone(
            db,
            approval_id=approval_id,
            company_id=data["company_a"],
            contact_id=data["contact_a"],
        )
        saved_approval = await db.get(Approval, approval_id)
        milestone = await db.get(Milestone, data["milestone_a"])
        assert saved_approval.status == ApprovalStatus.APPROVED.value
        assert saved_approval.decided_at is not None
        assert milestone.status == MilestoneStatus.COMPLETED.value
        assert milestone.approved_at is not None


@pytest.mark.asyncio
async def test_milestone_request_changes_updates_both_rows():
    data = await _seed_portal_fixture()

    async with get_tenant_db(data["org_id"], role="project_manager") as db:
        approval = await mark_milestone_ready_for_review(db, org_id=data["org_id"], milestone_id=data["milestone_a"])
        approval_id = approval.id

    async with get_tenant_db(data["org_id"], user_id=data["contact_a"]) as db:
        await request_milestone_changes(
            db,
            approval_id=approval_id,
            company_id=data["company_a"],
            contact_id=data["contact_a"],
            comment="Needs revision",
        )
        saved_approval = await db.get(Approval, approval_id)
        milestone = await db.get(Milestone, data["milestone_a"])
        assert saved_approval.status == ApprovalStatus.REJECTED.value
        assert saved_approval.comment == "Needs revision"
        assert milestone.status == MilestoneStatus.IN_PROGRESS.value
        assert milestone.approved_at is None


@pytest.mark.asyncio
async def test_document_upload_version_increment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ASSETS_ROOT_PATH", str(tmp_path))
    get_settings.cache_clear()

    data = await _seed_portal_fixture()

    async with get_tenant_db(data["org_id"], user_id=data["contact_a"]) as db:
        result1 = await request_upload_url(
            db,
            org_id=data["org_id"],
            company_id=data["company_a"],
            actor_type=ActorType.PORTAL,
            entity_type="project",
            entity_id=data["project_a"],
            filename="spec.pdf",
            content_type="application/pdf",
            upload_base_url="http://test",
        )
        assert result1.upload_url == "http://test/assets/upload"
        assert result1.upload_token
        asset_storage.write_file(result1.file_url, b"pdf-v1")

        doc1 = await confirm_upload(
            db,
            org_id=data["org_id"],
            company_id=data["company_a"],
            actor_type=ActorType.PORTAL,
            actor_id=data["contact_a"],
            entity_type="project",
            entity_id=data["project_a"],
            file_url=result1.file_url,
        )

        result2 = await request_upload_url(
            db,
            org_id=data["org_id"],
            company_id=data["company_a"],
            actor_type=ActorType.PORTAL,
            entity_type="project",
            entity_id=data["project_a"],
            filename="spec-v2.pdf",
            content_type="application/pdf",
            upload_base_url="http://test",
        )
        asset_storage.write_file(result2.file_url, b"pdf-v2")

        doc2 = await confirm_upload(
            db,
            org_id=data["org_id"],
            company_id=data["company_a"],
            actor_type=ActorType.PORTAL,
            actor_id=data["contact_a"],
            entity_type="project",
            entity_id=data["project_a"],
            file_url=result2.file_url,
        )
        assert doc1.version == 1
        assert doc2.version == 2
        assert (tmp_path / result1.file_url.replace("/", "\\")).is_file()
