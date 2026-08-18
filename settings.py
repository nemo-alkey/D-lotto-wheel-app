#!/usr/bin/env python3
"""
settings.py — Centralised configuration for the NZ Lotto Wheel Analysis platform.

All configuration lives in one Pydantic BaseSettings object.  Every value can be
overridden by an environment variable or a ``.env`` file.  Import ``settings``
from this module everywhere instead of hardcoding constants or reading os.environ
directly.

Usage:
    from settings import settings
    print(settings.div1_cap)  # → 50000000.0
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_THIS_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Typed, overridable configuration for the entire application."""

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        default_factory=lambda: f"sqlite:///{_THIS_DIR / 'lotto.db'}",
        description="SQLAlchemy database URL.  Set to postgresql://... for PostgreSQL.",
    )
    db_path: str = Field(
        default_factory=lambda: str(_THIS_DIR / "lotto.db"),
        description="Path to the main SQLite database.",
    )
    prize_cache_file: str = Field(
        default_factory=lambda: str(_THIS_DIR / "prize_cache.json"),
        description="Path to the prize payout cache JSON file.",
    )
    alert_log: str = Field(
        default_factory=lambda: str(_THIS_DIR / "alert.log"),
        description="Path to the alert log file.",
    )
    ticket_store: str = Field(
        default_factory=lambda: str(_THIS_DIR / "latest_tickets.json"),
        description="Path to the stored tickets JSON file.",
    )

    # ------------------------------------------------------------------
    # JWT Authentication
    # ------------------------------------------------------------------
    jwt_secret_key: str = Field(
        default="change-me-in-production-lotto-app-secret",
        description="Secret key for signing JWT tokens.  CHANGE IN PRODUCTION.",
    )
    jwt_expire_minutes: int = Field(
        default=15,
        ge=1,
        description="JWT access token lifetime in minutes.",
    )
    jwt_refresh_expire_days: int = Field(
        default=7,
        ge=1,
        description="JWT refresh token lifetime in days.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm.",
    )

    # ------------------------------------------------------------------
    # Admin credentials (initial admin account)
    # ------------------------------------------------------------------
    admin_username: str = Field(
        default="admin",
        description="Default admin username created on first run.",
    )
    admin_password: str = Field(
        default="admin",
        description="Default admin password.  CHANGE IN PRODUCTION.",
    )

    # ------------------------------------------------------------------
    # SMTP / Notifier
    # ------------------------------------------------------------------
    smtp_server: str = Field(
        default="smtp.gmail.com",
        description="SMTP server hostname.",
    )
    smtp_port: int = Field(
        default=587,
        description="SMTP server port (587 for TLS, 465 for SSL).",
    )
    smtp_username: str | None = Field(
        default=None,
        description="SMTP username (email address).",
    )
    smtp_password: str | None = Field(
        default=None,
        description="SMTP password or app password.",
    )
    smtp_from: str | None = Field(
        default=None,
        description="From address for email alerts (defaults to smtp_username).",
    )
    alert_email_to: str | None = Field(
        default=None,
        description="Recipient email address for alerts.",
    )

    # ------------------------------------------------------------------
    # Prize Pool & Allocation
    # ------------------------------------------------------------------
    prize_pool_ratio: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Fraction of turnover that goes to the prize pool.",
    )
    reserve_lotto: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Fraction of Lotto turnover reserved for operating costs / grants.",
    )
    reserve_powerball: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Fraction of Powerball turnover reserved for operating costs / grants.",
    )
    div1_cap: float = Field(
        default=50_000_000.0,
        ge=0.0,
        description="Maximum NZ Powerball Division 1 payout per winner (NZD).",
    )
    max_consecutive_jackpots: int = Field(
        default=10,
        ge=0,
        description="Maximum number of consecutive Div 1 rollovers before a must-win draw.",
    )
    div7_pb_prize: float = Field(
        default=15.0,
        description="Fixed prize per Div 7 winner in Powerball (NZD).",
    )
    div7_lotto_prize: float = Field(
        default=2.80,
        description="Fixed prize value per Div 7 winner in Lotto-only (bonus ticket, NZD).",
    )
    default_lotto_pool: float = Field(
        default=215_000.0,
        description="Estimated typical Lotto prize pool for fallback calculations.",
    )
    default_powerball_turnover: float = Field(
        default=2_500_000.0,
        description="Estimated typical Powerball draw turnover for pool allocation.",
    )
    default_strike_pool: float = Field(
        default=350_000.0,
        description="Estimated typical Lotto Strike prize pool for fallback calculations.",
    )
    strike_div4_fixed: float = Field(
        default=1.00,
        description="Fixed prize for Strike Division 4 (bonus selection).",
    )

    # Lotto Strike pool percentages (first 4 balls in exact order)
    strike_pool_percentages: dict[int, float] = Field(
        default={
            1: 65.0,
            2: 20.0,
            3: 15.0,
            4: 0.0,  # Div 4 is a fixed prize
        },
        description="Lotto Strike pool percentage shares for Divisions 1–4.",
    )

    # Powerball prize pool percentages (after Div 7 fixed prizes deducted)
    pb_pool_percentages: dict[int, float] = Field(
        default={
            1: 85.74,
            2: 2.23,
            3: 2.23,
            4: 0.60,
            5: 4.64,
            6: 4.56,
            7: 0.0,
        },
        description="Powerball pool percentage shares for Divisions 1–7.",
    )

    # Standard Lotto prize pool percentages (no Powerball)
    lotto_pool_percentages: dict[int, float] = Field(
        default={
            1: 34.6,
            2: 10.1,
            3: 10.5,
            4: 2.5,
            5: 21.5,
            6: 20.8,
            7: 0.0,
        },
        description="Standard Lotto pool percentage shares for Divisions 1–7.",
    )

    # ------------------------------------------------------------------
    # Selenium / Scraping
    # ------------------------------------------------------------------
    selenium_chrome_binary: str | None = Field(
        default=None,
        description="Full path to the Chrome/Chromium binary for Selenium.",
    )
    use_selenium_fallback: bool = Field(
        default=False,
        description="Enable Selenium-based scraper as last-resort fallback.",
    )

    # ------------------------------------------------------------------
    # Rate Limits (FastAPI / slowapi)
    # ------------------------------------------------------------------
    api_rate_limit: str = Field(
        default="60/minute",
        description="Default rate limit for most API endpoints.",
    )
    heavy_rate_limit: str = Field(
        default="5/minute",
        description="Rate limit for compute-heavy endpoints (EV sim, backtest).",
    )

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    draws_per_week: int = Field(
        default=2,
        ge=1,
        le=7,
        description="Number of draws per week (NZ Lotto = 2: Wed + Sat).",
    )
    decay_per_draw: float = Field(
        default=0.98 ** (1.0 / 2.0),
        description="Exponential decay factor per draw for Bayesian models.",
    )
    ticket_cost: float = Field(
        default=1.50,
        description="Cost per ticket line in NZD.",
    )

    # ------------------------------------------------------------------
    # External API
    # ------------------------------------------------------------------
    api_base: str = Field(
        default="https://pathway.mylotto.co.nz",
        description="Base URL for the MyLotto API.",
    )
    api_timeout: int = Field(
        default=15,
        ge=1,
        description="Timeout in seconds for MyLotto API requests.",
    )
    polite_delay: float = Field(
        default=2.0,
        ge=0.0,
        description="Delay in seconds between successive API fetches.",
    )
    cache_ttl_days: int = Field(
        default=7,
        ge=1,
        description="Cache TTL in days for prize payouts (draws are Wed+Sat, so 7d is safe).",
    )
    cache_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        description="Default Streamlit cache TTL in seconds (1 hour).",
    )
    retry_delays: list[float] = Field(
        default=[1.0, 2.0, 4.0],
        description="Exponential backoff delays in seconds for API retries.",
    )

    # ------------------------------------------------------------------
    # Static fallback payouts (used when API is unavailable)
    # ------------------------------------------------------------------
    fallback_lotto: dict[int, float] = Field(
        default={
            1: 1_000_000.0,
            2: 30_000.0,
            3: 1_000.0,
            4: 100.0,
            5: 60.0,
            6: 40.0,
            7: 20.0,
        },
        description="Static fallback Lotto division prizes when API is unavailable.",
    )
    fallback_pb: dict[int, float] = Field(
        default={
            1: 0.0,
            2: 0.0,
            3: 0.0,
            4: 0.0,
            5: 0.0,
            6: 0.0,
            7: 0.0,
        },
        description="Static fallback Powerball division prizes when API is unavailable.",
    )

    # ------------------------------------------------------------------
    # Pydantic configuration
    # ------------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )


# ------------------------------------------------------------------
# Singleton instance — import this everywhere
# ------------------------------------------------------------------
settings = Settings()
