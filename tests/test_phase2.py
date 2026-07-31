import uuid

import pytest
from graphql import GraphQLError

from app.core.db import AsyncSessionLocal, get_tenant_db
from app.core.exceptions import DomainError
from app.db.models.company import Company
from app.core.security import hash_password
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.planning import Milestone, ProjectPhase, Task, TaskDependency
from app.db.models.project import Project
from app.graphql.planning.repository import reorder_milestone_indices, reorder_phase_indices, validate_dependency_insert
from app.graphql.planning.service import add_task_dependency_record, get_workload_rows


async def _seed_project_tree(org_id: uuid.UUID) -> dict:
    company_id = uuid.uuid4()
    project_id = uuid.uuid4()
    phase_id = uuid.uuid4()
    task_a = uuid.uuid4()
    task_b = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(Organization(id=org_id, name=f"Org {org_id.hex[:8]}", plan="trial", settings={}))

    async with get_tenant_db(org_id) as db:
        db.add(Company(id=company_id, org_id=org_id, name="Co", status="active"))
        db.add(
            Project(
                id=project_id,
                org_id=org_id,
                company_id=company_id,
                name="Proj",
                status="planning",
            )
        )
        db.add(
            ProjectPhase(
                id=phase_id,
                org_id=org_id,
                project_id=project_id,
                name="Phase 1",
                order_index=0,
                status="not_started",
            )
        )
        db.add(
            Task(
                id=task_a,
                org_id=org_id,
                project_id=project_id,
                phase_id=phase_id,
                title="Task A",
                status="todo",
                priority="medium",
                estimated_hours=5,
                actual_hours=2,
            )
        )
        db.add(
            Task(
                id=task_b,
                org_id=org_id,
                project_id=project_id,
                phase_id=phase_id,
                title="Task B",
                status="in_progress",
                priority="high",
                estimated_hours=3,
                actual_hours=1,
            )
        )

    return {
        "org_id": org_id,
        "project_id": project_id,
        "phase_id": phase_id,
        "task_a": task_a,
        "task_b": task_b,
    }


@pytest.mark.asyncio
async def test_dependency_cycle_rejected():
    org_id = uuid.uuid4()
    data = await _seed_project_tree(org_id)

    async with get_tenant_db(org_id) as db:
        with pytest.raises(DomainError) as self_dep:
            await validate_dependency_insert(
                db,
                project_id=data["project_id"],
                task_id=data["task_a"],
                depends_on_task_id=data["task_a"],
            )
        assert self_dep.value.code == "dependency_cycle"

        await add_task_dependency_record(
            db,
            actor=type("U", (), {"org_id": org_id, "id": uuid.uuid4()})(),
            project_id=data["project_id"],
            task_id=data["task_a"],
            depends_on_task_id=data["task_b"],
        )

        with pytest.raises(DomainError) as cycle:
            await validate_dependency_insert(
                db,
                project_id=data["project_id"],
                task_id=data["task_b"],
                depends_on_task_id=data["task_a"],
            )
        assert cycle.value.code == "dependency_cycle"


@pytest.mark.asyncio
async def test_reorder_phases_exact_set_required():
    org_id = uuid.uuid4()
    data = await _seed_project_tree(org_id)
    phase2 = uuid.uuid4()

    async with get_tenant_db(org_id) as db:
        db.add(
            ProjectPhase(
                id=phase2,
                org_id=org_id,
                project_id=data["project_id"],
                name="Phase 2",
                order_index=1,
                status="not_started",
            )
        )
        await db.flush()

        with pytest.raises(DomainError):
            await reorder_phase_indices(db, data["project_id"], [data["phase_id"]])

        reordered = await reorder_phase_indices(db, data["project_id"], [phase2, data["phase_id"]])
        assert [p.order_index for p in reordered] == [0, 1]
        assert [p.id for p in reordered] == [phase2, data["phase_id"]]


@pytest.mark.asyncio
async def test_workload_aggregate():
    org_id = uuid.uuid4()
    assignee_id = uuid.uuid4()
    data = await _seed_project_tree(org_id)

    async with get_tenant_db(org_id) as db:
        db.add(
            User(
                id=assignee_id,
                org_id=org_id,
                name="Assignee",
                email=f"{assignee_id.hex[:8]}@example.com",
                password_hash=hash_password("ChangeMe123!"),
                role="team_member",
                status="active",
            )
        )
        await db.flush()
        task_a = await db.get(Task, data["task_a"])
        task_b = await db.get(Task, data["task_b"])
        task_a.assignee_id = assignee_id
        task_b.assignee_id = assignee_id
        await db.flush()

        rows = await get_workload_rows(db, project_id=data["project_id"])
        assert len(rows) == 1
        assert rows[0]["total_estimated_hours"] == 8.0
        assert rows[0]["total_actual_hours"] == 3.0
        assert rows[0]["open_task_count"] == 2
