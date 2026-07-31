from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_activity_log
from app.core.exceptions import DomainError, NotFoundError
from app.db.enums import (
    EnrollmentStatus,
    ProjectStatus,
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
from app.graphql.retention.repository import (
    get_active_sequences_by_trigger,
    get_email_template,
    get_enrollment,
    get_sequence,
    get_step,
    get_touchpoint,
    has_active_enrollment_for_sequence,
    list_sequences,
    list_steps_for_sequence,
    list_upcoming_touchpoints,
    touchpoint_exists_for_step,
)


def _sequence_dict(seq: RetentionSequence) -> dict:
    return {"id": str(seq.id), "name": seq.name, "trigger_type": seq.trigger_type}


async def list_retention_sequences(db: AsyncSession, *, active_only: bool = False) -> list[RetentionSequence]:
    return await list_sequences(db, active_only=active_only)


async def get_retention_sequence(db: AsyncSession, sequence_id: UUID) -> RetentionSequence:
    seq = await get_sequence(db, sequence_id)
    if seq is None:
        raise NotFoundError("Sequence not found")
    return seq


async def create_sequence_record(
    db: AsyncSession,
    *,
    actor: User,
    name: str,
    trigger_type: str = SequenceTriggerType.MANUAL.value,
    is_active: bool = True,
    is_template: bool = False,
) -> RetentionSequence:
    seq = RetentionSequence(
        org_id=actor.org_id,
        name=name,
        trigger_type=trigger_type,
        is_active=is_active,
        is_template=is_template,
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
    seq = await get_retention_sequence(db, sequence_id)
    before = _sequence_dict(seq)
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
    source = await get_retention_sequence(db, sequence_id)
    if not source.is_template:
        raise DomainError("Only template sequences can be duplicated", code="validation_error")

    clone = RetentionSequence(
        org_id=actor.org_id,
        name=f"{source.name} (copy)",
        trigger_type=source.trigger_type,
        is_active=True,
        is_template=False,
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
            )
        )
    await db.flush()
    return await get_retention_sequence(db, clone.id)


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
) -> RetentionSequenceStep:
    await get_retention_sequence(db, sequence_id)
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
    )
    db.add(step)
    await db.flush()
    return step


async def reorder_sequence_steps(
    db: AsyncSession,
    *,
    actor: User,
    sequence_id: UUID,
    ordered_step_ids: list[UUID],
) -> list[RetentionSequenceStep]:
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
    if not sequence.is_active or sequence.is_template:
        raise DomainError("Sequence is not enrollable", code="conflict")
    if not sequence.steps:
        raise DomainError("Sequence has no steps", code="validation_error")

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
    sequence = await get_retention_sequence(db, sequence_id)
    if sequence.trigger_type != SequenceTriggerType.MANUAL.value:
        raise DomainError("Use auto-enrollment for non-manual trigger sequences", code="validation_error")
    return await _create_enrollment(
        db,
        org_id=actor.org_id,
        sequence=sequence,
        company_id=company_id,
        contact_id=contact_id,
        project_id=project_id,
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
    """Enroll company in all active ON_RENEWAL_APPROACHING sequences (idempotent per sequence)."""
    sequences = await get_active_sequences_by_trigger(db, SequenceTriggerType.ON_RENEWAL_APPROACHING.value)
    enrollments: list[RetentionEnrollment] = []
    for sequence in sequences:
        if await has_active_enrollment_for_sequence(db, company_id=company_id, sequence_id=sequence.id):
            continue
        enrollment = await _create_enrollment(
            db,
            org_id=org_id,
            sequence=sequence,
            company_id=company_id,
            contact_id=contact_id,
            actor_id=actor_id,
        )
        enrollments.append(enrollment)
    return enrollments


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
    if trigger_type == SequenceTriggerType.ON_RENEWAL_APPROACHING.value:
        return []

    sequences = await get_active_sequences_by_trigger(db, trigger_type)
    enrollments: list[RetentionEnrollment] = []
    for sequence in sequences:
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


async def get_upcoming_touchpoints(db: AsyncSession) -> list[Touchpoint]:
    return await list_upcoming_touchpoints(db)


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
