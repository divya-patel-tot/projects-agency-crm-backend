from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.env_file import ENV_FILE


class Settings(BaseSettings):
    """Central configuration — the ONLY module allowed to read environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    database_url: str
    database_url_sync: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    cookie_secure: bool = True
    cookie_domain: str | None = None

    cors_allowed_origins: str = "http://localhost:3000"

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    resend_api_key: str | None = None
    sentry_dsn: str | None = None

    enable_scheduler: bool = False
    # TOTP 2FA — off by default; set ENABLE_2FA=true when the UI and login challenge are ready.
    enable_2fa: bool = False
    # Mail is disabled by default — set EMAIL_FEATURES_ENABLED=true to turn SMTP jobs back on.
    email_features_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True

    assets_root_path: str = r"\\192.168.0.10\Shared\agency-crm-assets"
    assets_upload_token_expire_minutes: int = Field(default=15, ge=5, le=60)

    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None

    @field_validator("jwt_secret_key")
    @classmethod
    def jwt_secret_must_be_strong(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return value

    @model_validator(mode="after")
    def production_must_not_be_debug(self) -> "Settings":
        if self.environment == "production" and self.debug:
            raise ValueError("DEBUG must be false when ENVIRONMENT is production")
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def cors_allow_all_origins(self) -> bool:
        """True when CORS_ALLOWED_ORIGINS is * (local dev — reflects any Origin header)."""
        return self.cors_allowed_origins.strip() == "*"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    # Cached per process; bootstrap loads backend/.env (overriding stale OS env) first.
    # Restart the process after editing .env — nothing is persisted at OS level.
    from app.core.bootstrap import bootstrap_env

    bootstrap_env()
    return Settings()


def mask_secret(value: str | None) -> str:
    if not value:
        return "unset"
    if len(value) <= 8:
        return f"set(len={len(value)})"
    return f"set(len={len(value)}, prefix={value[:4]}***)"
