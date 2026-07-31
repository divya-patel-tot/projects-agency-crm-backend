"""Optional Sentry error reporting — enabled only when SENTRY_DSN is set."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def init_sentry(*, dsn: str | None, environment: str, debug: bool) -> None:
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        debug=debug,
        traces_sample_rate=0.1 if not debug else 0.0,
        send_default_pii=False,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )
    logger.info("Sentry initialized", extra={"extra_data": {"environment": environment}})
