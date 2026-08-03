from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from jinja2 import BaseLoader, Environment, StrictUndefined

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_jinja = Environment(loader=BaseLoader(), undefined=StrictUndefined, autoescape=True)


def render_template(subject: str, body: str, context: dict) -> tuple[str, str]:
    return _jinja.from_string(subject).render(**context), _jinja.from_string(body).render(**context)


def send_email(*, to: str, subject: str, body: str, html: bool = False) -> None:
    settings = get_settings()
    if not settings.email_features_enabled:
        logger.info("Email features disabled — skipped send to %s (subject=%s)", to, subject)
        return
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP not configured — email to %s skipped (subject=%s)", to, subject)
        return

    from_addr = settings.smtp_from or settings.smtp_user
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    if html:
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_use_tls:
            server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)

    logger.info("Email sent to %s subject=%s", to, subject)
