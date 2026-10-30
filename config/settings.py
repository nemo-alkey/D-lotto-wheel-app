#!/usr/bin/env python3
"""
config/settings.py — Canonical, type-safe application configuration.

Single source of truth for platform/app-level settings, built on
pydantic-settings. Lottery-domain tuning (prize pools, division caps, …)
stays in the legacy root ``settings.py``; this module owns the app
runtime: secrets, server, CORS, rate limiting, Redis, notifications,
payments (Stripe), feature flags, and backups.

Environment variables are UPPERCASE (case_sensitive=True). Legacy names
from earlier deployments are accepted via aliases (JWT_SECRET_KEY,
SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD).

Deployment tiers (ENVIRONMENT=development|staging|production):
- development/staging: values may come from a local ``.env`` file.
- production: ``.env`` is ignored — secrets must be injected as real
  environment variables by the platform (never read from files).

SECRET_KEY ships with a recognizable insecure default so imports never
crash without a .env; config_manager.validate_startup() refuses to boot
in production while it is unchanged.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Literal

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

# Field-name fragments whose values are masked in admin/debug dumps.
_SENSITIVE_NAME_PARTS = ("SECRET", "PASSWORD", "PASS", "TOKEN", "_KEY")

_URL_PASSWORD_RE = re.compile(r"(://[^:/\s]*:)([^@\s]+)(@)")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(PROJECT_ROOT / "data" / "lotto.db")

Environment = Literal["development", "staging", "production"]


def _mask_url_password(url: str) -> str:
    """Replace the password component of a URL with ``****``."""
    return _URL_PASSWORD_RE.sub(r"\1****\3", url)


class Settings(BaseSettings):
    """Application configuration, loaded from env vars / .env."""

    # ---- App ----
    APP_NAME: str = "Lotto Wheel App"
    DEBUG: bool = False
    VERSION: str = "2.0.0"
    ENVIRONMENT: Environment = "development"
    SECRET_KEY: str = Field(
        default="dev-only-insecure-secret-change-me",
        min_length=32,
        validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET_KEY"),
    )

    # ---- Database ----
    # PostgreSQL in production (pooled); SQLite fallback for local dev.
    DATABASE_URL: str = f"sqlite:///{DB_PATH}"
    DB_PATH: str = DB_PATH
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30  # seconds to wait for a pooled connection
    DB_POOL_RECYCLE: int = 1800  # seconds before a connection is recycled

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

    # ---- Redis (caching + rate limiting; in-memory fallback when unset) ----
    REDIS_URL: str | None = "redis://localhost:6379"

    # ---- Email (SMTP) ----
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

    # ---- Stripe (payments) ----
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_PUBLISHABLE_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None

    # ---- Feature flags ----
    FEATURE_ML_PREDICTIONS: bool = True
    FEATURE_BACKTESTING: bool = True
    FEATURE_WEBSOCKETS: bool = True
    FEATURE_PAYMENTS: bool = False
    FEATURE_EMAIL_ALERTS: bool = True

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

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def is_production(self) -> bool:
        """True when running a production deployment.

        Either ENVIRONMENT=production or DEBUG=false marks the deployment
        as production for validation purposes — both must be deliberately
        relaxed to get insecure dev behavior.
        """
        return self.ENVIRONMENT == "production" or not self.DEBUG

    @property
    def database_backend(self) -> str:
        """Database backend derived from DATABASE_URL: postgresql/sqlite/other."""
        url = self.DATABASE_URL.lower()
        if url.startswith(("postgresql://", "postgresql+", "postgres://")):
            return "postgresql"
        if url.startswith("sqlite"):
            return "sqlite"
        return "other"

    def sqlalchemy_engine_kwargs(self) -> dict[str, Any]:
        """create_engine() kwargs: connection pooling for PostgreSQL only.

        SQLite gets ``check_same_thread=False`` and no pooling (callers use
        StaticPool); PostgreSQL gets a bounded pool with pre-ping so stale
        connections are detected instead of erroring mid-request.
        """
        if self.database_backend == "postgresql":
            return {
                "pool_size": self.DB_POOL_SIZE,
                "max_overflow": self.DB_MAX_OVERFLOW,
                "pool_timeout": self.DB_POOL_TIMEOUT,
                "pool_recycle": self.DB_POOL_RECYCLE,
                "pool_pre_ping": True,
            }
        if self.database_backend == "sqlite":
            return {"connect_args": {"check_same_thread": False}}
        return {}

    # ------------------------------------------------------------------
    # Feature flags
    # ------------------------------------------------------------------

    def feature_flags(self) -> dict[str, bool]:
        """All feature flags as {snake_case_name: enabled}."""
        return {
            name.removeprefix("FEATURE_").lower(): bool(getattr(self, name))
            for name in type(self).model_fields
            if name.startswith("FEATURE_")
        }

    def feature_enabled(self, name: str) -> bool:
        """Check one flag, e.g. ``feature_enabled("payments")``."""
        return self.feature_flags().get(name.lower(), False)

    # ------------------------------------------------------------------
    # Safe serialization (config endpoints)
    # ------------------------------------------------------------------

    @property
    def smtp_configured(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_USER)

    @property
    def stripe_configured(self) -> bool:
        return bool(self.STRIPE_SECRET_KEY and self.STRIPE_PUBLISHABLE_KEY)

    def public_summary(self) -> dict[str, Any]:
        """Non-sensitive runtime config — safe to expose unauthenticated."""
        return {
            "app_name": self.APP_NAME,
            "version": self.VERSION,
            "environment": self.ENVIRONMENT,
            "debug": self.DEBUG,
            "features": self.feature_flags(),
            "database": {
                "backend": self.database_backend,
                "pooling": self.database_backend == "postgresql",
            },
            "redis_configured": bool(self.REDIS_URL),
            "smtp_configured": self.smtp_configured,
            "stripe_configured": self.stripe_configured,
            "rate_limit": {
                "enabled": self.RATE_LIMIT_ENABLED,
                "requests": self.RATE_LIMIT_REQUESTS,
                "window_seconds": self.RATE_LIMIT_WINDOW,
            },
        }

    def masked_dump(self) -> dict[str, Any]:
        """Full config with secrets masked — for admin eyes only.

        Fields whose name contains SECRET/PASS/TOKEN/_KEY are replaced by
        ``********`` when set. URLs keep their scheme/host but the password
        component is masked.
        """
        masked: dict[str, Any] = {}
        for name, value in self.model_dump().items():
            if value is None:
                masked[name] = None
            elif any(part in name for part in _SENSITIVE_NAME_PARTS):
                masked[name] = "********" if value else None
            elif isinstance(value, str) and "://" in value and "@" in value:
                masked[name] = _mask_url_password(value)
            else:
                masked[name] = value
        return masked


# Singleton instance — import this (or get_settings()) everywhere.
# In production (ENVIRONMENT=production) the .env file is ignored: secrets
# must come from the process environment, never from files on disk.
# Invalid env configuration (e.g. SECRET_KEY under 32 chars) fails fast
# with a clear message and exit code 1 instead of a raw traceback.
_env_file: str | None = ".env"
if os.environ.get("ENVIRONMENT", "").strip().lower() == "production":
    _env_file = None

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
