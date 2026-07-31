"""Parse and apply backend/.env files without python-dotenv."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_ROOT / ".env"
ENV_TEST_FILE = BACKEND_ROOT / ".env.test"


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def apply_env_files(*paths: Path, override: bool = False) -> None:
    """Apply env file keys to ``os.environ`` for this process only (not persisted to OS)."""
    for path in paths:
        for key, value in parse_env_file(path).items():
            if override or key not in os.environ:
                os.environ[key] = value


def load_env_files(*paths: Path, override: bool = False) -> None:
    """Backward-compatible alias for ``apply_env_files``."""
    apply_env_files(*paths, override=override)


def require_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable {key}. Set it in backend/.env")
    return value


def optional_env(key: str, default: str | None = None) -> str | None:
    value = os.environ.get(key, "").strip()
    return value if value else default
