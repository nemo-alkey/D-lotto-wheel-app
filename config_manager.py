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
and exit with code 1. In production mode (DEBUG=False) an unchanged
placeholder SECRET_KEY or a wildcard CORS origin is fatal; DEBUG=True
with no localhost in CORS_ORIGINS earns a loud warning.
"""

from __future__ import annotations

import sys
import warnings

from config.settings import INSECURE_SECRET_VALUES, Settings, get_settings

__all__ = ["Settings", "get_settings", "validate_startup"]


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
    problems: list[str] = []

    if not cfg.DEBUG:
        if cfg.SECRET_KEY in INSECURE_SECRET_VALUES:
            problems.append(
                "SECRET_KEY is unset or a placeholder — set a strong random "
                "secret of at least 32 characters, e.g. "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if "*" in cfg.CORS_ORIGINS:
            problems.append(
                "CORS_ORIGINS contains '*' — list explicit origins instead "
                "(comma-separated, e.g. CORS_ORIGINS=https://app.example.com)"
            )

    # DEBUG=True with no localhost origin looks like a prod deployment
    # still running in debug mode.
    if cfg.DEBUG and not any(
        "localhost" in origin or "127.0.0.1" in origin for origin in cfg.CORS_ORIGINS
    ):
        warnings.warn(
            "DEBUG=True but CORS_ORIGINS contains no localhost origin — "
            "this looks like a production deployment running in debug mode.",
            stacklevel=2,
        )

    if problems:
        print(
            "Configuration error — refusing to start:\n  - " + "\n  - ".join(problems),
            file=sys.stderr,
        )
        sys.exit(1)

    return cfg
