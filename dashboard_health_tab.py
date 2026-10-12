#!/usr/bin/env python3
"""
dashboard_health_tab.py — "🔔 System Health" page for the Streamlit dashboard.

Extracted from dashboard.py (pure code motion, behavior identical). Renders
🟢/🟡/🔴 status cards from the API's /health payload plus charts derived from
the Prometheus /metrics text exposition.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

import pandas as pd
import streamlit as st


def render_health_tab(api_url: str | None = None) -> None:
    """Render the System Health page.

    Parameters
    ----------
    api_url : str or None
        Base URL of the companion FastAPI service. Falls back to the
        LOTTO_API_URL environment variable, then http://localhost:8000.
    """
    st.markdown('<h2 class="section-header">System Health</h2>', unsafe_allow_html=True)

    from datetime import datetime

    import requests as _requests

    api_base = api_url or os.environ.get("LOTTO_API_URL", "http://localhost:8000")
    prom_url = os.environ.get("PROMETHEUS_URL", "")

    # ---- Fetch health + metrics from the API ----
    health_data, metrics_text = None, ""
    try:
        hr = _requests.get(f"{api_base}/health", timeout=5)
        health_data = hr.json()
    except Exception as exc:
        st.error(f"API unreachable at {api_base} — {exc}")
    with contextlib.suppress(Exception):
        metrics_text = _requests.get(f"{api_base}/metrics", timeout=5).text

    def _metric_samples(name: str) -> Any:
        """All samples for a metric family from the /metrics text."""
        from prometheus_client.parser import text_string_to_metric_families

        for fam in text_string_to_metric_families(metrics_text):
            if fam.name == name:
                return fam.samples
        return []

    def _quantile(samples: Any, q: float) -> Any:
        """Approximate a quantile from histogram bucket samples."""
        buckets, count = [], 0.0
        for s in samples:
            if s.name.endswith("_bucket"):
                le = s.labels.get("le")
                if le not in (None, "+Inf"):
                    buckets.append((float(le), s.value))
            elif s.name.endswith("_count"):
                count = s.value
        if not buckets or count <= 0:
            return None
        buckets.sort()
        target = q * count
        for le, cum in buckets:
            if cum >= target:
                return le
        return buckets[-1][0]

    # ---- Status cards ----
    if health_data:
        overall = health_data.get("status", "unknown")
        color = {
            "healthy": "🟢",
            "degraded": "🟡",
            "unhealthy": "🔴",
        }.get(overall, "⚪")
        st.markdown(
            f"### {color} Overall: **{overall.upper()}** "
            f"(v{health_data.get('version', '?')}, {health_data.get('timestamp', '?')})"
        )

        checks = health_data.get("checks", {})
        cols = st.columns(len(checks) or 1)
        for col, (name, value) in zip(cols, checks.items(), strict=False):
            text = str(value)
            if text == "ok" or isinstance(value, int | float):
                icon = "🟢"
            elif text.startswith("warn"):
                icon = "🟡"
            else:
                icon = "🔴"
            col.metric(
                label=f"{icon} {name.replace('_', ' ').title()}",
                value=text if len(text) <= 22 else text[:22] + "…",
            )

        if st.button("🔄 Re-check now", key="health_recheck"):
            st.rerun()

    if not metrics_text:
        st.info("No metrics available — start the API (uvicorn api:app --port 8000).")
    else:
        st.divider()

        # ---- Active users + request volume ----
        active = 0
        for s in _metric_samples("active_users"):
            active = int(s.value)
        total_req, err_req = 0.0, 0.0
        for s in _metric_samples("http_requests_total"):
            total_req += s.value
            if str(s.labels.get("status", "")).startswith("5"):
                err_req += s.value
        err_pct = (err_req / total_req * 100) if total_req else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("👤 Active Users (15 min)", active)
        c2.metric("📨 Total Requests", int(total_req))
        c3.metric("⚠️ 5xx Error Rate", f"{err_pct:.2f}%")

        # ---- Error rate over time ----
        st.markdown("#### Error Rate (last 24h)")
        series = None
        if prom_url:
            try:
                end = datetime.now()
                start = end - pd.Timedelta(hours=24)
                resp = _requests.get(
                    f"{prom_url}/api/v1/query_range",
                    params={
                        "query": 'sum(rate(http_requests_total{status=~"5.."}[5m])) '
                        "/ sum(rate(http_requests_total[5m]))",
                        "start": start.timestamp(),
                        "end": end.timestamp(),
                        "step": 900,
                    },
                    timeout=5,
                )
                results = resp.json()["data"]["result"]
                if results:
                    ts_vals = results[0]["values"]
                    series = pd.Series(
                        [float(v) * 100 for _t, v in ts_vals],
                        index=pd.to_datetime([t for t, _v in ts_vals], unit="s"),
                        name="5xx %",
                    )
            except Exception:
                series = None
        if series is not None and not series.empty:
            st.line_chart(series)
        else:
            # No Prometheus: accumulate samples while this page is open.
            samples = st.session_state.setdefault("health_err_rate", [])
            samples.append((datetime.now(), err_pct))
            df_err = pd.DataFrame(samples, columns=["time", "5xx %"]).set_index("time")
            st.line_chart(df_err)
            if not prom_url:
                st.caption(
                    "Showing samples collected this session. Set PROMETHEUS_URL "
                    "(e.g. http://localhost:9090) for the full 24h history."
                )

        # ---- Prediction latency percentiles ----
        st.markdown("#### Prediction Latency (/predictions)")
        lat_samples = [
            s
            for s in _metric_samples("http_request_duration_seconds")
            if s.labels.get("endpoint") == "/predictions"
        ]
        p50 = _quantile(lat_samples, 0.50)
        p95 = _quantile(lat_samples, 0.95)
        p99 = _quantile(lat_samples, 0.99)
        l1, l2, l3 = st.columns(3)
        l1.metric("p50", f"{p50:.2f}s" if p50 is not None else "no data")
        l2.metric("p95", f"{p95:.2f}s" if p95 is not None else "no data")
        l3.metric("p99", f"{p99:.2f}s" if p99 is not None else "no data")

        # ---- Predictions / wheels generated ----
        pred_counts, wheel_counts = {}, {}
        for s in _metric_samples("predictions_generated_total"):
            pred_counts[s.labels.get("method", "?")] = int(s.value)
        for s in _metric_samples("wheels_generated_total"):
            wheel_counts[s.labels.get("system_type", "?")] = int(s.value)
        g1, g2 = st.columns(2)
        if pred_counts:
            g1.markdown("**Predictions generated**")
            g1.bar_chart(pd.Series(pred_counts))
        if wheel_counts:
            g2.markdown("**Wheels generated**")
            g2.bar_chart(pd.Series(wheel_counts))

    # ---- Disk / memory usage bars (local host) ----
    st.divider()
    st.markdown("#### Host Resources")
    import shutil as _shutil

    try:
        import psutil as _psutil

        mem_pct = _psutil.virtual_memory().percent / 100.0
    except Exception:
        mem_pct = None
    du = _shutil.disk_usage(os.path.dirname(__file__) or ".")
    disk_used = 1.0 - (du.free / du.total if du.total else 0.0)

    d1, d2 = st.columns(2)
    d1.markdown(f"**Disk used:** {disk_used * 100:.1f}%")
    d1.progress(min(max(disk_used, 0.0), 1.0))
    if mem_pct is not None:
        d2.markdown(f"**Memory used:** {mem_pct * 100:.1f}%")
        d2.progress(min(max(mem_pct, 0.0), 1.0))
    else:
        d2.markdown("**Memory used:** psutil unavailable")
