#!/usr/bin/env python3
"""
config/secrets.py — Backward-compatible shim.

The canonical configuration now lives in ``config/settings.py`` (typed
pydantic-settings) with startup validation in ``config_manager.py``.
This module keeps the old import surface working for code that has not
migrated yet. Prefer::

    from config_manager import get_settings, validate_startup
"""

from __future__ import annotations

from config.settings import settings as _settings

# Placeholder values that must never be used in production.
INSECURE_DEFAULTS = frozenset(
    {
        "",
        "changeme",
        "change-me-in-production-lotto-app-secret",
        "dev-only-insecure-secret-change-me",
    }
)

DEBUG: bool = _settings.DEBUG
SECRET_KEY: str = _settings.SECRET_KEY
INTERNAL_NOTIFY_TOKEN: str = _settings.INTERNAL_NOTIFY_TOKEN


def cors_origins() -> list[str]:
    """Allowed CORS origins (explicit list; never "*" in production)."""
    return list(_settings.CORS_ORIGINS)


def validate_production_secrets() -> None:
    """Fail fast on insecure production configuration.

    Delegates to config_manager.validate_startup(), which exits with
    code 1 when DEBUG=false and secrets are placeholders or CORS is "*".
    """
    from config_manager import validate_startup

    validate_startup()
