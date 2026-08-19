#!/usr/bin/env python3
"""
monitoring/health.py — System health checks for the Lotto Wheel API.

Each check returns a short status string: "ok", "warn: <reason>", or
"fail: <reason>".  run_all_checks() aggregates them into the GET /health
payload and decides the HTTP status:

  - 200 "healthy"  — every check ok
  - 200 "degraded" — at least one warning, no critical failures
  - 503 "unhealthy"— a critical check failed (database, disk unreadable)

Redis is non-critical: the API falls back to in-memory caching/rate
limiting when it is down, so a Redis failure degrades rather than 503s.
"""

from __future__ import annotations

import glob
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from typing import Any

try:
    import psutil as psutil  # explicit re-export for monitoring.metrics
except ImportError:  # pragma: no cover - psutil is a pinned dependency
    psutil = None

# Thresholds
DISK_WARN_FREE_RATIO = 0.10  # warn if < 10% free
MEMORY_WARN_USED_RATIO = 0.90  # warn if > 90% used
DRAW_STALE_HOURS = 72  # warn if the latest draw is older than this
BACKUP_STALE_HOURS = 48  # warn if the newest backup is older than this

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_database(db_path: str) -> str:
    """Open the SQLite DB and count draws. Critical check."""
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        try:
            conn.execute("SELECT COUNT(*) FROM draws").fetchone()
        finally:
            conn.close()
        return "ok"
    except Exception as exc:
        return f"fail: {exc}"


def check_redis(redis_url: str) -> str:
    """Ping Redis. Non-critical (the API has in-memory fallbacks)."""
    try:
        import redis

        client = redis.Redis.from_url(redis_url, socket_timeout=1)
        client.ping()
        return "ok"
    except Exception as exc:
        return f"fail: {exc}"


def check_disk_space(path: str = _ROOT) -> str:
    """Free disk ratio. Warns below 10% free; fails if unreadable."""
    try:
        usage = shutil.disk_usage(path)
    except Exception as exc:
        return f"fail: {exc}"
    free_ratio = usage.free / usage.total if usage.total else 0.0
    if free_ratio < DISK_WARN_FREE_RATIO:
        return f"warn: only {free_ratio * 100:.1f}% free"
    return "ok"


def check_memory() -> str:
    """System memory usage. Warns above 90% used."""
    if psutil is None:
        return "warn: psutil not installed"
    try:
        used_ratio = psutil.virtual_memory().percent / 100.0
    except Exception as exc:
        return f"fail: {exc}"
    if used_ratio > MEMORY_WARN_USED_RATIO:
        return f"warn: {used_ratio * 100:.1f}% used"
    return "ok"


def check_backup(backup_dir: str | None = None) -> str:
    """Latest database backup freshness. Non-critical check.

    Warns when no backup exists or the newest backup (.db or .db.gz in
    backups/) is older than BACKUP_STALE_HOURS.
    """
    backup_dir = backup_dir or os.path.join(_ROOT, "backups")
    try:
        candidates: list[str] = []
        for pattern in ("lotto_*.db", "lotto_*.db.gz"):
            candidates.extend(p for p in glob.glob(os.path.join(backup_dir, pattern)))
        if not candidates:
            return "warn: no backups found"
        newest = max(os.path.getmtime(p) for p in candidates)
    except OSError as exc:
        return f"warn: {exc}"
    age_hours = (datetime.now().timestamp() - newest) / 3600.0
    if age_hours > BACKUP_STALE_HOURS:
        return f"warn: latest backup {age_hours:.0f}h old"
    return "ok"


def last_draw_age_hours(db_path: str) -> float | None:
    """Hours since the most recent draw_date, or None if no draws exist."""
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        try:
            row = conn.execute("SELECT MAX(draw_date) FROM draws").fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row or not row[0]:
        return None
    try:
        latest = datetime.fromisoformat(str(row[0]))
    except ValueError:
        return None
    age = datetime.now() - latest
    return round(age.total_seconds() / 3600.0, 1)


def draw_count(db_path: str) -> int:
    """Number of draws in the database (0 on error)."""
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        try:
            row = conn.execute("SELECT COUNT(*) FROM draws").fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def run_all_checks(db_path: str, redis_url: str, version: str) -> dict[str, Any]:
    """Run every check and build the /health response payload.

    Returns:
        dict with status, timestamp, version, checks, draws (row count),
        and http_status (200 or 503).
    """
    checks: dict[str, Any] = {
        "database": check_database(db_path),
        "redis": check_redis(redis_url),
        "disk_space": check_disk_space(),
        "memory": check_memory(),
        "backup": check_backup(),
    }

    age = last_draw_age_hours(db_path)
    if age is None:
        checks["last_draw_age_hours"] = "warn: no draws found"
    else:
        checks["last_draw_age_hours"] = f"warn: {age}h old" if age > DRAW_STALE_HOURS else age

    values = [v if isinstance(v, str) else "ok" for v in checks.values()]
    critical_failed = any(v.startswith("fail") for v in (checks["database"],)) or checks[
        "disk_space"
    ].startswith("fail")
    any_warn = any(v.startswith(("warn", "fail")) for v in values)

    if critical_failed:
        status, http_status = "unhealthy", 503
    elif any_warn:
        status, http_status = "degraded", 200
    else:
        status, http_status = "healthy", 200

    return {
        "status": status,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": version,
        "checks": checks,
        "draws": draw_count(db_path),
        "http_status": http_status,
    }
