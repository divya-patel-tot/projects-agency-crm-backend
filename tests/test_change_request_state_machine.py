"""Pure unit tests for the change-request state machine — no database."""

import pytest

from app.core.exceptions import AuthorizationError, DomainError
from app.db.enums import ChangeRequestStatus, ChangeRequestType
from app.graphql.change_requests.state_machine import (
    ChangeRequestSnapshot,
    OrgCrSettings,
    TransitionActor,
    TRANSITION_TABLE,
    apply_snapshot_transition,
    apply_transition,
    compute_approval_requirements,
    validate_transition,
)


def _cr(
    status: str = ChangeRequestStatus.SUBMITTED.value,
    revision_count: int = 0,
    cr_type: str = ChangeRequestType.OTHER.value,
) -> ChangeRequestSnapshot:
    return ChangeRequestSnapshot(status=status, type=cr_type, revision_count=revision_count)


DEFAULT_SETTINGS = OrgCrSettings(
    internal_cost_threshold=5000.0,
    internal_timeline_days_threshold=5,
    revision_cap=3,
    response_sla_days=7,
)


@pytest.mark.parametrize(
    ("from_status", "to_status", "actor"),
    [
        (ChangeRequestStatus.SUBMITTED.value, ChangeRequestStatus.UNDER_REVIEW.value, TransitionActor.INTERNAL_PM),
        (
            ChangeRequestStatus.UNDER_REVIEW.value,
            ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
            TransitionActor.INTERNAL_PM,
        ),
        (ChangeRequestStatus.UNDER_REVIEW.value, ChangeRequestStatus.ON_HOLD.value, TransitionActor.INTERNAL_ADMIN),
        (ChangeRequestStatus.UNDER_REVIEW.value, ChangeRequestStatus.REJECTED.value, TransitionActor.INTERNAL_PM),
        (
            ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
            ChangeRequestStatus.PENDING_APPROVAL.value,
            TransitionActor.SYSTEM,
        ),
        (
            ChangeRequestStatus.PENDING_APPROVAL.value,
            ChangeRequestStatus.APPROVED.value,
            TransitionActor.SYSTEM,
        ),
        (ChangeRequestStatus.APPROVED.value, ChangeRequestStatus.IN_PROGRESS.value, TransitionActor.SYSTEM),
        (ChangeRequestStatus.IN_PROGRESS.value, ChangeRequestStatus.IMPLEMENTED.value, TransitionActor.INTERNAL_PM),
        (ChangeRequestStatus.IMPLEMENTED.value, ChangeRequestStatus.CLOSED.value, TransitionActor.INTERNAL_ADMIN),
        (ChangeRequestStatus.REJECTED.value, ChangeRequestStatus.CLOSED.value, TransitionActor.INTERNAL_PM),
        (ChangeRequestStatus.REJECTED.value, ChangeRequestStatus.SUBMITTED.value, TransitionActor.PORTAL_CONTACT),
        (ChangeRequestStatus.ON_HOLD.value, ChangeRequestStatus.UNDER_REVIEW.value, TransitionActor.INTERNAL_PM),
    ],
)
def test_legal_transitions(from_status, to_status, actor):
    cr = _cr(status=from_status)
    validate_transition(cr, to_status, actor)
    result = apply_transition(cr, to_status, actor, org_settings=DEFAULT_SETTINGS)
    assert result.status == to_status


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (ChangeRequestStatus.SUBMITTED.value, ChangeRequestStatus.APPROVED.value),
        (ChangeRequestStatus.SUBMITTED.value, ChangeRequestStatus.IN_PROGRESS.value),
        (ChangeRequestStatus.UNDER_REVIEW.value, ChangeRequestStatus.APPROVED.value),
        (ChangeRequestStatus.PENDING_APPROVAL.value, ChangeRequestStatus.IN_PROGRESS.value),
        (ChangeRequestStatus.CLOSED.value, ChangeRequestStatus.SUBMITTED.value),
    ],
)
def test_illegal_transitions_raise(from_status, to_status):
    cr = _cr(status=from_status)
    with pytest.raises(DomainError) as exc:
        validate_transition(cr, to_status, TransitionActor.INTERNAL_PM)
    assert exc.value.code == "invalid_transition"


def test_wrong_actor_rejected():
    cr = _cr(status=ChangeRequestStatus.SUBMITTED.value)
    with pytest.raises(AuthorizationError):
        validate_transition(cr, ChangeRequestStatus.UNDER_REVIEW.value, TransitionActor.PORTAL_CONTACT)


def test_revision_escalation_at_cap_plus_one():
    cr = _cr(status=ChangeRequestStatus.ON_HOLD.value, revision_count=3)
    result = apply_transition(
        cr,
        ChangeRequestStatus.UNDER_REVIEW.value,
        TransitionActor.INTERNAL_PM,
        org_settings=DEFAULT_SETTINGS,
    )
    assert result.revision_count == 4
    assert result.trigger_escalation is True
    assert result.manager_escalation_flagged is True


def test_revision_escalation_not_before_cap():
    cr = _cr(status=ChangeRequestStatus.ON_HOLD.value, revision_count=2)
    result = apply_transition(
        cr,
        ChangeRequestStatus.UNDER_REVIEW.value,
        TransitionActor.INTERNAL_PM,
        org_settings=DEFAULT_SETTINGS,
    )
    assert result.revision_count == 3
    assert result.trigger_escalation is False
    assert result.manager_escalation_flagged is False


def test_compute_approval_requirements_client_and_internal():
    requires_client, requires_internal = compute_approval_requirements(
        cr_type=ChangeRequestType.SCOPE_ADDITION.value,
        impact_cost=6000.0,
        impact_timeline_days=2,
        org_settings=DEFAULT_SETTINGS,
    )
    assert requires_client is True
    assert requires_internal is True


def test_compute_approval_requirements_neither():
    requires_client, requires_internal = compute_approval_requirements(
        cr_type=ChangeRequestType.BUGFIX.value,
        impact_cost=100.0,
        impact_timeline_days=1,
        org_settings=DEFAULT_SETTINGS,
    )
    assert requires_client is False
    assert requires_internal is False


def test_transition_table_covers_all_non_terminal_statuses():
    non_terminal = {
        ChangeRequestStatus.SUBMITTED.value,
        ChangeRequestStatus.UNDER_REVIEW.value,
        ChangeRequestStatus.PENDING_IMPACT_ASSESSMENT.value,
        ChangeRequestStatus.PENDING_APPROVAL.value,
        ChangeRequestStatus.APPROVED.value,
        ChangeRequestStatus.IN_PROGRESS.value,
        ChangeRequestStatus.IMPLEMENTED.value,
        ChangeRequestStatus.REJECTED.value,
        ChangeRequestStatus.ON_HOLD.value,
    }
    assert set(TRANSITION_TABLE.keys()) == non_terminal


def test_apply_snapshot_transition_updates_fields():
    cr = _cr(status=ChangeRequestStatus.ON_HOLD.value, revision_count=3)
    result = apply_transition(
        cr,
        ChangeRequestStatus.UNDER_REVIEW.value,
        TransitionActor.INTERNAL_PM,
        org_settings=DEFAULT_SETTINGS,
    )
    updated = apply_snapshot_transition(cr, result)
    assert updated.status == ChangeRequestStatus.UNDER_REVIEW.value
    assert updated.revision_count == 4
    assert updated.manager_escalation_flagged is True
