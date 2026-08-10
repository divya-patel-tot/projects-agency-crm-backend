"""Seed completed projects for retention testing — The One Technologies org.

Run: python scripts/seed_retention_test_data.py
Optional: SEED_ADMIN_EMAIL=divyeshgohil123@gmail.com
"""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import select, text

from app.core.bootstrap import bootstrap_env

bootstrap_env()

from app.core.db import get_auth_db, get_tenant_db  # noqa: E402
from app.db.enums import (  # noqa: E402
    CompanyStatus,
    ContactStatus,
    Currency,
    MilestoneStatus,
    PhaseStatus,
    ProjectHealth,
    ProjectStatus,
    TaskStatus,
)
from app.db.models.company import Company  # noqa: E402
from app.db.models.contact import Contact  # noqa: E402
from app.db.models.planning import Milestone, ProjectPhase, Task  # noqa: E402
from app.db.models.project import Project  # noqa: E402
from app.db.models.project_member import ProjectMember  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.graphql.retention.eligibility import get_company_retention_eligibility  # noqa: E402

DEFAULT_EMAIL = "divyeshgohil123@gmail.com"


def _target_email() -> str:
    import os
    import sys

    if len(sys.argv) > 1:
        return sys.argv[1].strip()
    return os.environ.get("SEED_TARGET_EMAIL") or DEFAULT_EMAIL

# Existing IDs from inspect (idempotent updates)
DR_JO_COMPANY_ID = UUID("e9bc47ed-a354-4b2a-9201-54a5b9329d70")
GEORGE_COMPANY_ID = UUID("5c5d61c1-fa06-47c2-a261-ef18fe681cf0")
SUBRAT_PROJECT_ID = UUID("0a5f78bd-5430-4b29-b03c-671617cfb8b9")
MY_BUDDY_PROJECT_ID = UUID("92a917a1-43fb-4761-9e16-e44710bac4d6")
KALIMERA_PROJECT_ID = UUID("dec0063a-54bd-4411-ab11-fa1ab7c9f87b")


async def _find_admin(email: str) -> tuple[User, UUID]:
    async with get_auth_db() as session:
        result = await session.execute(
            select(User).where(User.email == email, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise SystemExit(f"Admin user not found: {email}")
        return user, user.org_id


async def _ensure_primary_contact(
    session,
    *,
    org_id: UUID,
    company_id: UUID,
    first_name: str,
    last_name: str,
    email: str,
    phone: str | None = None,
    title: str | None = None,
) -> Contact:
    result = await session.execute(
        select(Contact).where(
            Contact.company_id == company_id,
            Contact.deleted_at.is_(None),
            Contact.is_primary.is_(True),
        )
    )
    contact = result.scalar_one_or_none()
    if contact:
        contact.first_name = first_name
        contact.last_name = last_name
        contact.email = email
        contact.phone = phone
        contact.title = title
        contact.preferred_channel = "call"
        return contact

    contact = Contact(
        org_id=org_id,
        company_id=company_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        title=title,
        is_primary=True,
        preferred_channel="call",
        status=ContactStatus.ACTIVE.value,
    )
    session.add(contact)
    await session.flush()
    return contact


async def _ensure_project_member(session, *, org_id: UUID, project_id: UUID, user_id: UUID) -> None:
    existing = await session.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if existing.scalar_one_or_none():
        return
    session.add(ProjectMember(org_id=org_id, project_id=project_id, user_id=user_id))


async def _add_completed_structure(
    session,
    *,
    org_id: UUID,
    project_id: UUID,
    pm_user_id: UUID,
    phases: list[tuple[str, list[tuple[str, list[str]]]]],
    start: date,
    end: date,
) -> None:
    """phases: [(phase_name, [(milestone_title, [task_titles])])]"""
    existing = await session.execute(
        select(ProjectPhase.id).where(
            ProjectPhase.project_id == project_id,
            ProjectPhase.deleted_at.is_(None),
        )
    )
    if existing.first():
        return

    span_days = max((end - start).days, 1)
    for phase_index, (phase_name, milestones) in enumerate(phases):
        phase_start = start
        phase_end = end
        phase = ProjectPhase(
            org_id=org_id,
            project_id=project_id,
            name=phase_name,
            order_index=phase_index,
            start_date=phase_start,
            due_date=phase_end,
            status=PhaseStatus.COMPLETED.value,
        )
        session.add(phase)
        await session.flush()

        for ms_index, (ms_title, task_titles) in enumerate(milestones):
            milestone = Milestone(
                org_id=org_id,
                phase_id=phase.id,
                title=ms_title,
                description=f"Delivered as part of {phase_name.lower()}.",
                due_date=end,
                status=MilestoneStatus.COMPLETED.value,
                requires_client_approval=ms_index == len(milestones) - 1,
                order_index=ms_index,
            )
            session.add(milestone)
            await session.flush()

            for task_index, task_title in enumerate(task_titles):
                session.add(
                    Task(
                        org_id=org_id,
                        project_id=project_id,
                        phase_id=phase.id,
                        milestone_id=milestone.id,
                        title=task_title,
                        description="Completed during delivery.",
                        assignee_id=pm_user_id,
                        status=TaskStatus.DONE.value,
                        start_date=start,
                        due_date=end,
                        estimated_hours=8,
                        actual_hours=7.5,
                    )
                )


async def _complete_project(
    session,
    project: Project,
    *,
    name: str,
    description: str,
    start: date,
    end: date,
    budget: float,
    actual_cost: float,
    pm_user_id: UUID,
    phases: list[tuple[str, list[tuple[str, list[str]]]]],
) -> None:
    project.name = name
    project.description = description
    project.status = ProjectStatus.COMPLETED.value
    project.health = ProjectHealth.ON_TRACK.value
    project.start_date = start
    project.end_date = end
    project.budget = budget
    project.actual_cost = actual_cost
    project.currency = Currency.GBP.value
    project.project_manager_id = pm_user_id
    await _ensure_project_member(
        session, org_id=project.org_id, project_id=project.id, user_id=pm_user_id
    )
    await _add_completed_structure(
        session,
        org_id=project.org_id,
        project_id=project.id,
        pm_user_id=pm_user_id,
        phases=phases,
        start=start,
        end=end,
    )


async def seed() -> None:
    email = _target_email()
    admin, org_id = await _find_admin(email)
    print(f"Seeding retention test data for org {org_id} (admin: {admin.email})")

    async with get_tenant_db(org_id, user_id=admin.id, role=admin.role) as session:
        # --- Dr Jo Whitaker ---
        dr_jo = await session.get(Company, DR_JO_COMPANY_ID)
        if dr_jo is None:
            raise SystemExit("Dr Jo Whitaker company not found")

        dr_jo.status = CompanyStatus.ACTIVE.value
        dr_jo.account_owner_id = admin.id
        dr_jo.health_score = 68
        dr_jo.website = dr_jo.website or "https://crystalwaterexperience.com"
        dr_jo.size = dr_jo.size or "51-200"

        await _ensure_primary_contact(
            session,
            org_id=org_id,
            company_id=dr_jo.id,
            first_name="Jo",
            last_name="Whitaker",
            email="jo.whitaker@crystalwaterexperience.com",
            phone="+44 7700 900123",
            title="Managing Director",
        )

        subrat = await session.get(Project, SUBRAT_PROJECT_ID)
        if subrat:
            await _complete_project(
                session,
                subrat,
                name="Crystal Water Experience Platform",
                description=(
                    "End-to-end e-commerce and tour booking platform with CRM integration, "
                    "payment gateway, and multilingual content — delivered and handed over Q1 2026."
                ),
                start=date(2025, 9, 15),
                end=date(2026, 3, 10),
                budget=45000,
                actual_cost=43250,
                pm_user_id=admin.id,
                phases=[
                    (
                        "Discovery & Design",
                        [
                            ("Requirements sign-off", ["Stakeholder workshops", "UX wireframes"]),
                            ("Visual design approved", ["Brand application", "Prototype review"]),
                        ],
                    ),
                    (
                        "Build & Integrate",
                        [
                            ("Core platform live on staging", ["Booking engine", "Payment integration"]),
                            ("CRM & email automation", ["HubSpot sync", "Transactional emails"]),
                        ],
                    ),
                    (
                        "Launch & Handover",
                        [
                            ("Production launch", ["Go-live checklist", "Staff training"]),
                            ("Post-launch support window", ["Bug fixes", "Performance tuning"]),
                        ],
                    ),
                ],
            )
            print(f"  [OK] Completed project: {subrat.name} ({subrat.id})")

        # --- George Chalkiadakis ---
        george_co = await session.get(Company, GEORGE_COMPANY_ID)
        if george_co:
            george_co.status = CompanyStatus.ACTIVE.value
            george_co.account_owner_id = admin.id
            george_co.health_score = 55
            george_co.industry = george_co.industry or "Technology & Software"

            my_buddy = await session.get(Project, MY_BUDDY_PROJECT_ID)
            if my_buddy:
                await _complete_project(
                    session,
                    my_buddy,
                    name="My Buddy — Care Companion MVP",
                    description=(
                        "Mobile-first care companion app for family check-ins, medication reminders, "
                        "and carer notifications. MVP shipped to App Store and Google Play."
                    ),
                    start=date(2025, 11, 1),
                    end=date(2026, 2, 28),
                    budget=28000,
                    actual_cost=26500,
                    pm_user_id=admin.id,
                    phases=[
                        (
                            "Product & UX",
                            [
                                ("MVP scope locked", ["User journeys", "Accessibility review"]),
                            ],
                        ),
                        (
                            "Engineering",
                            [
                                ("iOS & Android builds", ["Push notifications", "Offline mode"]),
                                ("Backend API", ["Auth", "Reminder scheduler"]),
                            ],
                        ),
                        (
                            "Release",
                            [
                                ("Store submission", ["App Store review", "Play Store release"]),
                            ],
                        ),
                    ],
                )
                print(f"  [OK] Completed project: {my_buddy.name} ({my_buddy.id})")

            kalimera = await session.get(Project, KALIMERA_PROJECT_ID)
            if kalimera and kalimera.status != ProjectStatus.COMPLETED.value:
                kalimera.status = ProjectStatus.CANCELLED.value
                kalimera.description = (
                    "AI concierge prototype — deprioritised after My Buddy MVP launch. "
                    "Scope may revisit in a future phase."
                )
                print(f"  [OK] Cancelled in-progress project: {kalimera.name}")

        # --- New client: retention-ready from day one ---
        existing = await session.execute(
            select(Company).where(Company.name == "Northwind Analytics", Company.deleted_at.is_(None))
        )
        northwind = existing.scalar_one_or_none()
        if northwind is None:
            northwind = Company(
                org_id=org_id,
                name="Northwind Analytics",
                industry="Professional Services",
                website="https://northwind-analytics.example.com",
                size="11-50",
                timezone="Europe/London",
                status=CompanyStatus.ACTIVE.value,
                account_owner_id=admin.id,
                health_score=52,
            )
            session.add(northwind)
            await session.flush()
            print(f"  [OK] Created company: Northwind Analytics ({northwind.id})")

            await _ensure_primary_contact(
                session,
                org_id=org_id,
                company_id=northwind.id,
                first_name="Sarah",
                last_name="Chen",
                email="sarah.chen@northwind-analytics.example.com",
                phone="+44 7700 900456",
                title="Head of Client Success",
            )

            nw_project = Project(
                org_id=org_id,
                company_id=northwind.id,
                name="Client Health Dashboard",
                description=(
                    "Bespoke analytics dashboard for account managers — health scores, "
                    "contract renewals, and engagement metrics. Delivered and signed off."
                ),
                status=ProjectStatus.COMPLETED.value,
                health=ProjectHealth.ON_TRACK.value,
                start_date=date(2025, 6, 1),
                end_date=date(2025, 11, 30),
                budget=18500,
                actual_cost=17800,
                currency=Currency.GBP.value,
                project_manager_id=admin.id,
            )
            session.add(nw_project)
            await session.flush()
            await _ensure_project_member(
                session, org_id=org_id, project_id=nw_project.id, user_id=admin.id
            )
            await _add_completed_structure(
                session,
                org_id=org_id,
                project_id=nw_project.id,
                pm_user_id=admin.id,
                phases=[
                    (
                        "Delivery",
                        [
                            ("Dashboard MVP", ["Data pipeline", "UI build"]),
                            ("Client training", ["Workshops", "Documentation"]),
                        ],
                    ),
                ],
                start=date(2025, 6, 1),
                end=date(2025, 11, 30),
            )
            print(f"  [OK] Created completed project: {nw_project.name} ({nw_project.id})")
        else:
            print(f"  - Northwind Analytics already exists ({northwind.id})")

    # Verify retention eligibility
    async with get_tenant_db(org_id, user_id=admin.id, role=admin.role) as session:
        for company_id, label in [
            (DR_JO_COMPANY_ID, "Dr Jo Whitaker"),
            (GEORGE_COMPANY_ID, "George Chalkiadakis"),
        ]:
            eligibility = await get_company_retention_eligibility(session, company_id)
            status = "UNLOCKED" if eligibility.eligible else "LOCKED"
            print(f"\n  Retention [{label}]: {status}")
            if eligibility.reason:
                print(f"    {eligibility.reason}")
            print(
                f"    completed={eligibility.completed_project_count}, "
                f"incomplete={eligibility.incomplete_project_count}"
            )

        nw = await session.execute(
            select(Company.id).where(
                Company.name == "Northwind Analytics",
                Company.deleted_at.is_(None),
            )
        )
        nw_id = nw.scalar_one_or_none()
        if nw_id:
            eligibility = await get_company_retention_eligibility(session, nw_id)
            print(f"\n  Retention [Northwind Analytics]: {'UNLOCKED' if eligibility.eligible else 'LOCKED'}")

    print("\nDone — log in and open Retention to test enrollments and AI sequences.")


if __name__ == "__main__":
    asyncio.run(seed())
