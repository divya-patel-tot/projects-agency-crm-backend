"""Production deployment readiness checks."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class ProductionIssue:
    level: str  # error | warning
    message: str


def collect_production_issues(settings: Settings) -> list[ProductionIssue]:
    issues: list[ProductionIssue] = []

    if settings.environment != "production":
        return issues

    if settings.debug:
        issues.append(ProductionIssue("error", "DEBUG must be false in production"))

    if not settings.cookie_secure:
        issues.append(ProductionIssue("error", "COOKIE_SECURE must be true in production"))

    if len(settings.jwt_secret_key) < 48:
        issues.append(ProductionIssue("warning", "JWT_SECRET_KEY should be at least 48 characters in production"))

    if not settings.cors_origins_list or settings.cors_origins_list == ["http://localhost:3000"]:
        issues.append(ProductionIssue("error", "CORS_ALLOWED_ORIGINS must list real frontend origins in production"))

    if any(origin == "*" for origin in settings.cors_origins_list):
        issues.append(ProductionIssue("error", "CORS must not use wildcard origin with credentials"))

    if settings.enable_scheduler and settings.environment == "production":
        issues.append(
            ProductionIssue(
                "warning",
                "ENABLE_SCHEDULER=true — ensure only one API process runs scheduled jobs",
            )
        )

    return issues


def validate_production_settings(settings: Settings) -> None:
    errors = [issue.message for issue in collect_production_issues(settings) if issue.level == "error"]
    if errors:
        joined = "; ".join(errors)
        raise RuntimeError(f"Production configuration invalid: {joined}")
