"""Config bootstrap: .env overrides stale OS env on each process start."""

from __future__ import annotations

import os

import pytest

from app.core.bootstrap import bootstrap_env, reload_runtime_config
from app.core.config import get_settings
from app.core.env_file import ENV_FILE, parse_env_file


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_bootstrap_overrides_stale_os_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("JWT_SECRET_KEY=from-file-32-chars-minimum-length!!\n", encoding="utf-8")
    monkeypatch.setenv("JWT_SECRET_KEY", "stale-os-secret-32-chars-minimum!!")

    from app.core.env_file import apply_env_files

    apply_env_files(env_path, override=True)
    assert os.environ["JWT_SECRET_KEY"] == "from-file-32-chars-minimum-length!!"


def test_get_settings_uses_backend_env_file():
    bootstrap_env(force=True)
    settings = get_settings()
    file_values = parse_env_file(ENV_FILE)
    assert settings.database_url == file_values["DATABASE_URL"]
    assert settings.jwt_secret_key == file_values["JWT_SECRET_KEY"]


def test_reload_runtime_config_refreshes_settings(monkeypatch: pytest.MonkeyPatch):
    bootstrap_env(force=True)
    before = get_settings().groq_model
    monkeypatch.setenv("GROQ_MODEL", before)

    reloaded = reload_runtime_config()
    assert reloaded.groq_model == before
