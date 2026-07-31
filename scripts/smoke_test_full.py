#!/usr/bin/env python3
"""
End-to-end smoke test for Phases 0–7.

Creates an isolated org, exercises CRUD + portal + approvals + documents +
change requests (positive and negative security cases),
then deletes all smoke-test data from the database and shared asset folder.

Usage:
    cd backend
    .\\venv\\Scripts\\python scripts\\smoke_test_full.py

Optional:
    SMOKE_BASE_URL=http://127.0.0.1:8000   # use live server (default: in-process ASGI)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.bootstrap import bootstrap_env
from app.core.env_file import require_env

bootstrap_env()

RUN_ID = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
SMOKE_MARKER = f"SMOKE_{RUN_ID}"
ADMIN_EMAIL = f"smoke-admin-{RUN_ID}@test.local"
ADMIN_PASSWORD = require_env("SMOKE_ADMIN_PASSWORD")
PORTAL_EMAIL = f"smoke-portal-{RUN_ID}@test.local"
PORTAL_PASSWORD = require_env("SMOKE_PORTAL_PASSWORD")
SMOKE_MEMBER_PASSWORD = require_env("SMOKE_MEMBER_PASSWORD")
ORG_NAME = f"Smoke Test Org {RUN_ID}"


@dataclass
class StepResult:
    category: str
    name: str
    status: Literal["PASS", "FAIL", "WARN", "SKIP"]
    detail: str = ""


@dataclass
class SmokeReport:
    run_id: str = RUN_ID
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    org_id: str | None = None
    steps: list[StepResult] = field(default_factory=list)

    def add(self, category: str, name: str, status: Literal["PASS", "FAIL", "WARN", "SKIP"], detail: str = "") -> None:
        self.steps.append(StepResult(category, name, status, detail))
        icon = {"PASS": "+", "FAIL": "X", "WARN": "!", "SKIP": "-"}[status]
        line = f"[{icon}] {category} / {name}"
        if detail:
            line += f" — {detail}"
        print(line)

    @property
    def passed(self) -> int:
        return sum(1 for s in self.steps if s.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for s in self.steps if s.status == "FAIL")

    @property
    def warned(self) -> int:
        return sum(1 for s in self.steps if s.status == "WARN")


class SmokeFailure(Exception):
    pass


def _gql_errors(payload: dict) -> list[dict]:
    return payload.get("errors") or []


async def gql(
    client: httpx.AsyncClient,
    query: str,
    *,
    variables: dict | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = await client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )
    response.raise_for_status()
    payload = response.json()
    if errors := _gql_errors(payload):
        raise SmokeFailure(errors[0].get("message", str(errors)))
    return payload["data"]


async def swagger_op(
    client: httpx.AsyncClient,
    path: str,
    *,
    variables: dict | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = await client.post(path, json={"variables": variables or {}}, headers=headers)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise SmokeFailure(str(payload["errors"]))
    return payload


async def gql_expect_error(
    client: httpx.AsyncClient,
    query: str,
    *,
    variables: dict | None = None,
    token: str | None = None,
) -> list[dict]:
    """Return GraphQL errors (expect at least one)."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = await client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )
    response.raise_for_status()
    payload = response.json()
    errors = payload.get("errors") or []
    if not errors:
        raise SmokeFailure(f"Expected GraphQL error but got data: {payload.get('data')}")
    return errors


async def gql_raw(
    client: httpx.AsyncClient,
    query: str,
    *,
    variables: dict | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = await client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )
    return {"status_code": response.status_code, "body": response.json()}


async def setup_smoke_org(report: SmokeReport) -> dict[str, Any]:
    from app.core.db import AsyncSessionLocal, get_tenant_db
    from app.core.security import hash_password
    from app.db.enums import UserRole, UserStatus
    from app.db.models.organization import Organization
    from app.db.models.user import User

    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    member_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                Organization(
                    id=org_id,
                    name=ORG_NAME,
                    plan="trial",
                    settings={
                        "smoke_test": True,
                        "marker": SMOKE_MARKER,
                        "cr_internal_approval_cost_threshold": 5000,
                        "cr_internal_approval_timeline_days_threshold": 5,
                        "cr_revision_cap": 3,
                        "cr_response_sla_days": 7,
                    },
                )
            )

    async with get_tenant_db(org_id) as db:
        db.add(
            User(
                id=admin_id,
                org_id=org_id,
                name="Smoke Admin",
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                role=UserRole.ADMIN.value,
                status=UserStatus.ACTIVE.value,
            )
        )
        db.add(
            User(
                id=member_id,
                org_id=org_id,
                name="Smoke Member",
                email=f"smoke-member-{RUN_ID}@test.local",
                password_hash=hash_password(SMOKE_MEMBER_PASSWORD),
                role=UserRole.TEAM_MEMBER.value,
                status=UserStatus.ACTIVE.value,
            )
        )

    report.org_id = str(org_id)
    report.add("Setup", "create_smoke_org", "PASS", f"org_id={org_id}")
    return {
        "org_id": org_id,
        "admin_id": admin_id,
        "member_id": member_id,
        "member_email": f"smoke-member-{RUN_ID}@test.local",
        "member_password": SMOKE_MEMBER_PASSWORD,
    }


async def cleanup_smoke_data(report: SmokeReport, org_id: uuid.UUID, asset_paths: list[str]) -> None:
    from sqlalchemy import text

    from app.core.config import get_settings
    from app.core.db import AsyncSessionLocal
    from app.integrations import asset_storage

    settings = get_settings()

    for rel_path in asset_paths:
        try:
            target = asset_storage.absolute_path(rel_path, settings)
            if target.is_file():
                target.unlink()
        except Exception as exc:  # noqa: BLE001
            report.add("Cleanup", f"asset:{rel_path}", "WARN", str(exc))

    tables = [
        "invoices",
        "client_health_scores",
        "contracts",
        "change_request_attachments",
        "change_requests",
        "notifications",
        "touchpoints",
        "retention_enrollments",
        "retention_sequence_steps",
        "retention_sequences",
        "email_templates",
        "job_runs",
        "task_dependencies",
        "tasks",
        "milestones",
        "project_phases",
        "approvals",
        "documents",
        "projects",
        "entity_tags",
        "tags",
        "contacts",
        "companies",
        "activity_logs",
        "users",
        "organizations",
    ]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(org_id)},
            )
            user_rows = await session.execute(
                text("SELECT id FROM users WHERE org_id = :org_id"),
                {"org_id": str(org_id)},
            )
            user_ids = [str(row[0]) for row in user_rows.fetchall()]
            if user_ids:
                await session.execute(
                    text("DELETE FROM refresh_tokens WHERE user_id = ANY(:ids)"),
                    {"ids": user_ids},
                )
            for table in tables:
                if table == "organizations":
                    await session.execute(
                        text("DELETE FROM organizations WHERE id = :org_id"),
                        {"org_id": str(org_id)},
                    )
                else:
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE org_id = :org_id"),
                        {"org_id": str(org_id)},
                    )

    report.add("Cleanup", "database_and_assets", "PASS", f"removed org {org_id}")


async def run_smoke(report: SmokeReport) -> None:
    ids: dict[str, Any] = {}
    asset_paths: list[str] = []
    admin_token: str | None = None

    base_url = __import__("os").environ.get("SMOKE_BASE_URL")
    if base_url:
        client_cm = httpx.AsyncClient(base_url=base_url, timeout=60.0)
    else:
        from httpx import ASGITransport

        from app.main import create_app

        app = create_app()
        client_cm = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60.0)

    setup = await setup_smoke_org(report)

    async with client_cm as client:
        # --- Preflight / Phase 0 ---
        try:
            r = await client.get("/health")
            assert r.status_code == 200 and r.json()["status"] == "ok"
            report.add("Phase 0", "GET /health", "PASS")
        except Exception as exc:
            report.add("Phase 0", "GET /health", "FAIL", str(exc))

        try:
            r = await client.get("/health/ready")
            if r.status_code == 200:
                report.add("Phase 0", "GET /health/ready", "PASS", "database ok")
            else:
                report.add(
                    "Phase 0",
                    "GET /health/ready",
                    "FAIL",
                    f"status={r.status_code}",
                )
        except Exception as exc:
            report.add("Phase 0", "GET /health/ready", "WARN", str(exc))

        try:
            data = await gql(client, "query { status }")
            assert data["status"] == "ok"
            report.add("Phase 0", "GraphQL status query", "PASS")
        except Exception as exc:
            report.add("Phase 0", "GraphQL status query", "FAIL", str(exc))

        try:
            payload = await swagger_op(client, "/graphql/queries/status")
            assert payload.get("data", {}).get("status") == "ok"
            report.add("Phase 0", "Swagger wrapper /graphql/queries/status", "PASS")
        except Exception as exc:
            report.add("Phase 0", "Swagger wrapper /graphql/queries/status", "FAIL", str(exc))

        # --- Security: unauthenticated access rejected ---
        try:
            errors = await gql_expect_error(client, "query { companies { id name } }")
            code = (errors[0].get("extensions") or {}).get("code", "")
            assert code == "authentication_error"
            report.add("Security", "unauthenticated companies query rejected", "PASS", code)
        except Exception as exc:
            report.add("Security", "unauthenticated companies query rejected", "FAIL", str(exc))

        try:
            errors = await gql_expect_error(
                client,
                "query($projectId: ID!) { changeRequests(projectId: $projectId) { id } }",
                variables={"projectId": "00000000-0000-0000-0000-000000000001"},
            )
            code = (errors[0].get("extensions") or {}).get("code", "")
            assert code == "authentication_error"
            report.add("Security", "unauthenticated changeRequests rejected", "PASS", code)
        except Exception as exc:
            report.add("Security", "unauthenticated changeRequests rejected", "FAIL", str(exc))

        try:
            raw = await gql_raw(client, "query { status }")
            assert raw["status_code"] == 200
            report.add("Security", "public status query allowed", "PASS")
        except Exception as exc:
            report.add("Security", "public status query allowed", "FAIL", str(exc))

        # --- Phase 1 Auth ---
        try:
            data = await gql(
                client,
                """
                mutation Login($email: String!, $password: String!) {
                  login(email: $email, password: $password) {
                    accessToken
                    requires2fa
                  }
                }
                """,
                variables={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            )
            admin_token = data["login"]["accessToken"]
            assert admin_token and not data["login"]["requires2fa"]
            report.add("Phase 1", "login", "PASS")
        except Exception as exc:
            report.add("Phase 1", "login", "FAIL", str(exc))
            raise SmokeFailure("Cannot continue without admin login") from exc

        try:
            data = await gql(
                client,
                "mutation { refreshToken { accessToken } }",
                token=admin_token,
            )
            admin_token = data["refreshToken"]["accessToken"]
            report.add("Phase 1", "refreshToken", "PASS")
        except Exception as exc:
            report.add("Phase 1", "refreshToken", "WARN", str(exc))

        # --- Phase 1 Companies CRUD ---
        try:
            data = await gql(
                client,
                """
                mutation($name: String!) {
                  createCompany(name: $name, status: "active", industry: "Technology") {
                    id name status industry
                  }
                }
                """,
                variables={"name": f"{SMOKE_MARKER} Company A"},
                token=admin_token,
            )
            ids["company_a"] = data["createCompany"]["id"]
            report.add("Phase 1", "createCompany", "PASS", ids["company_a"])
        except Exception as exc:
            report.add("Phase 1", "createCompany", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                mutation($id: ID!, $name: String!) {
                  updateCompany(id: $id, name: $name, status: "active") { id name }
                }
                """,
                variables={"id": ids["company_a"], "name": f"{SMOKE_MARKER} Company A Updated"},
                token=admin_token,
            )
            report.add("Phase 1", "updateCompany", "PASS", data["updateCompany"]["name"])
        except Exception as exc:
            report.add("Phase 1", "updateCompany", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                "query { companies { id name } }",
                token=admin_token,
            )
            assert any(c["id"] == ids["company_a"] for c in data["companies"])
            report.add("Phase 1", "companies list", "PASS", f"count={len(data['companies'])}")
        except Exception as exc:
            report.add("Phase 1", "companies list", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                "query($id: ID!) { company(id: $id) { id name contacts { id } } }",
                variables={"id": ids["company_a"]},
                token=admin_token,
            )
            assert data["company"]["id"] == ids["company_a"]
            report.add("Phase 1", "company detail + nested contacts", "PASS")
        except Exception as exc:
            report.add("Phase 1", "company detail", "FAIL", str(exc))

        # --- Phase 1 Contacts CRUD ---
        try:
            data = await gql(
                client,
                """
                mutation($companyId: ID!, $email: String!) {
                  createContact(
                    companyId: $companyId
                    firstName: "Portal"
                    lastName: "User"
                    email: $email
                    portalAccessEnabled: true
                    status: "active"
                  ) { id email portalAccessEnabled }
                }
                """,
                variables={
                    "companyId": ids["company_a"],
                    "email": PORTAL_EMAIL,
                },
                token=admin_token,
            )
            ids["portal_contact"] = data["createContact"]["id"]
            from app.core.db import get_tenant_db
            from app.core.security import hash_password
            from app.db.models.contact import Contact

            async with get_tenant_db(setup["org_id"]) as db:
                contact = await db.get(Contact, uuid.UUID(ids["portal_contact"]))
                contact.password_hash = hash_password(PORTAL_PASSWORD)
            report.add("Phase 1", "createContact (portal)", "PASS", ids["portal_contact"])
        except Exception as exc:
            report.add("Phase 1", "createContact (portal)", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                mutation($id: ID!) {
                  updateContact(id: $id, title: "Primary Contact") { id title }
                }
                """,
                variables={"id": ids["portal_contact"]},
                token=admin_token,
            )
            report.add("Phase 1", "updateContact", "PASS", data["updateContact"]["title"])
        except Exception as exc:
            report.add("Phase 1", "updateContact", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                "query { contacts { id email } }",
                token=admin_token,
            )
            assert any(c["id"] == ids["portal_contact"] for c in data["contacts"])
            report.add("Phase 1", "contacts list", "PASS")
        except Exception as exc:
            report.add("Phase 1", "contacts list", "FAIL", str(exc))

        # --- Phase 1 Tags ---
        try:
            data = await gql(
                client,
                'mutation { createTag(name: "smoke-priority") { id name } }',
                token=admin_token,
            )
            ids["tag"] = data["createTag"]["id"]
            report.add("Phase 1", "createTag", "PASS", ids["tag"])
        except Exception as exc:
            report.add("Phase 1", "createTag", "FAIL", str(exc))

        try:
            await gql(
                client,
                """
                mutation($entityId: ID!, $tagId: ID!) {
                  addTag(entityType: "company", entityId: $entityId, tagId: $tagId)
                }
                """,
                variables={"entityId": ids["company_a"], "tagId": ids["tag"]},
                token=admin_token,
            )
            report.add("Phase 1", "addTag", "PASS")
        except Exception as exc:
            report.add("Phase 1", "addTag", "FAIL", str(exc))

        try:
            data = await gql(client, "query { tags { id name } }", token=admin_token)
            assert any(t["id"] == ids["tag"] for t in data["tags"])
            report.add("Phase 1", "tags list", "PASS")
        except Exception as exc:
            report.add("Phase 1", "tags list", "FAIL", str(exc))

        # --- Phase 2 Projects CRUD ---
        try:
            data = await gql(
                client,
                """
                mutation($companyId: ID!, $name: String!) {
                  createProject(companyId: $companyId, name: $name, status: "active", budget: 10000) {
                    id name budget companyId
                  }
                }
                """,
                variables={"companyId": ids["company_a"], "name": f"{SMOKE_MARKER} Project"},
                token=admin_token,
            )
            ids["project"] = data["createProject"]["id"]
            report.add("Phase 2", "createProject", "PASS", ids["project"])
        except Exception as exc:
            report.add("Phase 2", "createProject", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                mutation($id: ID!) {
                  updateProject(id: $id, name: "Smoke Project Updated", health: "on_track") { id name health }
                }
                """,
                variables={"id": ids["project"]},
                token=admin_token,
            )
            report.add("Phase 2", "updateProject", "PASS")
        except Exception as exc:
            report.add("Phase 2", "updateProject", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                "query($id: ID!) { project(id: $id) { id name phases { id } tasks { id } } }",
                variables={"id": ids["project"]},
                token=admin_token,
            )
            assert data["project"]["id"] == ids["project"]
            report.add("Phase 2", "project detail", "PASS")
        except Exception as exc:
            report.add("Phase 2", "project detail", "FAIL", str(exc))

        # --- Phase 2 Planning ---
        try:
            data = await gql(
                client,
                """
                mutation($projectId: ID!) {
                  createPhase(projectId: $projectId, name: "Phase 1", orderIndex: 0, status: "in_progress") { id }
                }
                """,
                variables={"projectId": ids["project"]},
                token=admin_token,
            )
            ids["phase1"] = data["createPhase"]["id"]
            data2 = await gql(
                client,
                """
                mutation($projectId: ID!) {
                  createPhase(projectId: $projectId, name: "Phase 2", orderIndex: 1) { id }
                }
                """,
                variables={"projectId": ids["project"]},
                token=admin_token,
            )
            ids["phase2"] = data2["createPhase"]["id"]
            report.add("Phase 2", "createPhase x2", "PASS")
        except Exception as exc:
            report.add("Phase 2", "createPhase", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                mutation($projectId: ID!, $ordered: [ID!]!) {
                  reorderPhases(projectId: $projectId, orderedPhaseIds: $ordered) { id orderIndex }
                }
                """,
                variables={"projectId": ids["project"], "ordered": [ids["phase2"], ids["phase1"]]},
                token=admin_token,
            )
            assert data["reorderPhases"][0]["id"] == ids["phase2"]
            report.add("Phase 2", "reorderPhases", "PASS")
        except Exception as exc:
            report.add("Phase 2", "reorderPhases", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                mutation($phaseId: ID!) {
                  createMilestone(
                    phaseId: $phaseId
                    title: "Deliverable 1"
                    orderIndex: 0
                    status: "in_progress"
                    requiresClientApproval: true
                  ) { id title requiresClientApproval }
                }
                """,
                variables={"phaseId": ids["phase1"]},
                token=admin_token,
            )
            ids["milestone"] = data["createMilestone"]["id"]
            report.add("Phase 2", "createMilestone", "PASS", ids["milestone"])
        except Exception as exc:
            report.add("Phase 2", "createMilestone", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                mutation($projectId: ID!, $phaseId: ID!) {
                  t1: createTask(projectId: $projectId, phaseId: $phaseId, title: "Task A", estimatedHours: 5) { id }
                  t2: createTask(projectId: $projectId, phaseId: $phaseId, title: "Task B", estimatedHours: 3) { id }
                }
                """,
                variables={"projectId": ids["project"], "phaseId": ids["phase1"]},
                token=admin_token,
            )
            ids["task_a"] = data["t1"]["id"]
            ids["task_b"] = data["t2"]["id"]
            report.add("Phase 2", "createTask x2", "PASS")
        except Exception as exc:
            report.add("Phase 2", "createTask", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                mutation($id: ID!) {
                  updateTask(id: $id, status: "in_progress", actualHours: 2) { id status actualHours }
                }
                """,
                variables={"id": ids["task_a"]},
                token=admin_token,
            )
            report.add("Phase 2", "updateTask", "PASS", data["updateTask"]["status"])
        except Exception as exc:
            report.add("Phase 2", "updateTask", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                mutation($projectId: ID!, $taskId: ID!, $dependsOn: ID!) {
                  addTaskDependency(
                    projectId: $projectId
                    taskId: $taskId
                    dependsOnTaskId: $dependsOn
                  ) { id taskId dependsOnTaskId }
                }
                """,
                variables={
                    "projectId": ids["project"],
                    "taskId": ids["task_b"],
                    "dependsOn": ids["task_a"],
                },
                token=admin_token,
            )
            ids["dependency"] = data["addTaskDependency"]["id"]
            report.add("Phase 2", "addTaskDependency", "PASS")
        except Exception as exc:
            report.add("Phase 2", "addTaskDependency", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                "query($projectId: ID!) { workload(projectId: $projectId) { openTaskCount totalEstimatedHours } }",
                variables={"projectId": ids["project"]},
                token=admin_token,
            )
            wl = data["workload"]
            report.add("Phase 2", "workload query", "PASS", f"rows={len(wl)}")
        except Exception as exc:
            report.add("Phase 2", "workload query", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                "query($projectId: ID!) { phases(projectId: $projectId) { id name milestones { id title } } }",
                variables={"projectId": ids["project"]},
                token=admin_token,
            )
            assert len(data["phases"]) >= 2
            report.add("Phase 2", "phases + nested milestones", "PASS")
        except Exception as exc:
            report.add("Phase 2", "phases query", "FAIL", str(exc))

        # --- Phase 3 Documents ---
        try:
            data = await gql(
                client,
                """
                mutation($entityId: ID!) {
                  requestUploadUrl(
                    entityType: "project"
                    entityId: $entityId
                    filename: "smoke-spec.pdf"
                    contentType: "application/pdf"
                  ) { uploadUrl fileUrl uploadToken }
                }
                """,
                variables={"entityId": ids["project"]},
                token=admin_token,
            )
            upload = data["requestUploadUrl"]
            asset_paths.append(upload["fileUrl"])
            upload_resp = await client.put(
                "/assets/upload",
                content=b"%PDF-1.4 smoke test content",
                headers={
                    "Authorization": f"Bearer {upload['uploadToken']}",
                    "Content-Type": "application/pdf",
                },
            )
            upload_resp.raise_for_status()
            confirm = await gql(
                client,
                """
                mutation($entityId: ID!, $fileUrl: String!) {
                  confirmUpload(entityType: "project", entityId: $entityId, fileUrl: $fileUrl) {
                    id version fileUrl
                  }
                }
                """,
                variables={"entityId": ids["project"], "fileUrl": upload["fileUrl"]},
                token=admin_token,
            )
            ids["document"] = confirm["confirmUpload"]["id"]
            report.add("Phase 3", "document upload flow", "PASS", f"version={confirm['confirmUpload']['version']}")
        except Exception as exc:
            report.add("Phase 3", "document upload flow", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                query($entityId: ID!) {
                  documents(entityType: "project", entityId: $entityId) { id version fileUrl }
                }
                """,
                variables={"entityId": ids["project"]},
                token=admin_token,
            )
            assert len(data["documents"]) >= 1
            report.add("Phase 3", "documents query", "PASS")
        except Exception as exc:
            report.add("Phase 3", "documents query", "FAIL", str(exc))

        # --- Phase 3 Portal ---
        try:
            data = await gql(
                client,
                """
                mutation($email: String!, $password: String!) {
                  portalLogin(email: $email, password: $password) { accessToken }
                }
                """,
                variables={"email": PORTAL_EMAIL, "password": PORTAL_PASSWORD},
            )
            portal_token = data["portalLogin"]["accessToken"]
            report.add("Phase 3", "portalLogin", "PASS")
        except Exception as exc:
            report.add("Phase 3", "portalLogin", "FAIL", str(exc))
            portal_token = None

        if portal_token:
            try:
                data = await gql(
                    client,
                    "query { portalCompany { id name } portalProjects { id name } }",
                    token=portal_token,
                )
                assert data["portalCompany"]["id"] == ids["company_a"]
                assert any(p["id"] == ids["project"] for p in data["portalProjects"])
                report.add("Phase 3", "portalCompany + portalProjects", "PASS")
            except Exception as exc:
                report.add("Phase 3", "portalCompany + portalProjects", "FAIL", str(exc))

            try:
                data = await gql(
                    client,
                    "query($id: ID!) { portalProject(id: $id) { id name phases { id name } } }",
                    variables={"id": ids["project"]},
                    token=portal_token,
                )
                assert "budget" not in json.dumps(data)
                report.add("Phase 3", "portalProject (no budget fields)", "PASS")
            except Exception as exc:
                report.add("Phase 3", "portalProject", "FAIL", str(exc))

        # --- Phase 3 Milestone approval ---
        try:
            data = await gql(
                client,
                """
                mutation($milestoneId: ID!) {
                  markMilestoneReadyForReview(milestoneId: $milestoneId) { id status entityId }
                }
                """,
                variables={"milestoneId": ids["milestone"]},
                token=admin_token,
            )
            ids["approval"] = data["markMilestoneReadyForReview"]["id"]
            report.add("Phase 3", "markMilestoneReadyForReview", "PASS", ids["approval"])
        except Exception as exc:
            report.add("Phase 3", "markMilestoneReadyForReview", "FAIL", str(exc))

        if portal_token and ids.get("approval"):
            try:
                data = await gql(
                    client,
                    "query { portalPendingApprovals { id status entityId } }",
                    token=portal_token,
                )
                assert any(a["id"] == ids["approval"] for a in data["portalPendingApprovals"])
                report.add("Phase 3", "portalPendingApprovals", "PASS")
            except Exception as exc:
                report.add("Phase 3", "portalPendingApprovals", "FAIL", str(exc))

            try:
                data = await gql(
                    client,
                    """
                    mutation($approvalId: ID!) {
                      approveMilestone(approvalId: $approvalId) { id status }
                    }
                    """,
                    variables={"approvalId": ids["approval"]},
                    token=portal_token,
                )
                assert data["approveMilestone"]["status"] == "approved"
                report.add("Phase 3", "approveMilestone", "PASS")
            except Exception as exc:
                report.add("Phase 3", "approveMilestone", "FAIL", str(exc))

        # --- Security: portal cross-company isolation ---
        try:
            data_b = await gql(
                client,
                """
                mutation($name: String!) {
                  createCompany(name: $name, status: "active") { id name }
                }
                """,
                variables={"name": f"{SMOKE_MARKER} Company B"},
                token=admin_token,
            )
            ids["company_b"] = data_b["createCompany"]["id"]
            data_pb = await gql(
                client,
                """
                mutation($companyId: ID!, $name: String!) {
                  createProject(companyId: $companyId, name: $name, status: "active") { id }
                }
                """,
                variables={"companyId": ids["company_b"], "name": f"{SMOKE_MARKER} Project B"},
                token=admin_token,
            )
            ids["project_b"] = data_pb["createProject"]["id"]
            if portal_token:
                data = await gql(
                    client,
                    "query($id: ID!) { portalProject(id: $id) { id name } }",
                    variables={"id": ids["project_b"]},
                    token=portal_token,
                )
                assert data["portalProject"] is None
                data = await gql(
                    client,
                    "query { portalProjects { id } }",
                    token=portal_token,
                )
                portal_ids = {p["id"] for p in data["portalProjects"]}
                assert ids["project_b"] not in portal_ids
                assert ids["project"] in portal_ids
                report.add("Security", "portal cannot see other company project", "PASS")
            else:
                report.add("Security", "portal cannot see other company project", "SKIP", "no portal token")
        except Exception as exc:
            report.add("Security", "portal cannot see other company project", "FAIL", str(exc))

        # --- Phase 4 Change Requests (happy path) ---
        if portal_token:
            try:
                data = await gql(
                    client,
                    """
                    mutation($projectId: ID!, $title: String!) {
                      createChangeRequest(
                        projectId: $projectId
                        title: $title
                        type: "scope_addition"
                        description: "Add landing page"
                        priority: "high"
                      ) { id status type title revisionCount }
                    }
                    """,
                    variables={"projectId": ids["project"], "title": f"{SMOKE_MARKER} CR Scope Add"},
                    token=portal_token,
                )
                cr = data["createChangeRequest"]
                ids["change_request"] = cr["id"]
                assert cr["status"] == "submitted"
                report.add("Phase 4", "portal createChangeRequest", "PASS", cr["id"])
            except Exception as exc:
                report.add("Phase 4", "portal createChangeRequest", "FAIL", str(exc))

        if ids.get("change_request"):
            try:
                data = await gql(
                    client,
                    """
                    mutation($id: ID!) {
                      transitionChangeRequest(id: $id, toStatus: "under_review") { id status }
                    }
                    """,
                    variables={"id": ids["change_request"]},
                    token=admin_token,
                )
                assert data["transitionChangeRequest"]["status"] == "under_review"
                report.add("Phase 4", "transitionChangeRequest under_review", "PASS")
            except Exception as exc:
                report.add("Phase 4", "transitionChangeRequest under_review", "FAIL", str(exc))

            try:
                data = await gql(
                    client,
                    """
                    mutation Login($email: String!, $password: String!) {
                      login(email: $email, password: $password) { accessToken }
                    }
                    """,
                    variables={"email": setup["member_email"], "password": setup["member_password"]},
                )
                member_token = data["login"]["accessToken"]
                errors = await gql_expect_error(
                    client,
                    """
                    mutation($id: ID!) {
                      submitImpactAssessment(id: $id, impactCost: 100) { id }
                    }
                    """,
                    variables={"id": ids["change_request"]},
                    token=member_token,
                )
                code = (errors[0].get("extensions") or {}).get("code", "")
                assert code == "authorization_error"
                report.add("Security", "team_member cannot submitImpactAssessment", "PASS", code)
            except Exception as exc:
                report.add("Security", "team_member cannot submitImpactAssessment", "FAIL", str(exc))

            try:
                data = await gql(
                    client,
                    """
                    mutation($id: ID!) {
                      submitImpactAssessment(
                        id: $id
                        impactHours: 40
                        impactCost: 6000
                        impactTimelineDays: 7
                        assessmentNotes: "Large scope — dual approval"
                      ) { id status requiresClientApproval requiresInternalApproval }
                    }
                    """,
                    variables={"id": ids["change_request"]},
                    token=admin_token,
                )
                cr = data["submitImpactAssessment"]
                assert cr["status"] == "pending_approval"
                assert cr["requiresClientApproval"] is True
                assert cr["requiresInternalApproval"] is True
                report.add("Phase 4", "submitImpactAssessment dual approval", "PASS")
            except Exception as exc:
                report.add("Phase 4", "submitImpactAssessment dual approval", "FAIL", str(exc))

            # Internal approval first (sequencing rule)
            try:
                from app.core.db import get_tenant_db
                from app.db.enums import EntityType
                from app.db.models.approval import Approval
                from sqlalchemy import select

                async with get_tenant_db(setup["org_id"]) as db:
                    result = await db.execute(
                        select(Approval).where(
                            Approval.entity_type == EntityType.CHANGE_REQUEST.value,
                            Approval.entity_id == uuid.UUID(ids["change_request"]),
                            Approval.approver_type == "internal",
                        )
                    )
                    internal_approval = result.scalar_one()
                    ids["cr_internal_approval"] = str(internal_approval.id)

                data = await gql(
                    client,
                    """
                    mutation($id: ID!, $approvalId: ID!) {
                      decideChangeRequest(
                        id: $id
                        approvalId: $approvalId
                        decision: "approved"
                        comment: "Internal OK"
                      ) { id status }
                    }
                    """,
                    variables={"id": ids["change_request"], "approvalId": ids["cr_internal_approval"]},
                    token=admin_token,
                )
                assert data["decideChangeRequest"]["status"] == "pending_approval"
                report.add("Phase 4", "decideChangeRequest internal approve", "PASS")
            except Exception as exc:
                report.add("Phase 4", "decideChangeRequest internal approve", "FAIL", str(exc))

            if portal_token:
                try:
                    async with get_tenant_db(setup["org_id"]) as db:
                        result = await db.execute(
                            select(Approval).where(
                                Approval.entity_type == EntityType.CHANGE_REQUEST.value,
                                Approval.entity_id == uuid.UUID(ids["change_request"]),
                                Approval.approver_type == "client",
                            )
                        )
                        client_approval = result.scalar_one()
                        ids["cr_client_approval"] = str(client_approval.id)

                    data = await gql(
                        client,
                        """
                        mutation($id: ID!, $approvalId: ID!) {
                          decideChangeRequest(
                            id: $id
                            approvalId: $approvalId
                            decision: "approved"
                            applyFinancialImpact: false
                          ) { id status }
                        }
                        """,
                        variables={"id": ids["change_request"], "approvalId": ids["cr_client_approval"]},
                        token=portal_token,
                    )
                    assert data["decideChangeRequest"]["status"] == "in_progress"
                    report.add("Phase 4", "decideChangeRequest client approve -> in_progress", "PASS")
                except Exception as exc:
                    report.add("Phase 4", "decideChangeRequest client approve -> in_progress", "FAIL", str(exc))

            try:
                data = await gql(
                    client,
                    """
                    query($projectId: ID!) {
                      changeRequests(projectId: $projectId) { id status title }
                      changeRequestDashboard { openCount pendingApprovalCount overdueCount slaDays }
                    }
                    """,
                    variables={"projectId": ids["project"]},
                    token=admin_token,
                )
                crs = data["changeRequests"]
                assert any(c["id"] == ids["change_request"] for c in crs)
                dash = data["changeRequestDashboard"]
                assert dash["openCount"] >= 1
                report.add("Phase 4", "changeRequests + dashboard", "PASS", f"open={dash['openCount']}")
            except Exception as exc:
                report.add("Phase 4", "changeRequests + dashboard", "FAIL", str(exc))

            # Budget unchanged when applyFinancialImpact=false
            try:
                data = await gql(
                    client,
                    "query($id: ID!) { project(id: $id) { budget } }",
                    variables={"id": ids["project"]},
                    token=admin_token,
                )
                assert float(data["project"]["budget"]) == 10000.0
                report.add("Phase 4", "budget unchanged without applyFinancialImpact", "PASS")
            except Exception as exc:
                report.add("Phase 4", "budget unchanged without applyFinancialImpact", "FAIL", str(exc))

        # --- Phase 5: Retention sequences + touchpoints ---
        try:
            data = await gql(
                client,
                """
                mutation($name: String!) {
                  createRetentionSequence(name: $name, triggerType: "manual") { id name isActive }
                }
                """,
                variables={"name": f"{SMOKE_MARKER} Welcome Sequence"},
                token=admin_token,
            )
            ids["retention_sequence"] = data["createRetentionSequence"]["id"]
            report.add("Phase 5", "createRetentionSequence", "PASS", ids["retention_sequence"])
        except Exception as exc:
            report.add("Phase 5", "createRetentionSequence", "FAIL", str(exc))

        if ids.get("retention_sequence"):
            try:
                data = await gql(
                    client,
                    """
                    mutation($sequenceId: ID!) {
                      addSequenceStep(sequenceId: $sequenceId, channel: "task", offsetDays: 0) {
                        id stepOrder channel
                      }
                    }
                    """,
                    variables={"sequenceId": ids["retention_sequence"]},
                    token=admin_token,
                )
                ids["retention_step"] = data["addSequenceStep"]["id"]
                report.add("Phase 5", "addSequenceStep", "PASS", ids["retention_step"])
            except Exception as exc:
                report.add("Phase 5", "addSequenceStep", "FAIL", str(exc))

        if ids.get("retention_sequence") and ids.get("portal_contact"):
            try:
                data = await gql(
                    client,
                    """
                    mutation($sequenceId: ID!, $companyId: ID!, $contactId: ID!) {
                      enrollInSequence(
                        sequenceId: $sequenceId
                        companyId: $companyId
                        contactId: $contactId
                      ) { id status currentStep }
                    }
                    """,
                    variables={
                        "sequenceId": ids["retention_sequence"],
                        "companyId": ids["company_a"],
                        "contactId": ids["portal_contact"],
                    },
                    token=admin_token,
                )
                ids["retention_enrollment"] = data["enrollInSequence"]["id"]
                assert data["enrollInSequence"]["status"] == "active"
                report.add("Phase 5", "enrollInSequence", "PASS", ids["retention_enrollment"])
            except Exception as exc:
                report.add("Phase 5", "enrollInSequence", "FAIL", str(exc))

        if ids.get("retention_enrollment"):
            try:
                from datetime import date

                from app.scheduler.jobs import process_due_sequence_steps

                result = await process_due_sequence_steps(run_date=date.today())
                assert result["touchpoints_created"] >= 1
                report.add(
                    "Phase 5",
                    "processDueSequenceSteps",
                    "PASS",
                    f"created={result['touchpoints_created']}",
                )
            except Exception as exc:
                report.add("Phase 5", "processDueSequenceSteps", "FAIL", str(exc))

            try:
                data = await gql(
                    client,
                    "query { upcomingTouchpoints { id status enrollmentId } }",
                    token=admin_token,
                )
                tps = data["upcomingTouchpoints"]
                assert len(tps) >= 1
                ids["touchpoint"] = tps[0]["id"]
                report.add("Phase 5", "upcomingTouchpoints", "PASS", f"count={len(tps)}")
            except Exception as exc:
                report.add("Phase 5", "upcomingTouchpoints", "FAIL", str(exc))

            if ids.get("touchpoint"):
                try:
                    data = await gql(
                        client,
                        """
                        mutation($id: ID!) {
                          completeTouchpoint(id: $id, outcome: "positive") {
                            id status outcome
                          }
                        }
                        """,
                        variables={"id": ids["touchpoint"]},
                        token=admin_token,
                    )
                    assert data["completeTouchpoint"]["status"] == "completed"
                    report.add("Phase 5", "completeTouchpoint", "PASS")
                except Exception as exc:
                    report.add("Phase 5", "completeTouchpoint", "FAIL", str(exc))

            try:
                data = await gql(
                    client,
                    "query { retentionSequences(activeOnly: true) { id name steps { id } } }",
                    token=admin_token,
                )
                assert any(s["id"] == ids["retention_sequence"] for s in data["retentionSequences"])
                report.add("Phase 5", "retentionSequences query", "PASS")
            except Exception as exc:
                report.add("Phase 5", "retentionSequences query", "FAIL", str(exc))

        # --- Phase 5b: Auto-enrollment hooks ---
        try:
            data = await gql(
                client,
                """
                mutation($name: String!) {
                  createRetentionSequence(name: $name, triggerType: "on_company_created") { id }
                }
                """,
                variables={"name": f"{SMOKE_MARKER} Auto Company Seq"},
                token=admin_token,
            )
            ids["auto_company_seq"] = data["createRetentionSequence"]["id"]
            await gql(
                client,
                """
                mutation($sequenceId: ID!) {
                  addSequenceStep(sequenceId: $sequenceId, channel: "email", offsetDays: 0) { id }
                }
                """,
                variables={"sequenceId": ids["auto_company_seq"]},
                token=admin_token,
            )
            data = await gql(
                client,
                """
                mutation($name: String!) {
                  createCompany(name: $name, status: "active") { id }
                }
                """,
                variables={"name": f"{SMOKE_MARKER} Auto Enroll Co"},
                token=admin_token,
            )
            ids["auto_enroll_company"] = data["createCompany"]["id"]
            await gql(
                client,
                """
                mutation($companyId: ID!, $email: String!) {
                  createContact(
                    companyId: $companyId
                    firstName: "Auto"
                    lastName: "Primary"
                    email: $email
                    isPrimary: true
                    status: "active"
                  ) { id isPrimary }
                }
                """,
                variables={
                    "companyId": ids["auto_enroll_company"],
                    "email": f"auto-primary-{RUN_ID}@test.local",
                },
                token=admin_token,
            )
            from app.core.db import get_tenant_db
            from app.graphql.retention.repository import has_active_enrollment_for_sequence

            async with get_tenant_db(setup["org_id"]) as db:
                enrolled = await has_active_enrollment_for_sequence(
                    db,
                    company_id=uuid.UUID(ids["auto_enroll_company"]),
                    sequence_id=uuid.UUID(ids["auto_company_seq"]),
                )
            assert enrolled
            report.add("Phase 5", "autoEnroll on_company_created", "PASS")
        except Exception as exc:
            report.add("Phase 5", "autoEnroll on_company_created", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                mutation($name: String!) {
                  createRetentionSequence(name: $name, triggerType: "on_project_completed") { id }
                }
                """,
                variables={"name": f"{SMOKE_MARKER} Auto Project Seq"},
                token=admin_token,
            )
            ids["auto_project_seq"] = data["createRetentionSequence"]["id"]
            await gql(
                client,
                """
                mutation($sequenceId: ID!) {
                  addSequenceStep(sequenceId: $sequenceId, channel: "call", offsetDays: 1) { id }
                }
                """,
                variables={"sequenceId": ids["auto_project_seq"]},
                token=admin_token,
            )
            await gql(
                client,
                """
                mutation($id: ID!) {
                  updateContact(id: $id, isPrimary: true) { id isPrimary }
                }
                """,
                variables={"id": ids["portal_contact"]},
                token=admin_token,
            )
            await gql(
                client,
                """
                mutation($id: ID!) {
                  updateProject(id: $id, status: "completed") { id status }
                }
                """,
                variables={"id": ids["project"]},
                token=admin_token,
            )
            async with get_tenant_db(setup["org_id"]) as db:
                enrolled = await has_active_enrollment_for_sequence(
                    db,
                    company_id=uuid.UUID(ids["company_a"]),
                    sequence_id=uuid.UUID(ids["auto_project_seq"]),
                )
            assert enrolled
            report.add("Phase 5", "autoEnroll on_project_completed", "PASS")
        except Exception as exc:
            report.add("Phase 5", "autoEnroll on_project_completed", "FAIL", str(exc))

        if portal_token and ids.get("retention_sequence") and ids.get("portal_contact"):
            try:
                errors = await gql_expect_error(
                    client,
                    """
                    mutation($sequenceId: ID!, $companyId: ID!, $contactId: ID!) {
                      enrollInSequence(
                        sequenceId: $sequenceId
                        companyId: $companyId
                        contactId: $contactId
                      ) { id }
                    }
                    """,
                    variables={
                        "sequenceId": ids["retention_sequence"],
                        "companyId": ids["company_a"],
                        "contactId": ids["portal_contact"],
                    },
                    token=portal_token,
                )
                code = (errors[0].get("extensions") or {}).get("code", "")
                assert code in {"authorization_error", "authentication_error"}
                report.add("Security", "portal cannot enroll in sequence", "PASS", code)
            except Exception as exc:
                report.add("Security", "portal cannot enroll in sequence", "FAIL", str(exc))

        # --- Phase 6: Contracts + health scores ---
        from datetime import date, timedelta

        contract_end = (date.today() + timedelta(days=180)).isoformat()
        contract_start = (date.today() - timedelta(days=30)).isoformat()

        try:
            data = await gql(
                client,
                """
                mutation($companyId: ID!, $name: String!, $startDate: Date!, $endDate: Date!) {
                  createContract(
                    companyId: $companyId
                    name: $name
                    startDate: $startDate
                    endDate: $endDate
                    status: "active"
                    autoRenew: true
                  ) { id name status }
                }
                """,
                variables={
                    "companyId": ids["company_a"],
                    "name": f"{SMOKE_MARKER} MSA",
                    "startDate": contract_start,
                    "endDate": contract_end,
                },
                token=admin_token,
            )
            ids["contract"] = data["createContract"]["id"]
            report.add("Phase 6", "createContract", "PASS", ids["contract"])
        except Exception as exc:
            report.add("Phase 6", "createContract", "FAIL", str(exc))

        if ids.get("contract"):
            try:
                data = await gql(
                    client,
                    "query($companyId: ID!) { contracts(companyId: $companyId) { id name status } }",
                    variables={"companyId": ids["company_a"]},
                    token=admin_token,
                )
                assert any(c["id"] == ids["contract"] for c in data["contracts"])
                report.add("Phase 6", "contracts query", "PASS")
            except Exception as exc:
                report.add("Phase 6", "contracts query", "FAIL", str(exc))

            try:
                data = await gql(
                    client,
                    """
                    mutation($id: ID!, $name: String!) {
                      updateContract(id: $id, name: $name, value: 50000) { id name value status }
                    }
                    """,
                    variables={"id": ids["contract"], "name": f"{SMOKE_MARKER} MSA Updated"},
                    token=admin_token,
                )
                assert data["updateContract"]["name"].endswith("Updated")
                assert float(data["updateContract"]["value"]) == 50000.0
                report.add("Phase 6", "updateContract", "PASS")
            except Exception as exc:
                report.add("Phase 6", "updateContract", "FAIL", str(exc))

        # Renewal sequence + contract in window
        try:
            data = await gql(
                client,
                """
                mutation($name: String!) {
                  createRetentionSequence(name: $name, triggerType: "on_renewal_approaching") { id }
                }
                """,
                variables={"name": f"{SMOKE_MARKER} Renewal Seq"},
                token=admin_token,
            )
            ids["renewal_sequence"] = data["createRetentionSequence"]["id"]
            await gql(
                client,
                """
                mutation($sequenceId: ID!) {
                  addSequenceStep(sequenceId: $sequenceId, channel: "email", offsetDays: 0) { id }
                }
                """,
                variables={"sequenceId": ids["renewal_sequence"]},
                token=admin_token,
            )
            renewal_end = (date.today() + timedelta(days=14)).isoformat()
            data = await gql(
                client,
                """
                mutation($companyId: ID!, $name: String!, $startDate: Date!, $endDate: Date!) {
                  createContract(
                    companyId: $companyId
                    name: $name
                    startDate: $startDate
                    endDate: $endDate
                    status: "active"
                  ) { id endDate }
                }
                """,
                variables={
                    "companyId": ids["company_a"],
                    "name": f"{SMOKE_MARKER} Renewal Contract",
                    "startDate": contract_start,
                    "endDate": renewal_end,
                },
                token=admin_token,
            )
            ids["renewal_contract"] = data["createContract"]["id"]
            from app.scheduler.jobs import contract_renewal_check

            renewal_result = await contract_renewal_check(run_date=date.today())
            assert renewal_result["enrollments_created"] >= 1
            async with get_tenant_db(setup["org_id"]) as db:
                assert await has_active_enrollment_for_sequence(
                    db,
                    company_id=uuid.UUID(ids["company_a"]),
                    sequence_id=uuid.UUID(ids["renewal_sequence"]),
                )
            report.add(
                "Phase 6",
                "contractRenewalCheck",
                "PASS",
                f"enrolled={renewal_result['enrollments_created']}",
            )
        except Exception as exc:
            report.add("Phase 6", "contractRenewalCheck", "FAIL", str(exc))

        try:
            from app.scheduler.jobs import recalculate_health_scores

            result = await recalculate_health_scores(run_date=date.today())
            assert result["companies_scored"] >= 1
            report.add("Phase 6", "recalculateHealthScores", "PASS", f"scored={result['companies_scored']}")
        except Exception as exc:
            report.add("Phase 6", "recalculateHealthScores", "FAIL", str(exc))

        # Force at-risk scenario (direct service recalc bypasses job_runs idempotency)
        try:
            await gql(
                client,
                """
                mutation($companyId: ID!, $name: String!) {
                  createProject(
                    companyId: $companyId
                    name: $name
                    status: "active"
                    health: "delayed"
                  ) { id health status }
                }
                """,
                variables={
                    "companyId": ids["company_a"],
                    "name": f"{SMOKE_MARKER} At-Risk Project",
                },
                token=admin_token,
            )
            await gql(
                client,
                "mutation($id: ID!) { updateCompany(id: $id, status: \"paused\") { id status } }",
                variables={"id": ids["company_a"]},
                token=admin_token,
            )
            if ids.get("renewal_contract"):
                renewal_end = (date.today() + timedelta(days=14)).isoformat()
                await gql(
                    client,
                    "mutation($id: ID!, $endDate: Date!) { updateContract(id: $id, endDate: $endDate) { id endDate } }",
                    variables={"id": ids["renewal_contract"], "endDate": renewal_end},
                    token=admin_token,
                )

            from app.db.models.organization import Organization
            from app.graphql.health.service import recalculate_org_health_scores
            from app.graphql.org_settings import health_settings_from_dict

            async with get_tenant_db(setup["org_id"]) as db:
                org = await db.get(Organization, setup["org_id"])
                settings = health_settings_from_dict(org.settings if org else {})
                await recalculate_org_health_scores(db, org_settings=settings, include_ai=False)

            data = await gql(
                client,
                """
                query($companyId: ID!) {
                  healthScoreHistory(companyId: $companyId, limit: 5) { id score calculatedAt }
                  atRiskCompanies(threshold: 61) { id name healthScore }
                }
                """,
                variables={"companyId": ids["company_a"]},
                token=admin_token,
            )
            assert len(data["healthScoreHistory"]) >= 1
            latest_score = float(data["healthScoreHistory"][0]["score"])
            assert latest_score <= 60.0, f"score={latest_score}"
            at_risk_ids = [c["id"] for c in data["atRiskCompanies"]]
            assert ids["company_a"] in at_risk_ids, f"at_risk={at_risk_ids} score={latest_score}"
            report.add(
                "Phase 6",
                "atRiskCompanies below threshold",
                "PASS",
                f"score={latest_score}",
            )
        except Exception as exc:
            report.add("Phase 6", "atRiskCompanies below threshold", "FAIL", str(exc))

        try:
            from app.scheduler.jobs import weekly_digest_email

            digest_result = await weekly_digest_email(run_date=date.today())
            assert "emails_sent" in digest_result
            report.add(
                "Phase 6",
                "weeklyDigestEmail",
                "PASS",
                f"emails={digest_result['emails_sent']}",
            )
        except Exception as exc:
            report.add("Phase 6", "weeklyDigestEmail", "FAIL", str(exc))

        if ids.get("contract"):
            try:
                deleted = await gql(
                    client,
                    "mutation($id: ID!) { deleteContract(id: $id) }",
                    variables={"id": ids["contract"]},
                    token=admin_token,
                )
                assert deleted["deleteContract"] is True
                data = await gql(
                    client,
                    "query($companyId: ID!) { contracts(companyId: $companyId) { id } }",
                    variables={"companyId": ids["company_a"]},
                    token=admin_token,
                )
                assert not any(c["id"] == ids["contract"] for c in data["contracts"])
                report.add("Phase 6", "deleteContract", "PASS")
            except Exception as exc:
                report.add("Phase 6", "deleteContract", "FAIL", str(exc))

        try:
            data = await gql(
                client,
                """
                query($companyId: ID!) {
                  healthScoreHistory(companyId: $companyId, limit: 5) { id score calculatedAt }
                  atRiskCompanies { id name healthScore }
                }
                """,
                variables={"companyId": ids["company_a"]},
                token=admin_token,
            )
            assert len(data["healthScoreHistory"]) >= 1
            report.add(
                "Phase 6",
                "healthScoreHistory query",
                "PASS",
                f"history={len(data['healthScoreHistory'])}",
            )
        except Exception as exc:
            report.add("Phase 6", "healthScoreHistory query", "FAIL", str(exc))

        # --- Phase 7: invoices, audit, GROQ assist, 2FA ---
        try:
            data = await gql(
                client,
                """
                mutation($companyId: ID!, $projectId: ID!, $amount: Float!, $dueDate: Date!) {
                  createInvoice(
                    companyId: $companyId
                    projectId: $projectId
                    amount: $amount
                    dueDate: $dueDate
                    invoiceNumber: "SMOKE-INV-001"
                    status: "sent"
                  ) { id status amount invoiceNumber }
                }
                """,
                variables={
                    "companyId": ids["company_a"],
                    "projectId": ids["project"],
                    "amount": 2500.0,
                    "dueDate": (date.today() + timedelta(days=30)).isoformat(),
                },
                token=admin_token,
            )
            ids["invoice"] = data["createInvoice"]["id"]
            report.add("Phase 7", "createInvoice", "PASS", ids["invoice"])
        except Exception as exc:
            report.add("Phase 7", "createInvoice", "FAIL", str(exc))

        if ids.get("invoice"):
            try:
                data = await gql(
                    client,
                    """
                    query($companyId: ID!) {
                      invoices(companyId: $companyId) { id status amount }
                    }
                    """,
                    variables={"companyId": ids["company_a"]},
                    token=admin_token,
                )
                assert any(i["id"] == ids["invoice"] for i in data["invoices"])
                report.add("Phase 7", "invoices query", "PASS", f"count={len(data['invoices'])}")
            except Exception as exc:
                report.add("Phase 7", "invoices query", "FAIL", str(exc))

            try:
                paid = await gql(
                    client,
                    "mutation($id: ID!) { updateInvoice(id: $id, status: \"paid\") { id status paidAt } }",
                    variables={"id": ids["invoice"]},
                    token=admin_token,
                )
                assert paid["updateInvoice"]["status"] == "paid"
                report.add("Phase 7", "updateInvoice paid", "PASS")
            except Exception as exc:
                report.add("Phase 7", "updateInvoice paid", "FAIL", str(exc))

        try:
            logs = await gql(
                client,
                "query { activityLogs(limit: 20) { id action entityType } }",
                token=admin_token,
            )
            assert len(logs["activityLogs"]) >= 1
            report.add("Phase 7", "activityLogs query", "PASS", f"count={len(logs['activityLogs'])}")
        except Exception as exc:
            report.add("Phase 7", "activityLogs query", "FAIL", str(exc))

        try:
            resp = await client.get(
                "/exports/audit.csv",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200
            assert "entity_type" in resp.text.split("\n")[0]
            report.add("Phase 7", "audit CSV export", "PASS")
        except Exception as exc:
            report.add("Phase 7", "audit CSV export", "FAIL", str(exc))

        try:
            import pyotp

            totp_setup = await gql(
                client,
                "mutation { enableTotp { secret provisioningUri } }",
                token=admin_token,
            )
            secret = totp_setup["enableTotp"]["secret"]
            code = pyotp.TOTP(secret).now()
            confirmed = await gql(
                client,
                "mutation($code: String!) { confirmTotp(code: $code) }",
                variables={"code": code},
                token=admin_token,
            )
            assert confirmed["confirmTotp"] is True
            report.add("Phase 7", "enableTotp + confirmTotp", "PASS")
        except Exception as exc:
            report.add("Phase 7", "enableTotp + confirmTotp", "FAIL", str(exc))

        try:
            from unittest.mock import AsyncMock, patch

            data = await gql(
                client,
                """
                mutation($projectId: ID!) {
                  createChangeRequest(
                    projectId: $projectId
                    title: "GROQ draft test"
                    type: "scope_addition"
                  ) { id status }
                }
                """,
                variables={"projectId": ids["project"]},
                token=admin_token,
            )
            draft_cr_id = data["createChangeRequest"]["id"]
            await gql(
                client,
                "mutation($id: ID!) { transitionChangeRequest(id: $id, toStatus: \"under_review\") { id status } }",
                variables={"id": draft_cr_id},
                token=admin_token,
            )
            groq_payload = (
                '{"impact_hours": 8, "impact_cost": 1200, "impact_timeline_days": 5, '
                '"assessment_notes": "Smoke advisory draft"}'
            )
            with patch(
                "app.graphql.change_requests.ai_assist.generate_text",
                new_callable=AsyncMock,
                return_value=groq_payload,
            ):
                draft = await gql(
                    client,
                    "mutation($id: ID!) { draftImpactAssessment(id: $id) { advisory impactHours assessmentNotes } }",
                    variables={"id": draft_cr_id},
                    token=admin_token,
                )
            assert draft["draftImpactAssessment"]["advisory"] is True
            assert draft["draftImpactAssessment"]["impactHours"] == 8.0
            report.add("Phase 7", "draftImpactAssessment", "PASS")
        except Exception as exc:
            report.add("Phase 7", "draftImpactAssessment", "FAIL", str(exc))

        try:
            from app.scheduler.jobs import flag_overdue_invoices

            inv_result = await flag_overdue_invoices(run_date=date.today())
            assert "flagged" in inv_result
            report.add("Phase 7", "flagOverdueInvoices job", "PASS", f"flagged={inv_result['flagged']}")
        except Exception as exc:
            report.add("Phase 7", "flagOverdueInvoices job", "FAIL", str(exc))

        try:
            errors = await gql_expect_error(
                client,
                "query { invoices { id } }",
                token=portal_token,
            )
            code = (errors[0].get("extensions") or {}).get("code", "")
            assert code in ("authentication_error", "authorization_error")
            report.add("Security", "portal cannot list invoices", "PASS", code)
        except Exception as exc:
            report.add("Security", "portal cannot list invoices", "FAIL", str(exc))

        # --- Phase 4 + Security: negative cases ---
        from sqlalchemy import select

        from app.core.db import get_tenant_db
        from app.db.enums import EntityType
        from app.db.models.approval import Approval

        try:
            data = await gql(
                client,
                """
                mutation($companyId: ID!, $name: String!) {
                  createProject(companyId: $companyId, name: $name, status: "active") { id }
                }
                """,
                variables={"companyId": ids["company_a"], "name": f"{SMOKE_MARKER} CR Test Project"},
                token=admin_token,
            )
            cr_project = data["createProject"]["id"]
            data = await gql(
                client,
                """
                mutation($projectId: ID!) {
                  createChangeRequest(
                    projectId: $projectId
                    title: "Illegal transition test"
                    type: "bugfix"
                  ) { id status }
                }
                """,
                variables={"projectId": cr_project},
                token=admin_token,
            )
            test_cr_id = data["createChangeRequest"]["id"]
            errors = await gql_expect_error(
                client,
                """
                mutation($id: ID!) {
                  transitionChangeRequest(id: $id, toStatus: "approved") { id }
                }
                """,
                variables={"id": test_cr_id},
                token=admin_token,
            )
            code = (errors[0].get("extensions") or {}).get("code", "")
            assert code == "invalid_transition"
            report.add("Security", "illegal CR transition rejected", "PASS", code)
        except Exception as exc:
            report.add("Security", "illegal CR transition rejected", "FAIL", str(exc))

        if portal_token and ids.get("cr_internal_approval"):
            try:
                # Create fresh CR with internal-only pending approval
                data = await gql(
                    client,
                    """
                    mutation($projectId: ID!) {
                      createChangeRequest(
                        projectId: $projectId
                        title: "Internal only CR"
                        type: "bugfix"
                      ) { id }
                    }
                    """,
                    variables={"projectId": ids["project"]},
                    token=admin_token,
                )
                iocr_id = data["createChangeRequest"]["id"]
                await gql(
                    client,
                    "mutation($id: ID!) { transitionChangeRequest(id: $id, toStatus: \"under_review\") { id } }",
                    variables={"id": iocr_id},
                    token=admin_token,
                )
                await gql(
                    client,
                    """
                    mutation($id: ID!) {
                      submitImpactAssessment(id: $id, impactCost: 9000, impactTimelineDays: 10) { id }
                    }
                    """,
                    variables={"id": iocr_id},
                    token=admin_token,
                )
                async with get_tenant_db(setup["org_id"]) as db:
                    result = await db.execute(
                        select(Approval).where(
                            Approval.entity_type == EntityType.CHANGE_REQUEST.value,
                            Approval.entity_id == uuid.UUID(iocr_id),
                            Approval.approver_type == "internal",
                        )
                    )
                    internal_only = str(result.scalar_one().id)
                errors = await gql_expect_error(
                    client,
                    """
                    mutation($id: ID!, $approvalId: ID!) {
                      decideChangeRequest(id: $id, approvalId: $approvalId, decision: "approved") { id }
                    }
                    """,
                    variables={"id": iocr_id, "approvalId": internal_only},
                    token=portal_token,
                )
                code = (errors[0].get("extensions") or {}).get("code", "")
                assert code == "authorization_error"
                report.add("Security", "portal cannot resolve internal approval", "PASS", code)
            except Exception as exc:
                report.add("Security", "portal cannot resolve internal approval", "FAIL", str(exc))

        # --- Deletes (soft CRUD cleanup path) ---
        try:
            await gql(
                client,
                "mutation($id: ID!) { removeTaskDependency(id: $id) }",
                variables={"id": ids["dependency"]},
                token=admin_token,
            )
            report.add("Phase 2", "removeTaskDependency", "PASS")
        except Exception as exc:
            report.add("Phase 2", "removeTaskDependency", "WARN", str(exc))

        try:
            await gql(
                client,
                """
                mutation($entityId: ID!, $tagId: ID!) {
                  removeTag(entityType: "company", entityId: $entityId, tagId: $tagId)
                }
                """,
                variables={"entityId": ids["company_a"], "tagId": ids["tag"]},
                token=admin_token,
            )
            report.add("Phase 1", "removeTag", "PASS")
        except Exception as exc:
            report.add("Phase 1", "removeTag", "WARN", str(exc))

        try:
            await gql(client, "mutation { logout }", token=admin_token)
            report.add("Phase 1", "logout", "PASS")
        except Exception as exc:
            report.add("Phase 1", "logout", "WARN", str(exc))

    # Hard cleanup all smoke org data
    try:
        await cleanup_smoke_data(report, setup["org_id"], asset_paths)
    except Exception as exc:
        report.add("Cleanup", "database_and_assets", "FAIL", str(exc))


def print_summary(report: SmokeReport) -> None:
    report.finished_at = datetime.now(UTC).isoformat()
    print("\n" + "=" * 72)
    print("SMOKE TEST SUMMARY")
    print("=" * 72)
    print(f"Run ID:     {report.run_id}")
    print(f"Org ID:     {report.org_id} (deleted)")
    print(f"Passed:     {report.passed}")
    print(f"Failed:     {report.failed}")
    print(f"Warnings:   {report.warned}")
    print(f"Skipped:    {sum(1 for s in report.steps if s.status == 'SKIP')}")
    print(f"Finished:   {report.finished_at}")
    if report.failed:
        print("\nFailures:")
        for step in report.steps:
            if step.status == "FAIL":
                print(f"  - {step.category} / {step.name}: {step.detail}")
    print("=" * 72)

    out_path = BACKEND_ROOT / f"smoke_report_{RUN_ID}.json"
    out_path.write_text(
        json.dumps(
            {
                "run_id": report.run_id,
                "org_id": report.org_id,
                "started_at": report.started_at,
                "finished_at": report.finished_at,
                "passed": report.passed,
                "failed": report.failed,
                "warned": report.warned,
                "steps": [s.__dict__ for s in report.steps],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Report saved: {out_path}")


async def main() -> int:
    print("=" * 72)
    print(f"Agency CRM Full Smoke Test — {RUN_ID}")
    print("=" * 72)

    # Preflight: assets folder
    try:
        from scripts.check_assets_storage import main as check_assets

        if check_assets() != 0:
            print("ERROR: Shared assets folder is not writable. Fix ASSETS_ROOT_PATH first.")
            return 1
    except Exception as exc:
        print(f"WARN: Could not verify assets folder: {exc}")

    report = SmokeReport()
    try:
        await run_smoke(report)
    except SmokeFailure as exc:
        report.add("Fatal", "aborted", "FAIL", str(exc))
    print_summary(report)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
