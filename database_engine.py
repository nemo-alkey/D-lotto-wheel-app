#!/usr/bin/env python3
"""
database_engine.py — SQLAlchemy engine factory for multi-database support.

Returns a SQLAlchemy engine based on ``settings.database_url``.
Defaults to ``sqlite:///lotto.db`` for local development.
Set ``DATABASE_URL=postgresql://user:pass@host/db`` for PostgreSQL.

Usage:
    from database_engine import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(...)
"""

from __future__ import annotations

import os
from typing import Any, cast

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import StaticPool

_engine: Engine | None = None


def _build_url() -> str:
    """Resolve the database URL from settings or environment."""
    try:
        from settings import settings

        url = getattr(settings, "database_url", None)
        if url:
            return cast(str, url)
    except ImportError:
        pass

    # Fallback: check env var directly
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    # Ultimate fallback: SQLite in the project root
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lotto.db")
    return f"sqlite:///{db_path}"


def get_engine() -> Engine:
    """Return a SQLAlchemy engine (singleton — created once, reused thereafter).

    The URL is resolved via ``settings.database_url`` or the ``DATABASE_URL``
    environment variable.  Falls back to ``sqlite:///lotto.db``.
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
        # PostgreSQL / other databases
        _engine = create_engine(
            url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # verify connections before use
            echo=False,
        )

    return _engine


def reset_engine() -> None:
    """Reset the cached engine (useful for testing with different URLs)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None
