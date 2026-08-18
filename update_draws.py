#!/usr/bin/env python3
"""
update_draws.py — Fetch NZ Lotto Powerball results and update the database.

Fetches from the official MyLotto API with retries, exponential backoff,
and polite delays. Supports fetching a single latest draw, a specific date,
or a date range.

API: https://pathway.mylotto.co.nz/api/results/v1/results/lotto

Usage:
    python update_draws.py                           # fetch latest
    python update_draws.py --date 2026-01-15         # specific draw
    python update_draws.py --range 2026-01-01:2026-06-08  # date range
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from typing import Any

import requests

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lotto.db")
API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
LOG_FILE = "update_draws.log"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Exponential backoff delays in seconds
RETRY_DELAYS = [1, 2, 4]
POLITE_DELAY = 2  # seconds between successful fetches
_force_selenium = False  # overridden by --use-selenium flag


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    """Append a timestamped message to the log file and print to stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


def _get_session() -> requests.Session:
    """Create a requests.Session with User-Agent header."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


# ---------------------------------------------------------------------------
# API fetch with retries
# ---------------------------------------------------------------------------


def fetch_draw(date: str | None = None) -> dict[str, Any] | None:
    """Fetch a draw from the MyLotto API with exponential backoff.

    Parameters
    ----------
    date : str or None
        Specific draw date (YYYY-MM-DD), or None for latest.

    Returns
    -------
    dict or None
        draw_date, numbers, bonus, powerball on success; None on failure.
    """
    url = API_BASE
    if date:
        url = f"{API_BASE}/{date}"

    session = _get_session()

    for attempt, delay in enumerate(RETRY_DELAYS, 1):
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            lotto = data.get("lotto")
            if not lotto:
                raise ValueError("API response missing 'lotto' key")

            draw_date = lotto.get("drawDate")
            if not draw_date:
                raise ValueError("API response missing drawDate")

            wn = lotto.get("lottoWinningNumbers", {})
            numbers_raw = wn.get("numbers", [])
            if len(numbers_raw) != 6:
                raise ValueError(f"Expected 6 numbers, got {len(numbers_raw)}: {numbers_raw}")

            numbers = [int(n) for n in numbers_raw]

            # Bonus ball (string or list)
            bonus_raw = wn.get("bonusBalls", "")
            if isinstance(bonus_raw, list):
                bonus = int(bonus_raw[0]) if bonus_raw else 0
            else:
                bonus = int(bonus_raw) if bonus_raw else 0

            pb = data.get("powerBall", {})
            pb_raw = pb.get("powerballWinningNumber", "")
            if not pb_raw:
                raise ValueError("API response missing powerballWinningNumber")
            powerball = int(pb_raw)

            # Validate ranges
            for n in numbers:
                if not (1 <= n <= 40):
                    raise ValueError(f"Number {n} out of range (1-40)")
            if bonus and not (1 <= bonus <= 40):
                raise ValueError(f"Bonus ball {bonus} out of range (1-40)")
            if not (1 <= powerball <= 10):
                raise ValueError(f"Powerball {powerball} out of range (1-10)")

            return {
                "draw_date": draw_date,
                "numbers": numbers,
                "bonus": bonus,
                "powerball": powerball,
            }

        except requests.ConnectionError as e:
            log(f"  Connection error (attempt {attempt}/{len(RETRY_DELAYS)}): {e}")
            if attempt < len(RETRY_DELAYS):
                time.sleep(delay)
        except requests.Timeout as e:
            log(f"  Timeout (attempt {attempt}/{len(RETRY_DELAYS)}): {e}")
            if attempt < len(RETRY_DELAYS):
                time.sleep(delay)
        except requests.HTTPError as e:
            log(f"  HTTP error {resp.status_code}: {e}")
            log("  Falling back to HTML scraper...")
            return _scraper_fallback(date)
        except (ValueError, KeyError, TypeError) as e:
            log(f"  Data error: {e}")
            log("  Falling back to HTML scraper...")
            return _scraper_fallback(date)

    log(f"  All retries exhausted for {date or 'latest'}")
    log("  Falling back to HTML scraper...")
    return _scraper_fallback(date)


def _scraper_fallback(date: str | None = None) -> dict[str, Any] | None:
    """Attempt to fetch draw via HTML scraper when API fails."""
    try:
        from html_scraper import scrape_my_lotto_results
    except ImportError:
        log("  HTML scraper not available (missing beautifulsoup4).")
        return None

    result = scrape_my_lotto_results(date)
    if result:
        log(f"  HTML fallback succeeded: {result['draw_date']}")
        return result

    log("  HTML fallback also failed.")

    # Selenium fallback
    try:
        from settings import settings

        use_selenium_fallback = settings.use_selenium_fallback
    except ImportError:
        use_selenium_fallback = False

    if use_selenium_fallback or _force_selenium:
        log("  Trying Selenium fallback...")
        try:
            from selenium_scraper import selenium_scrape_results

            selenium_draws = selenium_scrape_results()
            if selenium_draws:
                # Find the matching date
                for d in selenium_draws:
                    if date is None or d["draw_date"] == date:
                        return {
                            "draw_date": d["draw_date"],
                            "numbers": d["numbers"],
                            "bonus": d["bonus"],
                            "powerball": d["powerball"],
                        }
                # Return first if no date match
                d = selenium_draws[0]
                return {
                    "draw_date": d["draw_date"],
                    "numbers": d["numbers"],
                    "bonus": d["bonus"],
                    "powerball": d["powerball"],
                }
            log("  Selenium fallback returned no results.")
        except ImportError:
            log("  Selenium not available (install selenium).")
        except Exception as e:
            log(f"  Selenium fallback error: {e}")
    else:
        log("  Selenium fallback disabled (set USE_SELENIUM_FALLBACK=True in config.py).")

    return None


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def init_db(conn: sqlite3.Connection) -> None:
    """Ensure the draws table exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS draws (
            draw_id    INTEGER PRIMARY KEY,
            draw_date  TEXT NOT NULL UNIQUE,
            numbers    TEXT NOT NULL,
            bonus      INTEGER CHECK (bonus BETWEEN 1 AND 40),
            powerball  INTEGER CHECK (powerball BETWEEN 1 AND 10)
        )
    """)
    conn.commit()


def draw_exists(conn: sqlite3.Connection, draw_date: str) -> bool:
    """Return True if a draw with this date already exists."""
    row = conn.execute("SELECT 1 FROM draws WHERE draw_date = ?", (draw_date,)).fetchone()
    return row is not None


def insert_draw(conn: sqlite3.Connection, draw: dict[str, Any]) -> bool:
    """Insert a new draw. Returns True on success, False on duplicate."""
    nums = draw["numbers"]
    nums_str = ",".join(str(n) for n in nums)
    try:
        cur = conn.execute("SELECT COALESCE(MAX(draw_id), 0) FROM draws")
        new_id = cur.fetchone()[0] + 1
        conn.execute(
            "INSERT INTO draws (draw_id, draw_date, numbers, bonus, powerball) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_id, draw["draw_date"], nums_str, draw.get("bonus", 0), draw["powerball"]),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


# ---------------------------------------------------------------------------
# Process a single draw
# ---------------------------------------------------------------------------


def process_draw(conn: sqlite3.Connection, date: str | None = None) -> int:
    """Fetch and insert one draw. Returns 1 if inserted, 0 if skipped/error."""
    label = date or "latest"
    log(f"Fetching {label} draw...")

    draw = fetch_draw(date)
    if draw is None:
        log(f"  FAILED to fetch {label}")
        return 0

    dt = draw["draw_date"]
    nums_str = ",".join(f"{n:02d}" for n in draw["numbers"])
    bonus = draw.get("bonus", 0)
    log(f"  {dt} -> {nums_str}  Bonus {bonus:02d}  PB {draw['powerball']}")

    if draw_exists(conn, dt):
        log("  Already exists, skipping.")
        return 0

    if insert_draw(conn, draw):
        log("  Inserted.")
        try:
            from live_draw_monitor import publish_draw_event

            publish_draw_event(draw, source="update_draws")
        except Exception:
            pass  # broadcast is best-effort; the draw is safely in the DB
        try:
            from pos_neg_tracker import run_rebalance_check

            shift_alert = run_rebalance_check(DB_PATH)
            if shift_alert:
                log(f"  Pos/Neg {shift_alert}")
        except Exception as e:
            log(f"  Pos/Neg rebalance check failed (non-fatal): {e}")
        return 1
    else:
        log("  Insert failed (duplicate?).")
        return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def check_selenium() -> None:
    """Test if Selenium is operational and print configuration guidance.

    Called by the --check-selenium CLI flag.  Does not scrape any data;
    only verifies that the driver can start and quit cleanly.
    """
    print("=== Selenium Readiness Check ===")
    print()
    try:
        from selenium_scraper import SELENIUM_AVAILABLE, _get_driver
    except ImportError:
        print("selenium_scraper module not found.")
        print("Ensure selenium and webdriver-manager are installed:")
        print("  pip install selenium webdriver-manager")
        return

    if not SELENIUM_AVAILABLE:
        print("Selenium package(s) not installed.")
        print("Install with: pip install selenium webdriver-manager")
        return

    print("  Selenium import:        OK")

    # Try to create a driver (headless) and quit immediately
    print("  Creating Chrome driver...", end=" ", flush=True)
    driver = _get_driver(headless=True)
    if driver is None:
        print("FAILED")
        print()
        print("Configuration needed (see messages above).")
        print()
        print("Quick reference:")
        print("  export SELENIUM_CHROME_BINARY=/path/to/chrome")
        print("  # or install ChromeDriverManager:")
        print("  pip install webdriver-manager")
        return

    print("OK")
    print("  Quitting driver...", end=" ", flush=True)
    try:
        driver.quit()
        print("OK")
    except Exception:
        print("warning (non-fatal)")

    print()
    print("Selenium is ready for use.")
    print("Use --use-selenium to force Selenium fallback during scraping.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch NZ Lotto draws and update the database.")
    parser.add_argument(
        "--date",
        help="Fetch a specific draw date (YYYY-MM-DD). Default: latest.",
    )
    parser.add_argument(
        "--range",
        help="Fetch a range of dates: 'YYYY-MM-DD:YYYY-MM-DD' (inclusive).",
    )
    parser.add_argument(
        "--use-selenium",
        action="store_true",
        help="Force Selenium-based scraping as fallback.",
    )
    parser.add_argument(
        "--check-selenium",
        action="store_true",
        help="Test if Selenium/ChromeDriver is configured and print"
        " instructional messages.  No scraping is performed.",
    )
    args = parser.parse_args()

    global _force_selenium

    # --- Check-selenium mode (no DB connection needed) ---
    if args.check_selenium:
        if args.use_selenium:
            _force_selenium = True  # honour combined flags
        check_selenium()
        return

    _force_selenium = args.use_selenium

    # Open database (create if missing)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    before = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    inserted = 0

    if args.range:
        # Parse date range
        try:
            start_str, end_str = args.range.split(":")
            start = datetime.strptime(start_str.strip(), "%Y-%m-%d")
            end = datetime.strptime(end_str.strip(), "%Y-%m-%d")
        except ValueError:
            log("ERROR: --range must be 'YYYY-MM-DD:YYYY-MM-DD'")
            conn.close()
            sys.exit(1)

        from datetime import timedelta

        current = start
        total = (end - start).days + 1
        count = 0
        while current <= end:
            count += 1
            date_str = current.strftime("%Y-%m-%d")
            log(f"[{count}/{total}] Processing {date_str}")
            n = process_draw(conn, date_str)
            inserted += n
            current += timedelta(days=1)
            if current <= end:
                time.sleep(POLITE_DELAY)

    else:
        # Single draw (latest or --date)
        inserted = process_draw(conn, args.date)

    # Summary
    after = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    new_count = after - before
    log(f"Done. {new_count} new draw(s) inserted. Database: {after} draws.")

    # Show last 3
    rows = conn.execute(
        "SELECT draw_date, numbers, bonus, powerball " "FROM draws ORDER BY draw_date DESC LIMIT 3"
    ).fetchall()
    if rows:
        log("Most recent draws:")
        for r in reversed(rows):
            bonus_str = f"  Bonus {r[2]:02d}" if r[2] else ""
            log(f"  {r[0]}  {r[1]}  {bonus_str}  PB {r[3]}")

    conn.close()


if __name__ == "__main__":
    main()
