#!/usr/bin/env python3
"""
data_pipeline.py — Unified data-fetching pipeline with priority fallback and monitoring.

Tries API → HTML scraper → Selenium in priority order. Logs all attempts to
data_pipeline.log and records stats in the pipeline_stats table.

Usage:
    from data_pipeline import DataFetcher
    fetcher = DataFetcher()
    result = fetcher.fetch(draw_date="2026-01-15")
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text

from database_engine import get_engine

LOG_FILE = "data_pipeline.log"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class DataFetcher:
    """Unified data fetcher with priority-based fallback."""

    METHODS = ["api", "html", "selenium"]

    def __init__(self) -> None:
        self._init_stats_table()

    def _init_stats_table(self) -> None:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS pipeline_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_time TEXT DEFAULT (datetime('now')),
                    source_used TEXT,
                    draw_date TEXT,
                    success INTEGER DEFAULT 0,
                    error_message TEXT
                )
            """)
            )
            conn.commit()

    def _record_stat(self, source: str, draw_date: str, success: bool, error: str = "") -> None:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO pipeline_stats (run_time, source_used, draw_date, success, error_message) "
                    "VALUES (datetime('now'), :source, :draw_date, :success, :error)"
                ),
                {
                    "source": source,
                    "draw_date": draw_date,
                    "success": 1 if success else 0,
                    "error": error,
                },
            )
        conn.commit()

    def _try_fetch(self, method: str, date: str | None = None) -> dict[str, Any] | None:
        """Try a single fetch method. Returns draw dict or None."""
        if method == "api":
            from update_draws import fetch_draw

            return fetch_draw(date)

        elif method == "html":
            from html_scraper import scrape_my_lotto_results

            return scrape_my_lotto_results(date)

        elif method == "selenium":
            from selenium_scraper import selenium_scrape_results

            draws = selenium_scrape_results()
            if draws:
                for d in draws:
                    if date is None or d["draw_date"] == date:
                        return {
                            "draw_date": d["draw_date"],
                            "numbers": d["numbers"],
                            "bonus": d["bonus"],
                            "powerball": d["powerball"],
                        }
            return None

        return None

    def fetch(self, draw_date: str | None = None) -> dict[str, Any] | None:
        """Fetch a draw using the priority chain.

        Parameters
        ----------
        draw_date : str or None
            Specific date (YYYY-MM-DD), or None for latest.

        Returns
        -------
        dict or None
            draw_date, numbers, bonus, powerball. None if all methods fail.
        """
        label = draw_date or "latest"
        _log(f"Fetching {label} draw...")

        for method in self.METHODS:
            _log(f"  Trying {method}...")
            try:
                result = self._try_fetch(method, draw_date)
                if result and result.get("numbers"):
                    _log(f"  {method} succeeded: {result['draw_date']}")
                    self._record_stat(method, result["draw_date"], True)
                    return result
                else:
                    _log(f"  {method} returned no data.")
            except Exception as e:
                _log(f"  {method} failed: {e}")
                self._record_stat(method, label, False, str(e))

        _log(f"  All methods exhausted for {label}.")
        return None

    def fetch_latest(self) -> dict[str, Any] | None:
        """Fetch the latest draw and insert into DB if new."""
        result = self.fetch()
        if not result:
            _log("No draw data retrieved.")
            return None

        from database import draw_exists as _de
        from database import insert_draw

        new_id = insert_draw(
            result["draw_date"],
            result["numbers"],
            result.get("bonus", 0),
            result["powerball"],
        )
        if new_id is None and _de(result["draw_date"]):
            _log(f"  Draw {result['draw_date']} already exists.")
        elif new_id:
            _log(f"  Inserted draw {result['draw_date']}.")
            # Trigger notification
            self._notify_new_draw(result)
        else:
            _log(f"  Failed to insert draw {result['draw_date']}.")
        return None

    def _notify_new_draw(self, draw: dict[str, Any]) -> None:
        """Send notification when new draw data is available."""
        try:
            from notifier import notify_new_draw

            notify_new_draw(
                draw["draw_date"],
                draw["numbers"],
                draw.get("bonus", 0),
                draw.get("powerball", 0),
                source="Pipeline",
            )
        except ImportError:
            pass

    def get_stats(self) -> list[dict[str, Any]]:
        """Return recent pipeline stats."""
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT run_time, source_used, draw_date, success, error_message "
                    "FROM pipeline_stats ORDER BY run_time DESC LIMIT 50"
                )
            ).fetchall()
        return [
            {
                "run_time": r[0],
                "source": r[1],
                "draw_date": r[2],
                "success": bool(r[3]),
                "error": r[4] or "",
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Scheduled job entry point
# ---------------------------------------------------------------------------


def fetch_latest_job() -> None:
    """Entry point for scheduler — fetch latest draw and insert."""
    _log("Scheduled fetch triggered.")
    fetcher = DataFetcher()
    fetcher.fetch_latest()
    _log("Scheduled fetch complete.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def validate_db() -> dict[str, Any]:
    """Validate the database for data quality issues.

    Checks: duplicate draw dates, missing draws (gaps > 4 days),
    invalid number ranges, bonus/powerball ranges.

    Returns dict with keys: duplicates, gaps, bad_numbers, bad_bonus, bad_pb.
    """
    from datetime import datetime

    from database_engine import get_engine

    engine = get_engine()
    conn = engine.connect()
    issues: dict[str, list[str]] = {
        "duplicates": [],
        "gaps": [],
        "bad_numbers": [],
        "bad_bonus": [],
        "bad_pb": [],
    }

    # Duplicates
    dupes = conn.execute(
        "SELECT draw_date, COUNT(*) FROM draws GROUP BY draw_date HAVING COUNT(*) > 1"  # type: ignore[call-overload]  # raw SQL string
    ).fetchall()
    issues["duplicates"] = [d[0] for d in dupes]

    # Date gaps (> 4 days, expecting Wed/Sat ~3-4 day gaps)
    rows = conn.execute(  # type: ignore[call-overload]  # raw SQL string
        "SELECT draw_date FROM draws ORDER BY draw_date"
    ).fetchall()
    for i in range(len(rows) - 1):
        try:
            d1 = datetime.strptime(rows[i][0], "%Y-%m-%d")
            d2 = datetime.strptime(rows[i + 1][0], "%Y-%m-%d")
            gap = (d2 - d1).days
            if gap > 4:
                issues["gaps"].append(f"{rows[i][0]} → {rows[i+1][0]} ({gap} days)")
        except ValueError:
            pass

    # Invalid numbers
    for row in conn.execute(  # type: ignore[call-overload]  # raw SQL string
        "SELECT draw_date, numbers, bonus, powerball FROM draws"
    ):
        date, nums_str, bonus, pb = row
        try:
            nums = [int(x) for x in nums_str.split(",")]
        except (ValueError, AttributeError):
            issues["bad_numbers"].append(f"{date}: parse error '{nums_str}'")
            continue
        if len(nums) != 6:
            issues["bad_numbers"].append(f"{date}: {len(nums)} numbers (expected 6)")
            continue
        for n in nums:
            if not (1 <= n <= 40):
                issues["bad_numbers"].append(f"{date}: number {n} out of range")
                break
        if bonus and not (1 <= bonus <= 40):
            issues["bad_bonus"].append(f"{date}: bonus {bonus}")
        if not (1 <= pb <= 10):
            issues["bad_pb"].append(f"{date}: powerball {pb}")

    conn.close()
    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Unified data pipeline")
    parser.add_argument("--date", help="Specific draw date (YYYY-MM-DD)")
    parser.add_argument("--validate", action="store_true", help="Validate database integrity")
    args = parser.parse_args()

    if args.validate:
        issues = validate_db()
        total = sum(len(v) for v in issues.values())
        print(f"DB Validation: {total} issues found\n")
        for category, items in issues.items():
            if items:
                print(f"  {category}: {len(items)}")
                for item in items[:10]:
                    print(f"    - {item}")
                if len(items) > 10:
                    print(f"    ... and {len(items) - 10} more")
        if total == 0:
            print("  No issues found — database is clean.")
    else:
        fetcher = DataFetcher()
        result = fetcher.fetch(args.date)
        if result:
            print(f"Success: {result['draw_date']} — {result['numbers']}")
        else:
            print("Failed to fetch draw.")
