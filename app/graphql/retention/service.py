from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import DomainError, NotFoundError
from app.db.enums import (
    EnrollmentStatus,
    ProjectStatus,
    SequenceSource,
    SequenceStatus,
    SequenceTriggerType,
    TouchpointChannel,
    TouchpointOutcome,
    TouchpointStatus,
)
from app.db.models.contact import Contact
from app.db.models.retention import (
    EmailTemplate,
    RetentionEnrollment,
    RetentionSequence,
    RetentionSequenceStep,
    Touchpoint,
)
from app.db.models.user import User
from app.graphql.retention.ai_assist import draft_retention_sequence
from app.graphql.retention.eligibility import (
    RETENTION_TRIGGER_TYPES,
    assert_company_retention_eligible,
    assert_completed_project_for_company,
    assert_retention_channel,
    assert_retention_trigger,
    get_company_retention_eligibility,
    get_latest_completed_project_id,
)
from app.graphql.retention.repository import (
    get_active_sequences_by_trigger,
    get_email_template,
    get_enrollment,
    has_active_enrollment_for_contact,
    get_sequence,
    get_step,
    get_touchpoint,
    list_sequences,
    list_steps_for_sequence,
    list_touchpoints_for_company,
    list_upcoming_touchpoints,
    touchpoint_exists_for_step,
)


def _sequence_dict(seq: RetentionSequence) -> dict:
    return {
        "id": str(seq.id),
        "name": seq.name,
        "trigger_type": seq.trigger_type,
        "company_id": str(seq.company_id) if seq.company_id else None,
        "status": seq.status,
        "source": seq.source,
    }


_PM_ADMIN_ROLES = {"admin", "project_manager"}
_ENROLLABLE_STATUSES = {SequenceStatus.APPROVED.value, SequenceStatus.ACTIVE.value}
_RESTRICTED_STATUSES = {SequenceStatus.PENDING.value, SequenceStatus.DRAFT.value, SequenceStatus.REJECTED.value}


def _can_view_sequence(actor: User, seq: RetentionSequence) -> bool:
    if actor.role in _PM_ADMIN_ROLES:
        return True
    return seq.status not in _RESTRICTED_STATUSES


def _is_sequence_enrollable(sequence: RetentionSequence) -> bool:
    return (
        sequence.status in _ENROLLABLE_STATUSES
        and sequence.is_active
        and not sequence.is_template
    )


async def list_retention_sequences(
    db: AsyncSession,
    *,
    actor: User,
    active_only: bool = False,
    company_id: UUID | None = None,
    status: str | None = None,
    source: str | None = None,
    created_by_id: UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    search: str | None = None,
) -> list[RetentionSequence]:
    exclude_statuses = None
    if actor.role not in _PM_ADMIN_ROLES:
        exclude_statuses = list(_RESTRICTED_STATUSES)
    return await list_sequences(
        db,
        active_only=active_only,
        company_id=company_id,
        status=status,
        source=source,
        created_by_id=created_by_id,
        created_after=created_after,
        created_before=created_before,
        search=search,
        exclude_statuses=exclude_statuses,
    )


async def get_retention_sequence(db: AsyncSession, sequence_id: UUID, *, actor: User | None = None) -> RetentionSequence:
    seq = await get_sequence(db, sequence_id)
    if seq is None:
        raise NotFoundError("Sequence not found")
    if actor is not None and not _can_view_sequence(actor, seq):
        raise NotFoundError("Sequence not found")
    return seq


async def create_sequence_record(
    db: AsyncSession,
    *,
    actor: User,
    name: str,
    company_id: UUID,
    trigger_type: str = SequenceTriggerType.MANUAL.value,
    description: str | None = None,
    is_active: bool = False,
    is_template: bool = False,
    status: str = SequenceStatus.DRAFT.value,
    source: str = SequenceSource.MANUAL.value,
    ai_rationale: str | None = None,
) -> RetentionSequence:
    assert_retention_trigger(trigger_type)
    await assert_company_retention_eligible(db, company_id)
    seq = RetentionSequence(
        org_id=actor.org_id,
        name=name,
        company_id=company_id,
        description=description,
        trigger_type=trigger_type,
        is_active=is_active,
        is_template=is_template,
        status=status,
        source=source,
        created_by_id=actor.id,
        ai_rationale=ai_rationale,
    )
    db.add(seq)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="retention_sequence",
        entity_id=seq.id,
        diff={"after": _sequence_dict(seq)},
    )
    return seq


async def update_sequence_record(
    db: AsyncSession,
    *,
    actor: User,
    sequence_id: UUID,
    updates: dict,
) -> RetentionSequence:
    seq = await get_retention_sequence(db, sequence_id, actor=actor)
    if seq.status in {SequenceStatus.PENDING.value, SequenceStatus.REJECTED.value}:
        raise DomainError("This sequence cannot be edited in its current status", code="conflict")
    before = _sequence_dict(seq)
    if updates.get("trigger_type") is not None:
        assert_retention_trigger(updates["trigger_type"])
    if updates.get("company_id") is not None:
        await assert_company_retention_eligible(db, updates["company_id"])
    for key, value in updates.items():
        if value is not None and hasattr(seq, key):
            setattr(seq, key, value)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="update",
        entity_type="retention_sequence",
        entity_id=seq.id,
        diff={"before": before, "after": _sequence_dict(seq)},
    )
    return seq


async def duplicate_sequence_record(db: AsyncSession, *, actor: User, sequence_id: UUID) -> RetentionSequence:
    source = await get_retention_sequence(db, sequence_id, actor=actor)
    clone = RetentionSequence(
        org_id=actor.org_id,
        name=f"{source.name} (copy)",
        company_id=source.company_id,
        description=source.description,
        trigger_type=source.trigger_type,
        is_active=False,
        is_template=False,
        status=SequenceStatus.DRAFT.value,
        source=SequenceSource.MANUAL.value,
        created_by_id=actor.id,
        ai_rationale=source.ai_rationale,
    )
    db.add(clone)
    await db.flush()

    for step in sorted(source.steps, key=lambda s: s.step_order):
        db.add(
            RetentionSequenceStep(
                org_id=actor.org_id,
                sequence_id=clone.id,
                step_order=step.step_order,
                channel=step.channel,
                offset_days=step.offset_days,
                template_id=step.template_id,
                assignee_role=step.assignee_role,
                name=step.name,
                action_message=step.action_message,
            )
        )
    await db.flush()
    return await get_retention_sequence(db, clone.id, actor=actor)


async def add_sequence_step(
    db: AsyncSession,
    *,
    actor: User,
    sequence_id: UUID,
    channel: str,
    offset_days: int,
    step_order: int | None = None,
    template_id: UUID | None = None,
    assignee_role: str | None = None,
    name: str | None = None,
    action_message: str | None = None,
) -> RetentionSequenceStep:
    seq = await get_retention_sequence(db, sequence_id, actor=actor)
    if seq.status in {SequenceStatus.PENDING.value, SequenceStatus.REJECTED.value}:
        raise DomainError("This sequence cannot be edited in its current status", code="conflict")
    assert_retention_channel(channel)
    existing = await list_steps_for_sequence(db, sequence_id)
    order = step_order if step_order is not None else len(existing)
    step = RetentionSequenceStep(
        org_id=actor.org_id,
        sequence_id=sequence_id,
        step_order=order,
        channel=channel,
        offset_days=offset_days,
        template_id=template_id,
        assignee_role=assignee_role,
        name=name,
        action_message=action_message,
    )
    db.add(step)
    await db.flush()
    return step


async def update_sequence_step(
    db: AsyncSession,
    *,
    actor: User,
    step_id: UUID,
    channel: str | None = None,
    offset_days: int | None = None,
    assignee_role: str | None = None,
    name: str | None = None,
    action_message: str | None = None,
) -> RetentionSequenceStep:
    step = await get_step(db, step_id)
    if step is None:
        raise NotFoundError("Step not found")
    seq = await get_retention_sequence(db, step.sequence_id, actor=actor)
    if seq.status in {SequenceStatus.PENDING.value, SequenceStatus.REJECTED.value}:
        raise DomainError("This sequence cannot be edited in its current status", code="conflict")
    if channel is not None:
        assert_retention_channel(channel)
        step.channel = channel
    if offset_days is not None:
        step.offset_days = offset_days
    if assignee_role is not None:
        step.assignee_role = assignee_role or None
    if name is not None:
        step.name = name or None
    if action_message is not None:
        step.action_message = action_message or None
    await db.flush()
    return step


async def remove_sequence_step(
    db: AsyncSession,
    *,
    actor: User,
    step_id: UUID,
) -> None:
    step = await get_step(db, step_id)
    if step is None:
        raise NotFoundError("Step not found")
    seq = await get_retention_sequence(db, step.sequence_id, actor=actor)
    if seq.status in {SequenceStatus.PENDING.value, SequenceStatus.REJECTED.value}:
        raise DomainError("This sequence cannot be edited in its current status", code="conflict")
    await db.delete(step)
    await db.flush()


async def reorder_sequence_steps(
    db: AsyncSession,
    *,
    actor: User,
    sequence_id: UUID,
    ordered_step_ids: list[UUID],
) -> list[RetentionSequenceStep]:
    await get_retention_sequence(db, sequence_id, actor=actor)
    steps = await list_steps_for_sequence(db, sequence_id)
    step_map = {s.id: s for s in steps}
    if set(step_map.keys()) != set(ordered_step_ids):
        raise DomainError("ordered_step_ids must match all steps exactly", code="validation_error")
    for index, step_id in enumerate(ordered_step_ids):
        step_map[step_id].step_order = index
    await db.flush()
    return await list_steps_for_sequence(db, sequence_id)


async def _create_enrollment(
    db: AsyncSession,
    *,
    org_id: UUID,
    sequence: RetentionSequence,
    company_id: UUID,
    contact_id: UUID,
    project_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> RetentionEnrollment:
    if not _is_sequence_enrollable(sequence):
        raise DomainError("Sequence is not approved for enrollment", code="conflict")
    steps = await list_steps_for_sequence(db, sequence.id)
    if not steps:
        raise DomainError("Sequence has no steps", code="validation_error")
    for step in steps:
        assert_retention_channel(step.channel)

    now = datetime.now(UTC)
    enrollment = RetentionEnrollment(
        org_id=org_id,
        sequence_id=sequence.id,
        company_id=company_id,
        contact_id=contact_id,
        project_id=project_id,
        status=EnrollmentStatus.ACTIVE.value,
        current_step=0,
        enrolled_at=now,
    )
    db.add(enrollment)
    await db.flush()

    if actor_id:
        await write_activity_log(
            db,
            org_id=org_id,
            actor_id=actor_id,
            action="enroll",
            entity_type="retention_enrollment",
            entity_id=enrollment.id,
            diff={"sequence_id": str(sequence.id), "company_id": str(company_id)},
        )
    return enrollment


async def enroll_in_sequence(
    db: AsyncSession,
    *,
    actor: User,
    sequence_id: UUID,
    company_id: UUID,
    contact_id: UUID,
    project_id: UUID | None = None,
) -> RetentionEnrollment:
    sequence = await get_retention_sequence(db, sequence_id, actor=actor)
    if sequence.company_id and sequence.company_id != company_id:
        raise DomainError("This sequence belongs to a different client company", code="validation_error")
    await assert_company_retention_eligible(db, company_id)
    resolved_project_id = project_id
    if resolved_project_id is not None:
        await assert_completed_project_for_company(
            db, company_id=company_id, project_id=resolved_project_id
        )
    else:
        resolved_project_id = await get_latest_completed_project_id(db, company_id)
        if resolved_project_id is None:
            raise DomainError(
                "Link enrollment to a completed project — retention starts after delivery.",
                code="validation_error",
            )
    if await has_active_enrollment_for_contact(db, sequence_id=sequence.id, contact_id=contact_id):
        raise DomainError("This contact is already enrolled in this sequence.", code="conflict")
    return await _create_enrollment(
        db,
        org_id=actor.org_id,
        sequence=sequence,
        company_id=company_id,
        contact_id=contact_id,
        project_id=resolved_project_id,
        actor_id=actor.id,
    )


async def enroll_renewal_sequences(
    db: AsyncSession,
    *,
    org_id: UUID,
    company_id: UUID,
    contact_id: UUID,
    actor_id: UUID | None = None,
) -> list[RetentionEnrollment]:
    """Retention is post-project call/email follow-up only — renewal auto-enroll is disabled."""
    return []


async def try_auto_enroll(
    db: AsyncSession,
    *,
    org_id: UUID,
    trigger_type: str,
    company_id: UUID,
    contact_id: UUID,
    project_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> list[RetentionEnrollment]:
    if trigger_type not in RETENTION_TRIGGER_TYPES:
        return []

    eligibility = await get_company_retention_eligibility(db, company_id)
    if not eligibility.eligible:
        return []

    if trigger_type == SequenceTriggerType.ON_PROJECT_COMPLETED.value:
        if project_id is None:
            return []
        await assert_completed_project_for_company(
            db, company_id=company_id, project_id=project_id
        )

    sequences = await get_active_sequences_by_trigger(db, trigger_type, company_id=company_id)
    enrollments: list[RetentionEnrollment] = []
    for sequence in sequences:
        if await has_active_enrollment_for_contact(db, sequence_id=sequence.id, contact_id=contact_id):
            continue
        enrollment = await _create_enrollment(
            db,
            org_id=org_id,
            sequence=sequence,
            company_id=company_id,
            contact_id=contact_id,
            project_id=project_id,
            actor_id=actor_id,
        )
        enrollments.append(enrollment)
    return enrollments


async def cancel_enrollment(db: AsyncSession, *, actor: User, enrollment_id: UUID) -> RetentionEnrollment:
    enrollment = await get_enrollment(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment not found")
    enrollment.status = EnrollmentStatus.CANCELLED.value
    await db.flush()
    return enrollment


async def materialize_due_touchpoint(
    db: AsyncSession,
    *,
    enrollment: RetentionEnrollment,
    step: RetentionSequenceStep,
    created_by: UUID | None = None,
) -> Touchpoint | None:
    if await touchpoint_exists_for_step(db, enrollment_id=enrollment.id, sequence_step_id=step.id):
        return None

    scheduled_at = enrollment.enrolled_at + timedelta(days=step.offset_days)
    row = Touchpoint(
        org_id=enrollment.org_id,
        enrollment_id=enrollment.id,
        sequence_step_id=step.id,
        company_id=enrollment.company_id,
        contact_id=enrollment.contact_id,
        project_id=enrollment.project_id,
        type=step.channel,
        scheduled_at=scheduled_at,
        status=TouchpointStatus.SCHEDULED.value,
        created_by=created_by,
    )
    db.add(row)
    await db.flush()
    return row


async def complete_touchpoint(
    db: AsyncSession,
    *,
    actor: User,
    touchpoint_id: UUID,
    outcome: str | None = None,
    notes: str | None = None,
) -> Touchpoint:
    tp = await get_touchpoint(db, touchpoint_id)
    if tp is None:
        raise NotFoundError("Touchpoint not found")
    if tp.status not in {TouchpointStatus.SCHEDULED.value, TouchpointStatus.OVERDUE.value}:
        raise DomainError("Touchpoint is not completable", code="conflict")

    now = datetime.now(UTC)
    tp.status = TouchpointStatus.COMPLETED.value
    tp.completed_at = now
    tp.outcome = outcome or TouchpointOutcome.NEUTRAL.value
    tp.notes = notes
    await db.flush()

    if tp.enrollment_id and tp.sequence_step_id:
        enrollment = await get_enrollment(db, tp.enrollment_id)
        if enrollment and enrollment.status == EnrollmentStatus.ACTIVE.value:
            step = await get_step(db, tp.sequence_step_id)
            if step:
                enrollment.current_step = step.step_order + 1
                all_steps = await list_steps_for_sequence(db, enrollment.sequence_id)
                if enrollment.current_step >= len(all_steps):
                    enrollment.status = EnrollmentStatus.COMPLETED.value
                await db.flush()

    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="complete",
        entity_type="touchpoint",
        entity_id=tp.id,
        diff={"outcome": tp.outcome},
    )
    return tp


async def skip_touchpoint(db: AsyncSession, *, actor: User, touchpoint_id: UUID, notes: str | None = None) -> Touchpoint:
    tp = await get_touchpoint(db, touchpoint_id)
    if tp is None:
        raise NotFoundError("Touchpoint not found")
    tp.status = TouchpointStatus.SKIPPED.value
    tp.notes = notes
    tp.completed_at = datetime.now(UTC)
    await db.flush()
    return tp


async def log_touchpoint(
    db: AsyncSession,
    *,
    actor: User,
    company_id: UUID,
    contact_id: UUID,
    type: str,
    outcome: str | None = None,
    notes: str | None = None,
    project_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> Touchpoint:
    """Records a touchpoint that already happened — a call made, a meeting held —
    rather than one scheduled ahead by a sequence step. Both `enrollment_id` and
    `sequence_step_id` stay null; that's how a manual log is told apart from an
    automated one."""
    now = datetime.now(UTC)
    when = occurred_at or now
    tp = Touchpoint(
        org_id=actor.org_id,
        company_id=company_id,
        contact_id=contact_id,
        project_id=project_id,
        type=type,
        scheduled_at=when,
        completed_at=when,
        status=TouchpointStatus.COMPLETED.value,
        outcome=outcome or TouchpointOutcome.NEUTRAL.value,
        notes=notes,
    )
    db.add(tp)
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="create",
        entity_type="touchpoint",
        entity_id=tp.id,
        diff={"after": {"type": tp.type, "outcome": tp.outcome, "company_id": str(company_id)}},
    )
    return tp


async def get_upcoming_touchpoints(db: AsyncSession) -> list[Touchpoint]:
    return await list_upcoming_touchpoints(db)


async def get_touchpoints_for_company(db: AsyncSession, company_id: UUID) -> list[Touchpoint]:
    return await list_touchpoints_for_company(db, company_id)


async def submit_sequence_for_approval(
    db: AsyncSession,
    *,
    actor: User,
    sequence_id: UUID,
) -> RetentionSequence:
    seq = await get_retention_sequence(db, sequence_id, actor=actor)
    if seq.status not in {SequenceStatus.DRAFT.value}:
        raise DomainError("Only draft sequences can be submitted for approval", code="validation_error")
    if not seq.company_id:
        raise DomainError("Link this sequence to a client company before submitting", code="validation_error")
    steps = await list_steps_for_sequence(db, sequence_id)
    if not steps:
        raise DomainError("Add at least one step before submitting", code="validation_error")
    for step in steps:
        assert_retention_channel(step.channel)
    await assert_company_retention_eligible(db, seq.company_id)
    seq.status = SequenceStatus.PENDING.value
    seq.is_active = False
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="submit_for_approval",
        entity_type="retention_sequence",
        entity_id=seq.id,
        diff={"status": seq.status},
    )
    return seq


async def approve_retention_sequence(
    db: AsyncSession,
    *,
    actor: User,
    sequence_id: UUID,
) -> RetentionSequence:
    seq = await get_retention_sequence(db, sequence_id, actor=actor)
    if seq.status != SequenceStatus.PENDING.value:
        raise DomainError("Only pending sequences can be approved", code="validation_error")
    now = datetime.now(UTC)
    seq.status = SequenceStatus.APPROVED.value
    seq.is_active = True
    seq.approved_by_id = actor.id
    seq.approved_at = now
    seq.rejection_reason = None
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="approve",
        entity_type="retention_sequence",
        entity_id=seq.id,
        diff={"status": seq.status},
    )
    return seq


async def reject_retention_sequence(
    db: AsyncSession,
    *,
    actor: User,
    sequence_id: UUID,
    reason: str | None = None,
) -> RetentionSequence:
    seq = await get_retention_sequence(db, sequence_id, actor=actor)
    if seq.status != SequenceStatus.PENDING.value:
        raise DomainError("Only pending sequences can be rejected", code="validation_error")
    seq.status = SequenceStatus.REJECTED.value
    seq.is_active = False
    seq.rejection_reason = reason
    await db.flush()
    await write_activity_log(
        db,
        org_id=actor.org_id,
        actor_id=actor.id,
        action="reject",
        entity_type="retention_sequence",
        entity_id=seq.id,
        diff={"status": seq.status, "reason": reason},
    )
    return seq


async def generate_ai_retention_sequence(
    db: AsyncSession,
    *,
    actor: User,
    company_id: UUID,
) -> RetentionSequence:
    await assert_company_retention_eligible(db, company_id)
    draft = await draft_retention_sequence(db, actor=actor, company_id=company_id)
    seq = await create_sequence_record(
        db,
        actor=actor,
        name=draft.name,
        company_id=company_id,
        trigger_type=draft.trigger_type,
        description=draft.description,
        is_active=False,
        status=SequenceStatus.DRAFT.value,
        source=SequenceSource.AI.value,
        ai_rationale=draft.strategy_summary,
    )
    for index, step in enumerate(draft.steps):
        await add_sequence_step(
            db,
            actor=actor,
            sequence_id=seq.id,
            channel=step.channel,
            offset_days=step.offset_days,
            step_order=index,
            assignee_role=step.assignee_role,
            name=step.name,
            action_message=step.action_message,
        )
    seq.status = SequenceStatus.PENDING.value
    await db.flush()
    return await get_retention_sequence(db, seq.id, actor=actor)


async def create_email_template_record(
    db: AsyncSession,
    *,
    actor: User,
    name: str,
    subject: str,
    body: str,
) -> EmailTemplate:
    row = EmailTemplate(org_id=actor.org_id, name=name, subject=subject, body=body)
    db.add(row)
    await db.flush()
    return row
