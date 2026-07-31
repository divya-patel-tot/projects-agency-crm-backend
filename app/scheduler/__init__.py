"""In-process scheduled jobs (APScheduler) — populated in Phase 5.

No Redis or Celery. Jobs run inside the FastAPI process or via a lightweight
`python -m app.scheduler.run` entry point for manual/cron invocation.
"""
