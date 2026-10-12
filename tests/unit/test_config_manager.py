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


# ---------------------------------------------------------------------------
# Environment tiers
# ---------------------------------------------------------------------------


def test_environment_defaults_to_development() -> None:
    assert _isolated().ENVIRONMENT == "development"


def test_environment_accepts_staging_and_production() -> None:
    assert _isolated(ENVIRONMENT="staging").ENVIRONMENT == "staging"
    assert _isolated(ENVIRONMENT="production").ENVIRONMENT == "production"


def test_environment_rejects_invalid_value() -> None:
    with pytest.raises(ValidationError):
        _isolated(ENVIRONMENT="qa")


def test_is_production_property() -> None:
    assert _isolated(ENVIRONMENT="production", DEBUG=True).is_production
    assert _isolated(ENVIRONMENT="development", DEBUG=False).is_production
    assert not _isolated(ENVIRONMENT="development", DEBUG=True).is_production


# ---------------------------------------------------------------------------
# Database backends and pooling
# ---------------------------------------------------------------------------


def test_database_backend_detection() -> None:
    assert _isolated().database_backend == "sqlite"
    assert _isolated(DATABASE_URL="postgresql://u:p@db:5432/lotto").database_backend == "postgresql"
    assert _isolated(DATABASE_URL="postgres://u:p@db/lotto").database_backend == "postgresql"
    assert _isolated(DATABASE_URL="mysql://u:p@db/lotto").database_backend == "other"


def test_engine_kwargs_postgres_pooling() -> None:
    cfg = _isolated(
        DATABASE_URL="postgresql://u:p@db:5432/lotto",
        DB_POOL_SIZE=9,
        DB_MAX_OVERFLOW=3,
        DB_POOL_TIMEOUT=11,
        DB_POOL_RECYCLE=60,
    )
    kwargs = cfg.sqlalchemy_engine_kwargs()
    assert kwargs == {
        "pool_size": 9,
        "max_overflow": 3,
        "pool_timeout": 11,
        "pool_recycle": 60,
        "pool_pre_ping": True,
    }


def test_engine_kwargs_sqlite_has_no_pooling() -> None:
    kwargs = _isolated().sqlalchemy_engine_kwargs()
    assert "pool_size" not in kwargs
    assert kwargs["connect_args"] == {"check_same_thread": False}


# ---------------------------------------------------------------------------
# Stripe and feature flags
# ---------------------------------------------------------------------------


def test_stripe_defaults_unconfigured() -> None:
    cfg = _isolated()
    assert cfg.STRIPE_SECRET_KEY is None
    assert cfg.stripe_configured is False


def test_feature_flags_defaults() -> None:
    flags = _isolated().feature_flags()
    assert flags == {
        "ml_predictions": True,
        "backtesting": True,
        "websockets": True,
        "payments": False,
        "email_alerts": True,
    }


def test_feature_enabled() -> None:
    cfg = _isolated(FEATURE_PAYMENTS=True)
    assert cfg.feature_enabled("payments") is True
    assert cfg.feature_enabled("websockets") is True
    assert cfg.feature_enabled("no-such-feature") is False


# ---------------------------------------------------------------------------
# Safe serialization
# ---------------------------------------------------------------------------


def test_masked_dump_masks_secrets() -> None:
    cfg = _isolated(
        SECRET_KEY="s" * 40,
        INTERNAL_NOTIFY_TOKEN="topsecret",
        STRIPE_SECRET_KEY="sk_live_123",
    )
    dump = cfg.masked_dump()
    assert dump["SECRET_KEY"] == "********"
    assert dump["INTERNAL_NOTIFY_TOKEN"] == "********"
    assert dump["STRIPE_SECRET_KEY"] == "********"
    assert dump["STRIPE_PUBLISHABLE_KEY"] is None  # unset stays None
    assert dump["APP_NAME"] == "Lotto Wheel App"


def test_masked_dump_masks_url_passwords() -> None:
    cfg = _isolated(
        DATABASE_URL="postgresql://user:hunter2@db:5432/lotto",
        REDIS_URL="redis://:hunter2@redis:6379/0",
    )
    dump = cfg.masked_dump()
    assert dump["DATABASE_URL"] == "postgresql://user:****@db:5432/lotto"
    assert dump["REDIS_URL"] == "redis://:****@redis:6379/0"


def test_public_summary_has_no_secret_values() -> None:
    cfg = _isolated(SECRET_KEY="s" * 40, SMTP_PASS="hunter2")
    summary = cfg.public_summary()
    assert summary["version"] == "2.0.0"
    assert summary["environment"] == "development"
    assert isinstance(summary["features"], dict)
    assert summary["database"]["backend"] == "sqlite"
    assert summary["smtp_configured"] is False  # SMTP_HOST still unset
    serialized = str(summary)
    assert "s" * 40 not in serialized
    assert "hunter2" not in serialized


# ---------------------------------------------------------------------------
# Extended startup validation
# ---------------------------------------------------------------------------


def test_validate_startup_prod_rejects_empty_database_url() -> None:
    cfg = _isolated(
        DEBUG=False,
        SECRET_KEY="s" * 40,
        CORS_ORIGINS="https://app.example.com",
        DATABASE_URL="",
    )
    with pytest.raises(SystemExit) as exc_info:
        validate_startup(cfg)
    assert exc_info.value.code == 1


def test_validate_startup_prod_payments_without_stripe_errors() -> None:
    cfg = _isolated(
        DEBUG=False,
        SECRET_KEY="s" * 40,
        CORS_ORIGINS="https://app.example.com",
        FEATURE_PAYMENTS=True,
    )
    with pytest.raises(SystemExit) as exc_info:
        validate_startup(cfg)
    assert exc_info.value.code == 1


def test_validate_startup_prod_payments_ok_with_stripe_keys() -> None:
    cfg = _isolated(
        DEBUG=False,
        SECRET_KEY="s" * 40,
        CORS_ORIGINS="https://app.example.com",
        FEATURE_PAYMENTS=True,
        STRIPE_SECRET_KEY="sk_live_x",
        STRIPE_PUBLISHABLE_KEY="pk_live_x",
        STRIPE_WEBHOOK_SECRET="whsec_x",
    )
    assert validate_startup(cfg) is cfg


def test_validate_startup_warns_debug_true_in_production_env() -> None:
    cfg = _isolated(
        ENVIRONMENT="production",
        DEBUG=True,
        SECRET_KEY="s" * 40,
        CORS_ORIGINS="http://localhost:5173",
    )
    with pytest.warns(UserWarning, match="debug mode"):
        validate_startup(cfg)


def test_validate_startup_prod_warns_partial_stripe() -> None:
    cfg = _isolated(
        DEBUG=False,
        SECRET_KEY="s" * 40,
        CORS_ORIGINS="https://app.example.com",
        STRIPE_SECRET_KEY="sk_live_x",  # only one of three
    )
    with pytest.warns(UserWarning, match="partially configured"):
        validate_startup(cfg)


def test_collect_config_issues_returns_without_exiting() -> None:
    from config_manager import collect_config_issues

    cfg = _isolated(DEBUG=False)  # placeholder SECRET_KEY → error
    errors, warns = collect_config_issues(cfg)
    assert any("SECRET_KEY" in e for e in errors)
    assert isinstance(warns, list)
