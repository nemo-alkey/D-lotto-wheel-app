"""Shared data loaders for analysis scripts.

Every analysis script imports from here so era handling, DB path
resolution, and output formatting stay consistent.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

# Repo root: scripts/analysis/_common.py -> scripts/analysis -> scripts -> repo
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "lotto.db"

# Make repo-root modules (prize_calculator, powerball_rules, etc.) importable
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_draws(era: str | None = None) -> list[dict[str, Any]]:
    """Load draws from data/lotto.db.

    Args:
        era: 'pre_2026_09_16', 'post_2026_09_16', or None for all.

    Returns:
        List of dicts with keys: draw_id, draw_date, draw_number,
        numbers (list[int]), bonus, powerball, rule_era.
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT draw_id, draw_date, draw_number, numbers, bonus, "
            "powerball, rule_era FROM draws"
        )
        params: list[Any] = []
        if era is not None:
            sql += " WHERE rule_era = ?"
            params.append(era)
        sql += " ORDER BY draw_date ASC"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        nums = [int(n) for n in r["numbers"].split(",")] if r["numbers"] else []
        out.append(
            {
                "draw_id": r["draw_id"],
                "draw_date": r["draw_date"],
                "draw_number": r["draw_number"],
                "numbers": nums,
                "bonus": r["bonus"],
                "powerball": r["powerball"],
                "rule_era": r["rule_era"],
            }
        )
    return out


def main_number_draws() -> list[dict[str, Any]]:
    """All draws with exactly 6 main numbers (excludes pre-launch rows)."""
    return [d for d in load_draws() if len(d["numbers"]) == 6]


def post_change_draws() -> list[dict[str, Any]]:
    return load_draws(era="post_2026_09_16")


def section(title: str) -> None:
    """Print a report section header."""
    print()
    print("=" * 68)
    print(f"  {title}")
    print("=" * 68)


def subsection(title: str) -> None:
    print()
    print(f"--- {title} ---")
