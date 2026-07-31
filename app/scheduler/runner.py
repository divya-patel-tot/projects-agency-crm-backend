"""APScheduler wiring — optional in-process cron (no Redis)."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.scheduler.jobs import (
    JOB_CONTRACT_RENEWAL,
    JOB_DEADLINE_REMINDERS,
    JOB_ESCALATE_CR,
    JOB_FLAG_OVERDUE,
    JOB_PROCESS_DUE_STEPS,
    JOB_RECALCULATE_HEALTH,
    JOB_WEEKLY_DIGEST,
    contract_renewal_check,
    escalate_pending_change_requests,
    flag_overdue_touchpoints,
    process_due_sequence_steps,
    project_deadline_reminders,
    recalculate_health_scores,
    weekly_digest_email,
)

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.enable_scheduler:
        logger.info("Scheduler disabled (ENABLE_SCHEDULER=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(process_due_sequence_steps, CronTrigger(hour=8, minute=0), id=JOB_PROCESS_DUE_STEPS)
    _scheduler.add_job(flag_overdue_touchpoints, CronTrigger(hour=9, minute=0), id=JOB_FLAG_OVERDUE)
    _scheduler.add_job(escalate_pending_change_requests, CronTrigger(hour=9, minute=30), id=JOB_ESCALATE_CR)
    _scheduler.add_job(project_deadline_reminders, CronTrigger(hour=7, minute=30), id=JOB_DEADLINE_REMINDERS)
    _scheduler.add_job(contract_renewal_check, CronTrigger(hour=8, minute=15), id=JOB_CONTRACT_RENEWAL)
    _scheduler.add_job(recalculate_health_scores, CronTrigger(hour=2, minute=0), id=JOB_RECALCULATE_HEALTH)
    _scheduler.add_job(weekly_digest_email, CronTrigger(day_of_week="mon", hour=8, minute=0), id=JOB_WEEKLY_DIGEST)
    _scheduler.start()
    logger.info("APScheduler started with %d jobs", len(_scheduler.get_jobs()))
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
