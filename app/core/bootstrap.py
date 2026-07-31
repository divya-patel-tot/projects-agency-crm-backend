"""Load backend/.env into the current process — never persisted at OS level.

Configuration rules:
- Secrets and settings live only in ``backend/.env`` (gitignored).
- This module only mutates ``os.environ`` for the lifetime of the current process;
  it does not write registry entries, user profiles, or other OS-level stores.
- On each new process start, ``.env`` values override stale shell/OS environment
  variables so edits take effect on the next run without manual env cleanup.
- ``get_settings()`` is cached per process; restart the server after ``.env`` changes.
"""

from __future__ import annotations

from app.core.env_file import ENV_FILE, ENV_TEST_FILE, apply_env_files

_bootstrapped = False


def bootstrap_env(*, force: bool = False) -> None:
    """Load ``backend/.env`` into this process (``.env`` wins over OS env)."""
    global _bootstrapped
    if _bootstrapped and not force:
        return
    apply_env_files(ENV_FILE, override=True)
    _bootstrapped = True


def bootstrap_test_env(*, force: bool = False) -> None:
    """Load ``.env`` then ``.env.test`` overrides for pytest."""
    bootstrap_env(force=force)
    if ENV_TEST_FILE.exists():
        apply_env_files(ENV_TEST_FILE, override=True)


def reload_runtime_config():
    """Reload ``.env`` and clear in-process caches (tests / long-running scripts)."""
    from app.core.config import get_settings
    from app.core.db import reset_db_engines
    from app.integrations.groq_client import reset_groq_client

    bootstrap_env(force=True)
    get_settings.cache_clear()
    reset_groq_client()
    reset_db_engines()
    return get_settings()
