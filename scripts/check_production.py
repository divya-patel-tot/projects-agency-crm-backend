#!/usr/bin/env python3
"""Validate production-ready settings when ENVIRONMENT=production."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.bootstrap import bootstrap_env
from app.core.config import get_settings
from app.core.production import collect_production_issues


def main() -> int:
    bootstrap_env(force=True)
    get_settings.cache_clear()
    settings = get_settings()
    issues = collect_production_issues(settings)

    if settings.environment != "production":
        print(f"Production check skipped (ENVIRONMENT={settings.environment}).")
        if issues:
            print("Note: no issues expected outside production.")
        return 0

    errors = [issue for issue in issues if issue.level == "error"]
    warnings = [issue for issue in issues if issue.level == "warning"]

    for issue in errors:
        print(f"ERROR: {issue.message}")
    for issue in warnings:
        print(f"WARNING: {issue.message}")

    if errors:
        return 1

    print("Production configuration check passed.")
    if warnings:
        print(f"({len(warnings)} warning(s) — review before deploy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
