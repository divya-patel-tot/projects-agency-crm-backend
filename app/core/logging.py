import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

REDACT_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "jwt_secret_key",
        "api_key",
        "authorization",
        "cookie",
        "totp_secret",
        "totp_backup_codes",
    }
)


def _redact_value(key: str, value: Any) -> Any:
    if key.lower() in REDACT_KEYS:
        return "***REDACTED***"
    if isinstance(value, dict):
        return redact_dict(value)
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(key, value) for key, value in data.items()}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_ctx.get()
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            payload["extra"] = redact_dict(record.extra_data)
        return json.dumps(payload, default=str)


def configure_logging(*, debug: bool = False) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
