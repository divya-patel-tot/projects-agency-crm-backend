from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.enums import EnrollmentStatus, SequenceTriggerType, TouchpointStatus
from app.db.models.retention import (
    EmailTemplate,
    JobRun,
    RetentionEnrollment,
    RetentionSequence,
    RetentionSequenceStep,
    Touchpoint,
)


async def list_sequences(db: AsyncSession, *, active_only: bool = False) -> list[RetentionSequence]:
    query = (
        select(RetentionSequence)
        .where(RetentionSequence.deleted_at.is_(None))
        .options(selectinload(RetentionSequence.steps))
        .order_by(RetentionSequence.name.asc())
    )
    if active_only:
        query = query.where(RetentionSequence.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().unique().all())


async def get_sequence(db: AsyncSession, sequence_id: UUID) -> RetentionSequence | None:
    result = await db.execute(
        select(RetentionSequence)
        .where(RetentionSequence.id == sequence_id, RetentionSequence.deleted_at.is_(None))
        .options(selectinload(RetentionSequence.steps))
    )
    return result.scalar_one_or_none()


async def get_active_sequences_by_trigger(db: AsyncSession, trigger_type: str) -> list[RetentionSequence]:
    result = await db.execute(
        select(RetentionSequence)
        .where(
            RetentionSequence.trigger_type == trigger_type,
            RetentionSequence.is_active.is_(True),
            RetentionSequence.is_template.is_(False),
            RetentionSequence.deleted_at.is_(None),
        )
        .options(selectinload(RetentionSequence.steps))
    )
    return list(result.scalars().unique().all())


async def get_step(db: AsyncSession, step_id: UUID) -> RetentionSequenceStep | None:
    return await db.get(RetentionSequenceStep, step_id)


async def list_steps_for_sequence(db: AsyncSession, sequence_id: UUID) -> list[RetentionSequenceStep]:
    result = await db.execute(
        select(RetentionSequenceStep)
        .where(RetentionSequenceStep.sequence_id == sequence_id)
        .order_by(RetentionSequenceStep.step_order.asc())
    )
    return list(result.scalars().all())


async def get_enrollment(db: AsyncSession, enrollment_id: UUID) -> RetentionEnrollment | None:
    result = await db.execute(
        select(RetentionEnrollment)
        .where(RetentionEnrollment.id == enrollment_id)
        .options(selectinload(RetentionEnrollment.touchpoints))
    )
    return result.scalar_one_or_none()


async def get_touchpoint(db: AsyncSession, touchpoint_id: UUID) -> Touchpoint | None:
    return await db.get(Touchpoint, touchpoint_id)


async def touchpoint_exists_for_step(db: AsyncSession, *, enrollment_id: UUID, sequence_step_id: UUID) -> bool:
    result = await db.execute(
        select(Touchpoint.id).where(
            Touchpoint.enrollment_id == enrollment_id,
            Touchpoint.sequence_step_id == sequence_step_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def list_upcoming_touchpoints(
    db: AsyncSession,
    *,
    from_time: datetime | None = None,
    limit: int = 100,
) -> list[Touchpoint]:
    now = from_time or datetime.now(UTC)
    result = await db.execute(
        select(Touchpoint)
        .where(
            Touchpoint.status.in_([TouchpointStatus.SCHEDULED.value, TouchpointStatus.OVERDUE.value]),
            Touchpoint.scheduled_at >= now - timedelta(days=1),
        )
        .order_by(Touchpoint.scheduled_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_enrollments_for_sequence(db: AsyncSession, sequence_id: UUID) -> list[RetentionEnrollment]:
    result = await db.execute(
        select(RetentionEnrollment)
        .where(RetentionEnrollment.sequence_id == sequence_id)
        .order_by(RetentionEnrollment.enrolled_at.desc())
    )
    return list(result.scalars().all())


async def list_active_enrollments(db: AsyncSession) -> list[RetentionEnrollment]:
    result = await db.execute(
        select(RetentionEnrollment)
        .where(RetentionEnrollment.status == EnrollmentStatus.ACTIVE.value)
        .options(selectinload(RetentionEnrollment.touchpoints))
    )
    return list(result.scalars().unique().all())


async def get_email_template(db: AsyncSession, template_id: UUID) -> EmailTemplate | None:
    result = await db.execute(
        select(EmailTemplate).where(
            EmailTemplate.id == template_id,
            EmailTemplate.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def has_active_enrollment_for_sequence(
    db: AsyncSession,
    *,
    company_id: UUID,
    sequence_id: UUID,
) -> bool:
    result = await db.execute(
        select(RetentionEnrollment.id).where(
            RetentionEnrollment.company_id == company_id,
            RetentionEnrollment.sequence_id == sequence_id,
            RetentionEnrollment.status == EnrollmentStatus.ACTIVE.value,
        )
    )
    return result.scalar_one_or_none() is not None


async def job_run_exists(db: AsyncSession, *, org_id: UUID, job_name: str, run_date: date) -> bool:
    result = await db.execute(
        select(JobRun.id).where(
            JobRun.org_id == org_id,
            JobRun.job_name == job_name,
            JobRun.run_date == run_date,
        )
    )
    return result.scalar_one_or_none() is not None


async def create_job_run(db: AsyncSession, row: JobRun) -> JobRun:
    db.add(row)
    await db.flush()
    return row


async def list_touchpoints_due_by(db: AsyncSession, *, cutoff: datetime) -> list[Touchpoint]:
    result = await db.execute(
        select(Touchpoint).where(
            Touchpoint.status == TouchpointStatus.SCHEDULED.value,
            Touchpoint.scheduled_at <= cutoff,
        )
    )
    return list(result.scalars().all())


async def list_scheduled_touchpoints_past_due(db: AsyncSession, *, now: datetime) -> list[Touchpoint]:
    result = await db.execute(
        select(Touchpoint).where(
            Touchpoint.status == TouchpointStatus.SCHEDULED.value,
            Touchpoint.scheduled_at < now,
            Touchpoint.completed_at.is_(None),
        )
    )
    return list(result.scalars().all())
