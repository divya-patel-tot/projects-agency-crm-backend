"""Production readiness checks."""

import pytest

from app.core.config import Settings
from app.core.production import collect_production_issues, validate_production_settings


def test_development_skips_production_errors():
    settings = Settings.model_construct(
        environment="development",
        debug=True,
        database_url="postgresql+asyncpg://u:p@localhost/db",
        database_url_sync="postgresql+psycopg://u:p@localhost/db",
        jwt_secret_key="x" * 32,
        cookie_secure=False,
        cors_allowed_origins="http://localhost:3000",
    )
    assert collect_production_issues(settings) == []


def test_production_flags_insecure_config():
    settings = Settings.model_construct(
        environment="production",
        debug=True,
        database_url="postgresql+asyncpg://u:p@localhost/db",
        database_url_sync="postgresql+psycopg://u:p@localhost/db",
        jwt_secret_key="x" * 32,
        cookie_secure=False,
        cors_allowed_origins="http://localhost:3000",
        enable_scheduler=False,
    )
    issues = collect_production_issues(settings)
    codes = {issue.message for issue in issues if issue.level == "error"}
    assert "DEBUG must be false in production" in codes
    assert "COOKIE_SECURE must be true in production" in codes

    with pytest.raises(RuntimeError, match="Production configuration invalid"):
        validate_production_settings(settings)
