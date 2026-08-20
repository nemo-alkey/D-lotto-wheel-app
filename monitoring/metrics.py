#!/usr/bin/env python3
"""
monitoring/metrics.py — Prometheus metrics for the Lotto Wheel API.

Exposed via GET /metrics (see api.py):

  http_requests_total{method,endpoint,status}   counter
  http_request_duration_seconds{method,endpoint} histogram
  predictions_generated_total{method}           counter
  wheels_generated_total{system_type}           counter
  active_users                                  gauge (distinct identities
                                                seen in the last 15 min)
  db_query_duration_seconds{operation}          histogram

A custom collector also runs the health checks at scrape time so
Prometheus can alert on them (see alerts.yml):

  health_check_ok{check}     1 = ok, 0 = warn/fail
  last_draw_age_hours        gauge
  disk_free_ratio            gauge
  memory_used_ratio          gauge
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, Literal, cast

import prometheus_client
from prometheus_client import Counter, Gauge, Histogram
from prometheus_client.core import GaugeMetricFamily, Metric
from starlette.requests import Request

from monitoring import health as _health

# ---------------------------------------------------------------------------
# Request / business metrics
# ---------------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "endpoint", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

PREDICTIONS_GENERATED = Counter(
    "predictions_generated_total",
    "Predictions generated, labeled by prediction method.",
    ["method"],
)

WHEELS_GENERATED = Counter(
    "wheels_generated_total",
    "Wheels generated, labeled by guarantee/system type.",
    ["system_type"],
)

ACTIVE_USERS = Gauge(
    "active_users",
    "Distinct users/IPs seen in the last 15 minutes.",
)

DB_QUERY_DURATION = Histogram(
    "db_query_duration_seconds",
    "Database query latency in seconds.",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)

# ---------------------------------------------------------------------------
# Active-user tracking (rolling 15-minute window)
# ---------------------------------------------------------------------------

_ACTIVE_WINDOW = timedelta(minutes=15)
_active_lock = threading.Lock()
_seen: dict[str, datetime] = {}


def record_active(identity: str) -> None:
    """Record activity for a user/IP identity and refresh the gauge."""
    now = datetime.now()
    with _active_lock:
        _seen[identity] = now
        cutoff = now - _ACTIVE_WINDOW
        stale = [k for k, ts in _seen.items() if ts < cutoff]
        for k in stale:
            del _seen[k]
        ACTIVE_USERS.set(len(_seen))


# ---------------------------------------------------------------------------
# Scrape-time health collector (drives the alerts in alerts.yml)
# ---------------------------------------------------------------------------


class HealthCollector:
    """Runs the health checks whenever Prometheus scrapes /metrics."""

    def __init__(self, db_path: str, redis_url: str):
        self._db_path = db_path
        self._redis_url = redis_url

    def collect(self) -> Iterable[Metric]:
        ok = GaugeMetricFamily(
            "health_check_ok",
            "1 if the check passed, 0 otherwise.",
            labels=["check"],
        )
        for name, result in (
            ("database", _health.check_database(self._db_path)),
            ("redis", _health.check_redis(self._redis_url)),
            ("disk_space", _health.check_disk_space()),
            ("memory", _health.check_memory()),
            ("backup", _health.check_backup()),
        ):
            ok.add_metric([name], 1.0 if result == "ok" else 0.0)
        yield ok

        age = GaugeMetricFamily(
            "last_draw_age_hours", "Hours since the most recent draw."
        )
        age_value = _health.last_draw_age_hours(self._db_path)
        age.add_metric([], age_value if age_value is not None else -1.0)
        yield age

        disk = GaugeMetricFamily("disk_free_ratio", "Free disk ratio (0-1).")
        try:
            usage = shutil.disk_usage(os.path.dirname(self._db_path) or ".")
            disk.add_metric([], usage.free / usage.total if usage.total else 0.0)
        except Exception:
            disk.add_metric([], 0.0)
        yield disk

        mem = GaugeMetricFamily("memory_used_ratio", "Used memory ratio (0-1).")
        try:
            if _health.psutil is not None:
                mem.add_metric([], _health.psutil.virtual_memory().percent / 100.0)
            else:
                mem.add_metric([], -1.0)
        except Exception:
            mem.add_metric([], -1.0)
        yield mem


_collector_registered = False


def register_health_collector(db_path: str, redis_url: str) -> None:
    """Register the scrape-time health collector (idempotent)."""
    global _collector_registered
    if not _collector_registered:
        prometheus_client.REGISTRY.register(HealthCollector(db_path, redis_url))
        _collector_registered = True


def render_metrics() -> bytes:
    """Return the Prometheus text exposition for /metrics."""
    return prometheus_client.generate_latest()


CONTENT_TYPE_LATEST = prometheus_client.CONTENT_TYPE_LATEST


def route_template(request: Request) -> str:
    """Best-effort route template for metric labels (avoids cardinality
    explosion from raw paths like /wheel/single1)."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return cast(str, path) if path else "unmatched"


class Timer:
    """Tiny context manager for observing DB query durations."""

    def __init__(self, operation: str):
        self._operation = operation
        self._start = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> Literal[False]:
        DB_QUERY_DURATION.labels(operation=self._operation).observe(
            time.perf_counter() - self._start
        )
        return False
