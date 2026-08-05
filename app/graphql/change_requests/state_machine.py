"""Pure change-request state machine — no database imports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from app.core.exceptions import AuthorizationError, DomainError
from app.db.enums import ChangeRequestStatus, ChangeRequestType


class TransitionActor(StrEnum):
    INTERNAL_PM = "internal_pm"
    INTERNAL_ADMIN = "internal_admin"
    INTERNAL_OTHER = "internal_other"
    PORTAL_CONTACT = "portal_contact"
    SYSTEM = "system"


TRANSITION_TABLE: dict[str, frozenset[str]] = {
    ChangeRequestStatus.SUBMITTED.value: frozenset({ChangeRequestStatus.UNDER_REVIEW.value}),
    ChangeRequestStatus.UNDER_REVIEW.value: frozenset(
        {
            ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
            ChangeRequestStatus.ON_HOLD.value,
            ChangeRequestStatus.REJECTED.value,
        }
    ),
    ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value: frozenset(
        {
            ChangeRequestStatus.PENDING_APPROVAL.value,
            ChangeRequestStatus.ON_HOLD.value,
        }
    ),
    ChangeRequestStatus.PENDING_APPROVAL.value: frozenset(
        {
            ChangeRequestStatus.APPROVED.value,
            ChangeRequestStatus.REJECTED.value,
        }
    ),
    ChangeRequestStatus.APPROVED.value: frozenset({ChangeRequestStatus.IN_PROGRESS.value}),
    ChangeRequestStatus.IN_PROGRESS.value: frozenset({ChangeRequestStatus.IMPLEMENTED.value}),
    ChangeRequestStatus.IMPLEMENTED.value: frozenset({ChangeRequestStatus.CLOSED.value}),
    ChangeRequestStatus.REJECTED.value: frozenset(
        {
            ChangeRequestStatus.CLOSED.value,
            ChangeRequestStatus.SUBMITTED.value,
        }
    ),
    ChangeRequestStatus.ON_HOLD.value: frozenset({ChangeRequestStatus.UNDER_REVIEW.value}),
}

TRANSITION_ACTORS: dict[tuple[str, str], frozenset[TransitionActor]] = {
    (ChangeRequestStatus.SUBMITTED.value, ChangeRequestStatus.UNDER_REVIEW.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.UNDER_REVIEW.value, ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.UNDER_REVIEW.value, ChangeRequestStatus.ON_HOLD.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.UNDER_REVIEW.value, ChangeRequestStatus.REJECTED.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value, ChangeRequestStatus.PENDING_APPROVAL.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN, TransitionActor.SYSTEM}
    ),
    (ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value, ChangeRequestStatus.ON_HOLD.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.PENDING_APPROVAL.value, ChangeRequestStatus.APPROVED.value): frozenset(
        {TransitionActor.SYSTEM, TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.PENDING_APPROVAL.value, ChangeRequestStatus.REJECTED.value): frozenset(
        {
            TransitionActor.SYSTEM,
            TransitionActor.INTERNAL_PM,
            TransitionActor.INTERNAL_ADMIN,
            TransitionActor.PORTAL_CONTACT,
        }
    ),
    (ChangeRequestStatus.APPROVED.value, ChangeRequestStatus.IN_PROGRESS.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN, TransitionActor.SYSTEM}
    ),
    (ChangeRequestStatus.IN_PROGRESS.value, ChangeRequestStatus.IMPLEMENTED.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.IMPLEMENTED.value, ChangeRequestStatus.CLOSED.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.REJECTED.value, ChangeRequestStatus.CLOSED.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.REJECTED.value, ChangeRequestStatus.SUBMITTED.value): frozenset(
        {TransitionActor.PORTAL_CONTACT, TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
    (ChangeRequestStatus.ON_HOLD.value, ChangeRequestStatus.UNDER_REVIEW.value): frozenset(
        {TransitionActor.INTERNAL_PM, TransitionActor.INTERNAL_ADMIN}
    ),
}

REVISION_INCREMENT_TRANSITIONS = frozenset(
    {
        (ChangeRequestStatus.ON_HOLD.value, ChangeRequestStatus.UNDER_REVIEW.value),
        (ChangeRequestStatus.REJECTED.value, ChangeRequestStatus.SUBMITTED.value),
    }
)

CLIENT_APPROVAL_TYPES = frozenset(
    {
        ChangeRequestType.SCOPE_ADDITION.value,
        ChangeRequestType.SCOPE_REDUCTION.value,
        ChangeRequestType.BUDGET_CHANGE.value,
    }
)

DEFAULT_ORG_SETTINGS = {
    "cr_internal_approval_cost_threshold": 5000.0,
    "cr_internal_approval_timeline_days_threshold": 5,
    "cr_revision_cap": 3,
    "cr_response_sla_days": 7,
}


@dataclass(frozen=True)
class OrgCrSettings:
    internal_cost_threshold: float
    internal_timeline_days_threshold: int
    revision_cap: int
    response_sla_days: int


@dataclass
class ChangeRequestSnapshot:
    status: str
    type: str
    revision_count: int
    impact_cost: float | None = None
    impact_timeline_days: int | None = None
    requires_client_approval: bool = False
    requires_internal_approval: bool = False
    manager_escalation_flagged: bool = False


@dataclass(frozen=True)
class TransitionResult:
    status: str
    revision_count: int
    manager_escalation_flagged: bool
    increment_revision: bool
    trigger_escalation: bool


def org_settings_from_dict(settings: dict | None) -> OrgCrSettings:
    merged = {**DEFAULT_ORG_SETTINGS, **(settings or {})}
    return OrgCrSettings(
        internal_cost_threshold=float(merged["cr_internal_approval_cost_threshold"]),
        internal_timeline_days_threshold=int(merged["cr_internal_approval_timeline_days_threshold"]),
        revision_cap=int(merged["cr_revision_cap"]),
        response_sla_days=int(merged["cr_response_sla_days"]),
    )


def compute_approval_requirements(
    *,
    cr_type: str,
    impact_cost: float | None,
    impact_timeline_days: int | None,
    org_settings: OrgCrSettings,
) -> tuple[bool, bool]:
    requires_client = cr_type in CLIENT_APPROVAL_TYPES
    requires_internal = False
    if impact_cost is not None and impact_cost > org_settings.internal_cost_threshold:
        requires_internal = True
    if impact_timeline_days is not None and impact_timeline_days > org_settings.internal_timeline_days_threshold:
        requires_internal = True
    return requires_client, requires_internal


def actor_from_internal_role(role: str) -> TransitionActor:
    if role == "admin":
        return TransitionActor.INTERNAL_ADMIN
    if role == "project_manager":
        return TransitionActor.INTERNAL_PM
    return TransitionActor.INTERNAL_OTHER


def validate_transition(
    cr: ChangeRequestSnapshot,
    to_status: str,
    actor: TransitionActor,
) -> None:
    allowed = TRANSITION_TABLE.get(cr.status, frozenset())
    if to_status not in allowed:
        raise DomainError(
            f"Invalid transition from {cr.status} to {to_status}",
            code="invalid_transition",
        )
    actors = TRANSITION_ACTORS.get((cr.status, to_status))
    if actors is None or actor not in actors:
        raise AuthorizationError(f"Actor {actor.value} cannot transition {cr.status} -> {to_status}")


def apply_transition(
    cr: ChangeRequestSnapshot,
    to_status: str,
    actor: TransitionActor,
    *,
    org_settings: OrgCrSettings,
) -> TransitionResult:
    validate_transition(cr, to_status, actor)
    increment = (cr.status, to_status) in REVISION_INCREMENT_TRANSITIONS
    new_revision = cr.revision_count + (1 if increment else 0)
    trigger_escalation = increment and new_revision > org_settings.revision_cap
    return TransitionResult(
        status=to_status,
        revision_count=new_revision,
        manager_escalation_flagged=cr.manager_escalation_flagged or trigger_escalation,
        increment_revision=increment,
        trigger_escalation=trigger_escalation,
    )


def apply_snapshot_transition(cr: ChangeRequestSnapshot, result: TransitionResult) -> ChangeRequestSnapshot:
    return replace(
        cr,
        status=result.status,
        revision_count=result.revision_count,
        manager_escalation_flagged=result.manager_escalation_flagged,
    )
