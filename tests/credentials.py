"""Test-only credentials — read from environment, never hardcoded."""

from __future__ import annotations

from app.core.bootstrap import bootstrap_env
from app.core.env_file import optional_env, require_env


def _ensure_env() -> None:
    bootstrap_env()


def fixture_password() -> str:
    _ensure_env()
    return require_env("TEST_FIXTURE_PASSWORD")


def seed_admin_email() -> str:
    _ensure_env()
    return optional_env("SEED_ADMIN_EMAIL", "admin@example.com") or "admin@example.com"


def seed_admin_password() -> str:
    _ensure_env()
    return require_env("SEED_ADMIN_PASSWORD")
