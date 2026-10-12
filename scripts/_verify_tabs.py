#!/usr/bin/env python3
"""Verify dashboard.py tab refactor with Streamlit AppTest."""

import os
import sys

from streamlit.testing.v1 import AppTest

EXPECTED = {
    "nav_predictions": [
        "Predictions",
        "ML Predictor",
        "📊 Predictor Leaderboard",
        "EV Simulation",
        "💰 Arbitrage",
        "International Lotteries",
    ],
    "nav_wheels": [
        "Wheels & Tickets",
        "Custom Wheel Builder",
        "📚 Bluskov Library",
        "Wheel Explorer",
        "⚛️ Quantum Wheel",
        "Ticket Wizard",
        "🎫 Standard Lotto",
        "Rotation Scheduler",
        "👥 Syndicates",
        "Export",
    ],
    "nav_backtest": [
        "Backtest Results",
        "Multi-Draw Backtest",
        "Statistical Report",
        "Check Draw",
        "Check Latest Draw",
        "Strike Check",
    ],
    "nav_attraction": [
        "🧲 Attraction Profile",
        "Bonus–Main Co‑occurrence",
        "Block Analysis",
        "🧱 Albert Blocks",
        "➕➖ Pos/Neg",
        "Frequency Chart",
    ],
    "nav_bonus": ["🎱 Bonus Impact", "Bonus Ball Analysis"],
    "nav_health": [
        "🔔 System Health",
        "Live Monitor",
        "Pipeline Status",
        "Performance Monitor",
        "Notification Settings",
    ],
}

ADMIN = os.environ.get("_TEST_ADMIN") == "1"
if ADMIN:
    os.environ["DASHBOARD_ADMIN"] = "1"
else:
    os.environ.pop("DASHBOARD_ADMIN", None)

at = AppTest.from_file("dashboard.py", default_timeout=180)
at.run()
assert not at.exception, at.exception

# --- tab count ---
# NOTE: task text said "7 without / 8 with" but the authoritative tab list has
# 6 permanent tabs + 1 env-gated Admin tab => 6 without, 7 with.
n_tabs = len(at.tabs)
expected_tabs = 7 if ADMIN else 6
assert n_tabs == expected_tabs, f"expected {expected_tabs} tabs, got {n_tabs}"
labels = [t.label for t in at.tabs]
print("tabs:", labels)
assert labels[:6] == [
    "🎯 Predictions",
    "🎡 Wheels",
    "📊 Backtest",
    "🧲 Attraction",
    "🎱 Bonus Impact",
    "🔔 System Health",
], labels
if ADMIN:
    assert labels[6] == "⚙️ Admin", labels

# --- sidebar additions ---
caps = [c.value for c in at.caption]
assert any(v.startswith("v2.0.0") or v.startswith("v") and "·" in v for v in caps), caps
btns = [b.label for b in at.button]
assert any("Clear Cache" in b for b in btns), btns
if ADMIN:
    md = [m.value for m in at.markdown]
    assert any(">Admin<" in m or "Admin</h2>" in m for m in md), "admin header missing"
print("sidebar captions sample:", caps[:5])

# --- cycle every page in every tab ---
failures = []
for key, pages in EXPECTED.items():
    for pg in pages:
        r = next(r for r in at.radio if r.key == key)
        r.set_value(pg).run()
        if at.exception:
            failures.append((key, pg, str(at.exception[0].value)[:400]))
        else:
            print(f"OK  {key}: {pg}")
assert not failures, failures

print("ALL CHECKS PASSED", "(ADMIN)" if ADMIN else "")
