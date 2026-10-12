#!/usr/bin/env python3
"""
config_manager.py — Centralized configuration access and startup validation.

Usage:
    from config_manager import get_settings, validate_startup

    cfg = get_settings()              # singleton Settings instance
    validate_startup()                # call once at app boot

FastAPI dependency injection:
    @app.get("/config")
    def read_config(cfg: Settings = Depends(get_settings)):
        return {"debug": cfg.DEBUG, "version": cfg.VERSION}

validate_startup() fails fast: configuration errors print a clear message
and exit with code 1. In production mode (ENVIRONMENT=production or
DEBUG=False) an unchanged placeholder SECRET_KEY, a wildcard CORS origin,
or a missing DATABASE_URL is fatal; DEBUG=True in production earns a loud
warning. collect_config_issues() exposes the same checks without exiting,
for the pre-deploy verification script (scripts/verify_config.py).
"""

from __future__ import annotations

import sys
import warnings

from config.settings import INSECURE_SECRET_VALUES, Settings, get_settings

__all__ = ["Settings", "get_settings", "collect_config_issues", "validate_startup"]


def collect_config_issues(cfg: Settings) -> tuple[list[str], list[str]]:
    """Check configuration; return (errors, warnings) without exiting.

    Errors are fatal in production — validate_startup() exits with code 1
    when any are present. Warnings are logged but do not block startup.
    """
    errors: list[str] = []
    warns: list[str] = []

    if cfg.is_production:
        if cfg.SECRET_KEY in INSECURE_SECRET_VALUES:
            errors.append(
                "SECRET_KEY is unset or a placeholder — set a strong random "
                "secret of at least 32 characters, e.g. "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if not cfg.DATABASE_URL:
            errors.append("DATABASE_URL is empty — set a database connection URL")
        if "*" in cfg.CORS_ORIGINS:
            errors.append(
                "CORS_ORIGINS contains '*' — list explicit origins instead "
                "(comma-separated, e.g. CORS_ORIGINS=https://app.example.com)"
            )
        if cfg.FEATURE_PAYMENTS and not cfg.stripe_configured:
            errors.append(
                "FEATURE_PAYMENTS=true but Stripe keys are missing — set "
                "STRIPE_SECRET_KEY and STRIPE_PUBLISHABLE_KEY, or disable the flag"
            )

    # Warn when DEBUG is left on for a production deployment.
    if cfg.ENVIRONMENT == "production" and cfg.DEBUG:
        warns.append(
            "DEBUG=true while ENVIRONMENT=production — disable debug mode "
            "before serving real traffic."
        )

    # DEBUG=True with no localhost origin looks like a prod deployment
    # still running in debug mode.
    if cfg.DEBUG and not any(
        "localhost" in origin or "127.0.0.1" in origin for origin in cfg.CORS_ORIGINS
    ):
        warns.append(
            "DEBUG=True but CORS_ORIGINS contains no localhost origin — "
            "this looks like a production deployment running in debug mode."
        )

    if cfg.is_production:
        if not cfg.REDIS_URL:
            warns.append(
                "REDIS_URL is unset — caching and rate limiting fall back to "
                "in-process memory, which does not scale across workers."
            )
        if cfg.FEATURE_EMAIL_ALERTS and not cfg.smtp_configured:
            warns.append(
                "FEATURE_EMAIL_ALERTS=true but SMTP is not configured — "
                "email alerts will be silently dropped."
            )
        stripe_keys = [cfg.STRIPE_SECRET_KEY, cfg.STRIPE_PUBLISHABLE_KEY, cfg.STRIPE_WEBHOOK_SECRET]
        if any(stripe_keys) and not all(stripe_keys):
            warns.append(
                "Stripe is partially configured — set STRIPE_SECRET_KEY, "
                "STRIPE_PUBLISHABLE_KEY, and STRIPE_WEBHOOK_SECRET together."
            )

    return errors, warns


def validate_startup(cfg: Settings | None = None) -> Settings:
    """Validate the live configuration; exit(1) on fatal problems.

    Args:
        cfg: Settings to validate (default: the singleton instance).

    Returns:
        The validated Settings instance.

    Raises:
        SystemExit: code 1 when required configuration is missing or
            insecure in production mode.
    """
    cfg = cfg or get_settings()
    errors, warns = collect_config_issues(cfg)

    for message in warns:
        warnings.warn(message, stacklevel=2)

    if errors:
        print(
            "Configuration error — refusing to start:\n  - " + "\n  - ".join(errors),
            file=sys.stderr,
        )
        sys.exit(1)

    return cfg
