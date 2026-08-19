#!/usr/bin/env python3
"""
config/settings.py — Canonical, type-safe application configuration.

Single source of truth for platform/app-level settings, built on
pydantic-settings. Lottery-domain tuning (prize pools, division caps, …)
stays in the legacy root ``settings.py``; this module owns the app
runtime: secrets, server, CORS, rate limiting, Redis, notifications,
backups.

Environment variables are UPPERCASE (case_sensitive=True). Legacy names
from earlier deployments are accepted via aliases (JWT_SECRET_KEY,
SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD).

SECRET_KEY ships with a recognizable insecure default so imports never
crash without a .env; config_manager.validate_startup() refuses to boot
in production (DEBUG=false) while it is unchanged.
"""

from __future__ import annotations

import sys

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Recognizable insecure defaults that must never run in production.
INSECURE_SECRET_VALUES = frozenset(
    {
        "",
        "changeme",
        "change-me-in-production-lotto-app-secret",
        "dev-only-insecure-secret-change-me",
    }
)


class Settings(BaseSettings):
    """Application configuration, loaded from env vars / .env."""

    # ---- App ----
    APP_NAME: str = "Lotto Wheel App"
    DEBUG: bool = False
    VERSION: str = "2.0.0"
    SECRET_KEY: str = Field(
        default="dev-only-insecure-secret-change-me",
        min_length=32,
        validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET_KEY"),
    )

    # ---- Database ----
    DATABASE_URL: str = "sqlite:///data/lotto.db"
    DB_PATH: str = "lotto.db"
    DB_POOL_SIZE: int = 5

    # ---- API ----
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    INTERNAL_NOTIFY_TOKEN: str = ""

    # ---- Rate limiting ----
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 60
    RATE_LIMIT_WINDOW: int = 60  # seconds

    # ---- Redis (optional; in-memory fallback when unset/unreachable) ----
    REDIS_URL: str | None = "redis://localhost:6379"

    # ---- Notifications ----
    SMTP_HOST: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_HOST", "SMTP_SERVER"),
    )
    SMTP_PORT: int = 587
    SMTP_USER: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_USER", "SMTP_USERNAME"),
    )
    SMTP_PASS: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_PASS", "SMTP_PASSWORD"),
    )
    ALERT_WEBHOOK_URL: str | None = None

    # ---- Backup ----
    BACKUP_ENABLED: bool = True
    BACKUP_RETENTION_DAYS: int = 30

    # ---- Lottery ----
    DEFAULT_POOL_SIZE: int = 40
    DEFAULT_TICKET_SIZE: int = 6

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        """Accept comma-separated strings as well as JSON lists."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


# Singleton instance — import this (or get_settings()) everywhere.
# Invalid env configuration (e.g. SECRET_KEY under 32 chars) fails fast
# with a clear message and exit code 1 instead of a raw traceback.
try:
    settings = Settings()
except ValidationError as exc:
    print("Configuration error — invalid environment settings:", file=sys.stderr)
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"])
        print(f"  - {field}: {err['msg']}", file=sys.stderr)
    sys.exit(1)


def get_settings() -> Settings:
    """FastAPI-friendly accessor: ``Depends(get_settings)``."""
    return settings
