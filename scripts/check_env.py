#!/usr/bin/env python3
"""Compare .env keys against .env.example and exit non-zero if required keys are missing."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.env_file import ENV_FILE, parse_env_file

REQUIRED_KEYS = {
    "ENVIRONMENT",
    "DEBUG",
    "DATABASE_URL",
    "DATABASE_URL_SYNC",
    "JWT_SECRET_KEY",
    "JWT_ALGORITHM",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
    "COOKIE_SECURE",
    "CORS_ALLOWED_ORIGINS",
    "GROQ_MODEL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
}


def main() -> int:
    example_path = BACKEND_ROOT / ".env.example"
    env_values = parse_env_file(ENV_FILE)
    example_keys = set(parse_env_file(example_path).keys())
    env_keys = set(env_values.keys())

    missing_required = sorted(key for key in REQUIRED_KEYS if not env_values.get(key))
    missing_from_example = sorted(example_keys - env_keys)
    unexpected = sorted(env_keys - example_keys)

    if missing_required:
        print("Missing required keys in .env:")
        for key in missing_required:
            print(f"  - {key}")

    if missing_from_example:
        print("Keys present in .env.example but missing in .env:")
        for key in missing_from_example:
            print(f"  - {key}")

    if unexpected:
        print("Unexpected keys in .env (not in .env.example):")
        for key in unexpected:
            print(f"  - {key}")

    if missing_required or missing_from_example:
        return 1

    print("Environment check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
