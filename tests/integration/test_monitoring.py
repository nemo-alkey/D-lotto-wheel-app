"""Integration tests for the monitoring/ observability layer.

Covers:
  - GET /health payload shape and status semantics
  - GET /metrics exposition and auto-incrementing request counters
  - business counters (predictions, wheels)
  - structured JSON access log with request_id/duration_ms
  - health check units (disk, memory, draw age)
  - alert rule evaluation
"""

from __future__ import annotations

import json
import os

import pytest

import api
from monitoring import health as health_checks
from monitoring import metrics
from monitoring.alerting import evaluate_rules

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear slowapi's in-memory storage so per-IP limits don't accumulate."""
    try:
        storage = api.limiter.limiter.storage
        reset = getattr(storage, "reset", None)
        if callable(reset):
            reset()
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_payload_shape(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] in ("healthy", "degraded", "unhealthy")
    assert "timestamp" in body
    assert body["version"] == "2.0.0"
    assert isinstance(body["draws"], int)

    checks = body["checks"]
    for name in ("database", "redis", "disk_space", "memory"):
        assert name in checks
    assert "last_draw_age_hours" in checks
    # DB check must be ok in the test environment (lotto.db exists).
    assert checks["database"] == "ok"


def test_health_503_on_database_failure(monkeypatch):
    monkeypatch.setattr(health_checks, "check_database", lambda path: "fail: connection timeout")
    result = health_checks.run_all_checks("lotto.db", "redis://localhost:6379", "2.0.0")
    assert result["status"] == "unhealthy"
    assert result["http_status"] == 503


def test_health_warn_levels(monkeypatch):
    monkeypatch.setattr(health_checks, "check_redis", lambda url: "fail: connection refused")
    result = health_checks.run_all_checks("lotto.db", "redis://localhost:6379", "2.0.0")
    # Redis failure degrades but does not 503 (in-memory fallback exists).
    assert result["status"] == "degraded"
    assert result["http_status"] == 200


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------


def test_metrics_endpoint_exposes_required_series(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    for name in (
        "http_requests_total",
        "http_request_duration_seconds",
        "predictions_generated_total",
        "wheels_generated_total",
        "active_users",
        "db_query_duration_seconds",
        "health_check_ok",
        "last_draw_age_hours",
    ):
        assert name in text, name


def test_request_counter_auto_increments(client):
    before = client.get("/metrics").text
    client.get("/")
    after = client.get("/metrics").text

    def count(text):
        total = 0.0
        for line in text.splitlines():
            if line.startswith("http_requests_total"):
                total += float(line.rsplit(" ", 1)[1])
        return total

    assert count(after) > count(before)


def test_predictions_counter_increments(client):
    resp = client.post("/predictions", json={"method": "frequency", "top_k": 6})
    assert resp.status_code == 200
    text = client.get("/metrics").text
    assert 'predictions_generated_total{method="frequency"}' in text


def test_wheels_counter_increments(client):
    resp = client.post("/wheels/generate", json={"pool_size": 8, "guarantee_type": "4 if 4"})
    assert resp.status_code == 200
    text = client.get("/metrics").text
    assert 'wheels_generated_total{system_type="4 if 4"}' in text


def test_metrics_content_type(client):
    resp = client.get("/metrics")
    assert resp.headers["content-type"].startswith("text/plain")


# ---------------------------------------------------------------------------
# Structured JSON access log
# ---------------------------------------------------------------------------


def test_json_access_log_written(client):
    log_file = os.path.join("data", "logs", "app.log")
    size_before = os.path.getsize(log_file) if os.path.exists(log_file) else 0

    resp = client.get("/")
    assert "X-Request-ID" in resp.headers

    assert os.path.exists(log_file)
    with open(log_file, encoding="utf-8") as fh:
        fh.seek(size_before)
        new_lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    assert new_lines, "no new log lines written"

    record = json.loads(new_lines[-1])
    for field in (
        "timestamp",
        "level",
        "module",
        "message",
        "request_id",
        "user_id",
        "duration_ms",
    ):
        assert field in record, field
    assert record["request_id"] == resp.headers["X-Request-ID"]


# ---------------------------------------------------------------------------
# Health check units
# ---------------------------------------------------------------------------


def test_disk_and_memory_checks_return_status_strings():
    assert health_checks.check_disk_space().startswith(("ok", "warn", "fail"))
    assert health_checks.check_memory().startswith(("ok", "warn", "fail"))


def test_last_draw_age_numeric_or_none():
    age = health_checks.last_draw_age_hours("lotto.db")
    assert age is None or age >= 0


def test_db_query_timer_observes():
    with metrics.Timer("test_operation"):
        pass
    text = metrics.render_metrics().decode()
    assert 'db_query_duration_seconds_count{operation="test_operation"}' in text


# ---------------------------------------------------------------------------
# Alert rule evaluation
# ---------------------------------------------------------------------------


def test_evaluate_rules_returns_all_five_rules():
    rules = evaluate_rules()
    names = {r["alert"] for r in rules}
    assert names == {"HighErrorRate", "SlowPredictions", "DatabaseDown", "DrawStale", "DiskFull"}
    for rule in rules:
        assert isinstance(rule["firing"], bool)
        assert "severity" in rule and "detail" in rule


def test_database_down_rule_not_firing_in_test_env():
    rules = {r["alert"]: r for r in evaluate_rules()}
    assert rules["DatabaseDown"]["firing"] is False
