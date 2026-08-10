"""Advisory GROQ draft for AI-generated retention sequences — saved as pending for PM approval."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError, NotFoundError
from app.db.enums import EnrollmentStatus, SequenceTriggerType
from app.db.models.company import Company
from app.db.models.contact import Contact
from app.db.models.project import Project
from app.db.models.retention import RetentionEnrollment, RetentionSequence, Touchpoint
from app.db.models.user import User
from app.graphql.retention.eligibility import (
    RETENTION_CHANNELS,
    assert_company_retention_eligible,
)
from app.integrations.groq_client import generate_text


@dataclass(frozen=True)
class GeneratedSequenceStep:
    name: str
    channel: str
    offset_days: int
    assignee_role: str | None
    action_message: str | None


@dataclass(frozen=True)
class GeneratedSequenceDraft:
    name: str
    description: str | None
    trigger_type: str
    strategy_summary: str | None
    steps: list[GeneratedSequenceStep]


def _extract_json_block(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _parse_step(raw: dict, index: int) -> GeneratedSequenceStep:
    channel = str(raw.get("channel") or "call").lower().replace("-", "_")
    if channel not in RETENTION_CHANNELS:
        channel = "call"
    offset = raw.get("offset_days", index * 7)
    try:
        offset_days = max(0, int(offset))
    except (TypeError, ValueError):
        offset_days = index * 7
    role = raw.get("assignee_role")
    assignee_role = str(role).lower().replace("-", "_") if role else None
    return GeneratedSequenceStep(
        name=str(raw.get("name") or f"Step {index + 1}").strip()[:255],
        channel=channel,
        offset_days=offset_days,
        assignee_role=assignee_role,
        action_message=str(raw.get("action_message")).strip() if raw.get("action_message") else None,
    )


def _parse_draft(payload: dict) -> GeneratedSequenceDraft:
    steps_raw = payload.get("steps") or []
    if not isinstance(steps_raw, list) or not steps_raw:
        raise DomainError("AI response did not include sequence steps", code="validation_error")
    steps = [_parse_step(step, index) for index, step in enumerate(steps_raw)]
    trigger = str(payload.get("trigger_type") or SequenceTriggerType.ON_PROJECT_COMPLETED.value).lower().replace("-", "_")
    if trigger not in {SequenceTriggerType.MANUAL.value, SequenceTriggerType.ON_PROJECT_COMPLETED.value}:
        trigger = SequenceTriggerType.ON_PROJECT_COMPLETED.value
    return GeneratedSequenceDraft(
        name=str(payload.get("name") or "Post-project retention sequence").strip()[:255],
        description=str(payload.get("description")).strip() if payload.get("description") else None,
        trigger_type=trigger,
        strategy_summary=str(payload.get("strategy_summary")).strip() if payload.get("strategy_summary") else None,
        steps=steps,
    )


async def _gather_company_context(db: AsyncSession, *, company_id: UUID, org_id: UUID) -> str:
    company = await db.get(Company, company_id)
    if company is None or company.deleted_at is not None or company.org_id != org_id:
        raise NotFoundError("Company not found")

    contacts_result = await db.execute(
        select(Contact)
        .where(Contact.company_id == company_id, Contact.deleted_at.is_(None))
        .order_by(Contact.is_primary.desc(), Contact.first_name.asc())
    )
    contacts = list(contacts_result.scalars().all())

    projects_result = await db.execute(
        select(Project)
        .where(Project.company_id == company_id, Project.deleted_at.is_(None))
        .order_by(Project.updated_at.desc())
        .limit(20)
    )
    projects = list(projects_result.scalars().all())

    touchpoints_result = await db.execute(
        select(Touchpoint)
        .where(Touchpoint.company_id == company_id)
        .order_by(Touchpoint.scheduled_at.desc())
        .limit(15)
    )
    touchpoints = list(touchpoints_result.scalars().all())

    enrollments_result = await db.execute(
        select(RetentionEnrollment, RetentionSequence)
        .join(RetentionSequence, RetentionEnrollment.sequence_id == RetentionSequence.id)
        .where(
            RetentionEnrollment.company_id == company_id,
            RetentionEnrollment.status == EnrollmentStatus.ACTIVE.value,
        )
    )
    enrollments = list(enrollments_result.all())

    lines = [
        f"Company: {company.name}",
        f"Industry: {company.industry or 'unknown'}",
        f"Status: {company.status}",
        f"Health score: {float(company.health_score) if company.health_score is not None else 'unknown'}",
        "",
        "Context: All delivery projects are complete. Design post-project retention follow-ups only.",
        "",
        "Contacts:",
    ]
    if contacts:
        for contact in contacts[:10]:
            lines.append(
                f"- {contact.first_name} {contact.last_name}"
                f"{' (primary)' if contact.is_primary else ''}"
                f", preferred channel: {contact.preferred_channel or 'unknown'}"
            )
    else:
        lines.append("- none on file")

    lines.extend(["", "Completed projects:"])
    completed = [p for p in projects if p.status == "completed"]
    if completed:
        for project in completed:
            lines.append(f"- {project.name}")
    else:
        lines.append("- none")

    lines.extend(["", "Recent retention touchpoints (call/email only):"])
    if touchpoints:
        for tp in touchpoints:
            lines.append(
                f"- {tp.type} on {tp.scheduled_at.date().isoformat()}: status={tp.status}, outcome={tp.outcome or 'n/a'}"
            )
    else:
        lines.append("- none recorded")

    lines.extend(["", "Active retention enrollments:"])
    if enrollments:
        for enrollment, sequence in enrollments:
            lines.append(f"- {sequence.name} (step {enrollment.current_step})")
    else:
        lines.append("- none")

    return "\n".join(lines)


async def draft_retention_sequence(
    db: AsyncSession,
    *,
    actor: User,
    company_id: UUID,
) -> GeneratedSequenceDraft:
    await assert_company_retention_eligible(db, company_id)
    context = await _gather_company_context(db, company_id=company_id, org_id=actor.org_id)
    prompt = (
        "You are an advisory assistant for post-project client retention in a CRM. "
        "The client's delivery work is finished — propose a follow-up sequence using ONLY "
        "phone calls and emails to maintain the relationship and prevent churn. "
        "Do NOT include meetings, QBRs, workshops, internal tasks, or any project delivery work.\n"
        "Return ONLY valid JSON with keys:\n"
        "name (string), description (string), "
        "trigger_type (prefer 'on_project_completed' or 'manual'), "
        "strategy_summary (string explaining the post-delivery retention approach), "
        "steps (array of objects with: name, channel, offset_days, assignee_role, action_message).\n"
        "channel must be ONLY 'email' or 'call'.\n"
        "assignee_role must be one of: project_manager, team_member, admin, or null.\n"
        "offset_days must be non-decreasing integers starting at 0.\n"
        "Include 3-6 steps with realistic gaps (e.g. day 0 check-in call, day 7 thank-you email, day 30 feedback call).\n"
        "action_message should be concise talking points or email draft text.\n"
        "Do not include markdown.\n\n"
        f"Client data:\n{context}\n"
    )
    raw = await generate_text(prompt, timeout=20)
    if not raw:
        raise DomainError("AI generation is unavailable right now. Try again later.", code="service_unavailable")
    payload = _extract_json_block(raw)
    if payload is None:
        raise DomainError("AI returned an invalid response. Try again.", code="validation_error")
    return _parse_draft(payload)
