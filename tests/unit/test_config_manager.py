"""Unit tests for config/settings.py and config_manager.py."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from config.settings import Settings
from config_manager import get_settings, validate_startup


def _isolated(**overrides: Any) -> Settings:
    """A Settings instance that ignores .env and process env leakage."""
    overrides.setdefault("_env_file", None)
    return Settings(**overrides)


# ---------------------------------------------------------------------------
# Defaults and types
# ---------------------------------------------------------------------------


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest sets DEBUG=true for the app-level tests; clear it here so
    # we verify the shipped defaults.
    monkeypatch.delenv("DEBUG", raising=False)
    cfg = _isolated()
    assert cfg.APP_NAME == "Lotto Wheel App"
    assert cfg.DEBUG is False
    assert cfg.VERSION == "2.0.0"
    assert cfg.API_PORT == 8000
    assert cfg.DB_POOL_SIZE == 5
    assert cfg.RATE_LIMIT_ENABLED is True
    assert cfg.BACKUP_RETENTION_DAYS == 30
    assert cfg.DEFAULT_POOL_SIZE == 40
    assert cfg.DEFAULT_TICKET_SIZE == 6


def test_singleton_accessor() -> None:
    assert get_settings() is get_settings()


def test_secret_key_min_length_enforced() -> None:
    with pytest.raises(ValidationError):
        _isolated(SECRET_KEY="too-short")


def test_secret_key_alias_jwt_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    cfg = Settings(_env_file=None)  # type: ignore[call-arg]
    assert cfg.SECRET_KEY == "x" * 40


def test_cors_origins_comma_separated_parsing() -> None:
    cfg = _isolated(CORS_ORIGINS="https://a.com, https://b.com ,https://c.com")
    assert cfg.CORS_ORIGINS == ["https://a.com", "https://b.com", "https://c.com"]


def test_smtp_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    cfg = Settings(_env_file=None)  # type: ignore[call-arg]
    assert cfg.SMTP_HOST == "smtp.example.com"
    assert cfg.SMTP_USER == "user@example.com"


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


def test_validate_startup_prod_rejects_placeholder_secret() -> None:
    cfg = _isolated(DEBUG=False)  # default SECRET_KEY is a placeholder
    with pytest.raises(SystemExit) as exc_info:
        validate_startup(cfg)
    assert exc_info.value.code == 1


def test_validate_startup_prod_rejects_wildcard_cors() -> None:
    cfg = _isolated(DEBUG=False, SECRET_KEY="s" * 40, CORS_ORIGINS="*")
    with pytest.raises(SystemExit) as exc_info:
        validate_startup(cfg)
    assert exc_info.value.code == 1


def test_validate_startup_prod_ok_with_real_config() -> None:
    cfg = _isolated(DEBUG=False, SECRET_KEY="s" * 40, CORS_ORIGINS="https://app.example.com")
    assert validate_startup(cfg) is cfg


def test_validate_startup_warns_debug_in_production() -> None:
    cfg = _isolated(DEBUG=True, CORS_ORIGINS="https://app.example.com")
    with pytest.warns(UserWarning, match="debug mode"):
        validate_startup(cfg)


def test_validate_startup_debug_localhost_no_warning(
    recwarn: pytest.WarningsRecorder,
) -> None:
    cfg = _isolated(DEBUG=True, CORS_ORIGINS="http://localhost:5173")
    validate_startup(cfg)
    assert not recwarn.list
