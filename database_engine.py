#!/usr/bin/env python3
"""
database_engine.py — SQLAlchemy engine factory for multi-database support.

Returns a SQLAlchemy engine based on ``settings.database_url``.
Defaults to the canonical ``data/lotto.db`` for local development.
Set ``DATABASE_URL=postgresql://user:pass@host/db`` for PostgreSQL.

Usage:
    from database_engine import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(...)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import StaticPool

from config.settings import DB_PATH, PROJECT_ROOT

_engine: Engine | None = None


def _absolute_sqlite_url(url: str) -> str:
    """Resolve relative SQLite URLs against the project root, not the cwd."""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw_path = url[len(prefix):]
    if raw_path == ":memory:" or Path(raw_path).is_absolute():
        return url
    return f"sqlite:///{(PROJECT_ROOT / raw_path).resolve()}"


def _build_url() -> str:
    """Resolve the database URL from settings or environment."""
    try:
        from settings import settings

        url = getattr(settings, "database_url", None)
        if url:
            return _absolute_sqlite_url(cast(str, url))
    except ImportError:
        pass

    # Fallback: check env var directly
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return _absolute_sqlite_url(env_url)

    # Ultimate fallback: the canonical absolute SQLite path.
    return f"sqlite:///{DB_PATH}"


def get_engine() -> Engine:
    """Return a SQLAlchemy engine (singleton — created once, reused thereafter).

    The URL is resolved via ``settings.database_url`` or the ``DATABASE_URL``
    environment variable.  Falls back to the canonical ``data/lotto.db``.
    """
    global _engine
    if _engine is not None:
        return _engine

    url = _build_url()
    connect_args: dict[str, Any] = {}

    if url.startswith("sqlite"):
        # SQLite-specific: enable WAL mode, disable same-thread check
        connect_args["check_same_thread"] = False
        _engine = create_engine(
            url,
            connect_args=connect_args,
            poolclass=StaticPool,  # SQLite doesn't need connection pooling
            echo=False,
        )

        # Enable WAL mode on connect for better concurrency
        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    else:
        # PostgreSQL / other databases — pooling parameters come from the
        # canonical app config (DB_POOL_SIZE, DB_MAX_OVERFLOW, …).
        try:
            from config_manager import get_settings

            pool_kwargs = get_settings().sqlalchemy_engine_kwargs()
        except Exception:
            pool_kwargs = {"pool_size": 5, "max_overflow": 10, "pool_pre_ping": True}
        _engine = create_engine(url, echo=False, **pool_kwargs)

    return _engine


def reset_engine() -> None:
    """Reset the cached engine (useful for testing with different URLs)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None
