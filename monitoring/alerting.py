#!/usr/bin/env python3
"""
monitoring/alerting.py — App-side alert evaluation and dispatch.

Evaluates the same conditions as monitoring/alerts.yml (the Prometheus
rules) directly against the health checks and in-process metrics, so
alerts fire even when the Prometheus/Grafana stack isn't running.

Channels:
  - email via notifier.send_email_alert (SMTP_* env vars)
  - webhook via ALERT_WEBHOOK_URL (Discord or Slack incoming webhook)

Alerts only dispatch on state transitions (ok -> firing), persisted in
data/logs/alert_state.json, so a flapping check doesn't spam channels.

Run standalone:  python -m monitoring.alerting
Or schedule:     from monitoring.alerting import evaluate_and_notify
"""

from __future__ import annotations

import json
import os
from typing import Any, cast

try:
    import requests
except ImportError:  # pragma: no cover - requests is a pinned dependency
    requests = None  # type: ignore[assignment]

from monitoring import health as _health

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATE_FILE = os.path.join(_ROOT, "data", "logs", "alert_state.json")

try:
    from settings import settings

    _DB_PATH = settings.db_path
except ImportError:
    _DB_PATH = os.path.join(_ROOT, "lotto.db")

from config_manager import get_settings

_app_cfg = get_settings()
_REDIS_URL = _app_cfg.REDIS_URL or "redis://localhost:6379"
_WEBHOOK_URL = _app_cfg.ALERT_WEBHOOK_URL or ""

# Thresholds (mirror monitoring/alerts.yml)
ERROR_RATE_THRESHOLD = 0.01  # 1% 5xx over the process counters
PREDICTION_P95_THRESHOLD_S = 5.0  # p95 prediction latency
DRAW_STALE_HOURS = 72
DISK_FULL_USED_RATIO = 0.90


# ---------------------------------------------------------------------------
# Alert rule evaluation
# ---------------------------------------------------------------------------


def _counter_value(metric_family, labels: dict[str, str]) -> float:
    """Sum counter samples matching all given labels."""
    total = 0.0
    for sample in metric_family.samples:
        if all(sample.labels.get(k) == v for k, v in labels.items()):
            total += sample.value
    return total


def evaluate_rules() -> list[dict[str, Any]]:
    """Evaluate every alert rule; return the list with current states.

    Each entry: {"alert", "severity", "summary", "firing", "detail"}.
    """
    from prometheus_client.parser import text_string_to_metric_families

    from monitoring import metrics as m

    families = {f.name: f for f in text_string_to_metric_families(m.render_metrics().decode())}

    rules: list[dict[str, Any]] = []

    # --- HighErrorRate: 5xx share of all requests > 1% ------------------
    req = families.get("http_requests_total")
    total = _counter_value(req, {}) if req else 0.0
    errors = 0.0
    if req:
        for sample in req.samples:
            if sample.labels.get("status", "").startswith("5"):
                errors += sample.value
    error_rate = (errors / total) if total else 0.0
    rules.append(
        {
            "alert": "HighErrorRate",
            "severity": "critical",
            "summary": "HTTP 5xx error rate above 1%",
            "firing": total > 20 and error_rate > ERROR_RATE_THRESHOLD,
            "detail": f"error_rate={error_rate:.4f} ({int(errors)}/{int(total)})",
        }
    )

    # --- SlowPredictions: p95 prediction latency > 5s --------------------
    lat = families.get("http_request_duration_seconds")
    p95 = 0.0
    if lat:
        buckets: list[tuple[float, float]] = []
        count = 0.0
        for sample in lat.samples:
            if sample.labels.get("endpoint") != "/predictions":
                continue
            if sample.name.endswith("_bucket"):
                buckets.append((float(sample.labels["le"]), sample.value))
            elif sample.name.endswith("_count"):
                count = sample.value
        if count > 0 and buckets:
            buckets.sort()
            target = 0.95 * count
            p95 = next((le for le, cum in buckets if cum >= target), buckets[-1][0])
    rules.append(
        {
            "alert": "SlowPredictions",
            "severity": "warning",
            "summary": "p95 prediction latency above 5s",
            "firing": p95 > PREDICTION_P95_THRESHOLD_S,
            "detail": f"p95={p95:.2f}s",
        }
    )

    # --- DatabaseDown ----------------------------------------------------
    db_status = _health.check_database(_DB_PATH)
    rules.append(
        {
            "alert": "DatabaseDown",
            "severity": "critical",
            "summary": "Database connection failing",
            "firing": db_status != "ok",
            "detail": db_status,
        }
    )

    # --- DrawStale --------------------------------------------------------
    age = _health.last_draw_age_hours(_DB_PATH)
    stale = age is None or age > DRAW_STALE_HOURS
    rules.append(
        {
            "alert": "DrawStale",
            "severity": "warning",
            "summary": f"No new draw in {DRAW_STALE_HOURS}h",
            "firing": stale,
            "detail": f"age_hours={age if age is not None else 'no draws'}",
        }
    )

    # --- DiskFull ----------------------------------------------------------
    disk_status = _health.check_disk_space()
    rules.append(
        {
            "alert": "DiskFull",
            "severity": "critical",
            "summary": "Disk usage above 90%",
            "firing": disk_status != "ok",
            "detail": disk_status,
        }
    )

    return rules


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _load_state() -> dict[str, bool]:
    try:
        with open(_STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_state(state: dict[str, bool]) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass  # alerting must never crash the caller


def send_webhook_alert(subject: str, body: str) -> bool:
    """POST an alert to a Discord/Slack incoming webhook (ALERT_WEBHOOK_URL).

    Discord accepts {"content": ...}; Slack accepts {"text": ...} — we send
    both keys; each platform ignores the one it doesn't know.
    """
    if not _WEBHOOK_URL:
        return False
    if requests is None:
        return False
    try:
        resp = requests.post(
            _WEBHOOK_URL,
            json={"content": f"**{subject}**\n{body}", "text": f"*{subject}*\n{body}"},
            timeout=10,
        )
        return resp.status_code < 300
    except Exception:
        return False


def dispatch_alert(rule: dict[str, Any]) -> None:
    """Send an alert through every configured channel."""
    subject = f"[{rule['severity'].upper()}] {rule['alert']}"
    body = f"{rule['summary']}\n\nDetail: {rule['detail']}"

    try:
        from notifier import send_email_alert

        send_email_alert(subject, body)
    except Exception:
        pass
    send_webhook_alert(subject, body)


def evaluate_and_notify() -> list[dict[str, Any]]:
    """Evaluate all rules; dispatch alerts on ok -> firing transitions.

    Returns the evaluated rules (each with a "firing" flag).
    """
    state = _load_state()
    rules = evaluate_rules()
    for rule in rules:
        name = rule["alert"]
        was_firing = state.get(name, False)
        if rule["firing"] and not was_firing:
            dispatch_alert(rule)
        state[name] = rule["firing"]
    _save_state(state)
    return rules


if __name__ == "__main__":
    for r in evaluate_and_notify():
        mark = "FIRING" if r["firing"] else "ok"
        print(f"{r['alert']:<16} {mark:<7} {r['detail']}")
