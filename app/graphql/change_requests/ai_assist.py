"""Advisory GROQ draft for change request impact assessment — never auto-applied."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, DomainError, NotFoundError
from app.db.enums import ChangeRequestStatus
from app.db.models.user import User
from app.graphql.change_requests.repository import get_change_request
from app.graphql.projects.service import actor_can_mutate_project
from app.integrations.groq_client import generate_text


@dataclass(frozen=True)
class ImpactAssessmentDraft:
    impact_hours: float | None
    impact_cost: float | None
    impact_timeline_days: int | None
    assessment_notes: str | None
    advisory: bool = True


_ALLOWED_STATUSES = {
    ChangeRequestStatus.UNDER_REVIEW.value,
    ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
}


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


def _parse_draft(payload: dict) -> ImpactAssessmentDraft:
    hours = payload.get("impact_hours")
    cost = payload.get("impact_cost")
    days = payload.get("impact_timeline_days")
    notes = payload.get("assessment_notes")
    return ImpactAssessmentDraft(
        impact_hours=float(hours) if hours is not None else None,
        impact_cost=float(cost) if cost is not None else None,
        impact_timeline_days=int(days) if days is not None else None,
        assessment_notes=str(notes) if notes is not None else None,
        advisory=True,
    )


async def draft_impact_assessment(
    db: AsyncSession,
    *,
    actor: User,
    cr_id: UUID,
) -> ImpactAssessmentDraft | None:
    cr = await get_change_request(db, cr_id)
    if cr is None:
        raise NotFoundError("Change request not found")
    if not await actor_can_mutate_project(db, actor, cr.project_id):
        raise AuthorizationError("You're not assigned to this project.")
    if cr.status not in _ALLOWED_STATUSES:
        raise DomainError(
            "Impact draft is only available while the change request is under review",
            code="validation_error",
        )

    prompt = (
        "You are an advisory assistant for a project management CRM. "
        "Return ONLY valid JSON with keys: impact_hours (number|null), "
        "impact_cost (number|null), impact_timeline_days (integer|null), "
        "assessment_notes (string). Do not include markdown.\n\n"
        f"Change request type: {cr.type}\n"
        f"Title: {cr.title}\n"
        f"Description: {cr.description or '(none)'}\n"
        f"Priority: {cr.priority}\n"
        f"Current status: {cr.status}\n"
    )
    raw = await generate_text(prompt, timeout=12)
    if not raw:
        return None
    payload = _extract_json_block(raw)
    if payload is None:
        return None
    return _parse_draft(payload)
