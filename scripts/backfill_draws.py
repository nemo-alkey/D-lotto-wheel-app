#!/usr/bin/env python3
"""Backfill missing NZ Lotto draws into the draws table (idempotent).

The official pathway API is keyed by draw number, not date:
``GET /api/results/v1/results/lotto/{drawnumber}``. This script anchors on the
largest draw number already stored, walks forward to the latest published
draw, and inserts only dates not already present — so re-runs are no-ops.
Every decision (insert / skip / not found / conflict) is logged.

Powerball values are validated against the rules in force on each draw date
(1-10 before 2026-09-16, 1-14 on/after); invalid data raises loudly.

Usage:
    python scripts/backfill_draws.py                 # catch up data/lotto.db
    python scripts/backfill_draws.py --db PATH
    python scripts/backfill_draws.py --dry-run       # log only, no writes
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests

# Allow running both as `python scripts/backfill_draws.py` and as an import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from powerball_rules import validate_powerball
from era_features import rule_era_for_date

DB_PATH = Path("data/lotto.db")
LOG_PATH = Path("data/logs/backfill_draws.log")
API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"

#: Powerball launched in NZ in August 2001; earlier draws legitimately have none.
POWERBALL_INTRO_DATE = "2001-08-01"

RATE_LIMIT = 0.3  # seconds between network fetches

#: fetcher signature: (draw_number) -> Optional[draw dict]
#: draw dict keys: draw_number, draw_date, numbers (sorted list[int]), bonus, powerball.
Fetcher = Callable[[int], Optional[dict]]

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _log(log_path: Optional[Path], msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# Official API fetch (draw-number keyed)
# ---------------------------------------------------------------------------


def latest_draw_number() -> int:
    """Latest published draw number (API base URL with no path)."""
    r = requests.get(API_BASE, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return int(r.json()["lotto"]["drawNumber"])


def fetch_by_number(draw_number: int) -> Optional[dict]:
    """Fetch one draw by number; era-validated. Raises ValueError on bad data."""
    try:
        r = requests.get(f"{API_BASE}/{draw_number}", headers=_HEADERS, timeout=15)
    except requests.RequestException as e:
        _log(None, f"  ! #{draw_number}: request error: {e}")
        return None
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        _log(None, f"  ! #{draw_number}: HTTP {r.status_code}")
        return None

    data = r.json()
    lotto = data.get("lotto", {})
    draw_date = lotto.get("drawDate")
    winning = lotto.get("lottoWinningNumbers", {})
    numbers = [int(n) for n in winning.get("numbers", []) if str(n).isdigit()]
    if not draw_date or len(numbers) != 6:
        raise ValueError(f"Draw #{draw_number}: malformed payload")
    for n in numbers:
        if not 1 <= n <= 40:
            raise ValueError(f"Draw #{draw_number}: number {n} out of range 1-40")

    bonus_raw = winning.get("bonusBalls", "0")
    if isinstance(bonus_raw, list):
        bonus_raw = bonus_raw[0] if bonus_raw else "0"
    bonus = int(bonus_raw) if str(bonus_raw).isdigit() else 0

    powerball = 0
    pb_raw = (data.get("powerBall") or {}).get("powerballWinningNumber", "")
    if str(pb_raw).strip().isdigit():
        powerball = int(pb_raw)
    if powerball:
        # Era-aware; raises ValueError loudly on invalid values — never clamp.
        validate_powerball(powerball, draw_date)
    elif draw_date >= POWERBALL_INTRO_DATE:
        raise ValueError(f"Draw #{draw_number} ({draw_date}): Powerball missing from payload")

    return {
        "draw_number": int(lotto.get("drawNumber", draw_number)),
        "draw_date": draw_date,
        "numbers": sorted(numbers),
        "bonus": bonus,
        "powerball": powerball,
    }


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


def backfill(
    db_path: Path = DB_PATH,
    log_path: Optional[Path] = LOG_PATH,
    fetcher: Fetcher = fetch_by_number,
    end: Optional[int] = None,
    rate_limit: float = RATE_LIMIT,
    dry_run: bool = False,
) -> dict[str, int]:
    """Insert draws after the last stored draw number up to ``end``.

    ``end=None`` discovers the latest published draw number from the API.
    Idempotent: dates already present are skipped.
    """
    conn = sqlite3.connect(str(db_path), timeout=10)
    anchor = conn.execute(
        "SELECT MAX(draw_number) FROM draws WHERE draw_number > 0"
    ).fetchone()[0]
    start = (anchor or 0) + 1
    if end is None:
        end = latest_draw_number()
    existing_dates = {r[0] for r in conn.execute("SELECT draw_date FROM draws")}
    conn.close()

    counts = {"start": start, "end": end, "inserted": 0, "skipped": 0, "not_found": 0}
    _log(log_path, f"backfill started: draws {start}..{end} "
                   f"({len(existing_dates)} dates already present, dry_run={dry_run})")

    for draw_number in range(start, end + 1):
        draw = fetcher(draw_number)
        label = f"#{draw_number}"
        if draw is None:
            counts["not_found"] += 1
            _log(log_path, f"NOT-FOUND {label}: no result published")
            time.sleep(rate_limit)
            continue
        if draw["draw_date"] in existing_dates:
            counts["skipped"] += 1
            _log(log_path, f"SKIP {label} ({draw['draw_date']}): already in DB")
            time.sleep(rate_limit)
            continue
        # Validate here, not only in the fetcher: injected/future fetchers must
        # not be able to sneak an out-of-era Powerball past us. Raises loudly.
        if draw["powerball"]:
            validate_powerball(draw["powerball"], draw["draw_date"])
        elif draw["draw_date"] >= POWERBALL_INTRO_DATE:
            raise ValueError(
                f"{label} ({draw['draw_date']}): Powerball missing from fetched draw"
            )
        if not dry_run:
            conn = sqlite3.connect(str(db_path), timeout=10)
            try:
                conn.execute(
                    "INSERT INTO draws (draw_number, draw_date, numbers, bonus, powerball, rule_era) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        draw["draw_number"],
                        draw["draw_date"],
                        ",".join(map(str, draw["numbers"])),
                        draw["bonus"],
                        draw["powerball"],
                        rule_era_for_date(draw["draw_date"]),
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # Same date raced in via another path — skip, never duplicate.
                counts["skipped"] += 1
                _log(log_path, f"SKIP {label} ({draw['draw_date']}): date conflict, "
                               "already present")
                conn.close()
                time.sleep(rate_limit)
                continue
            conn.close()
            existing_dates.add(draw["draw_date"])
        counts["inserted"] += 1
        _log(
            log_path,
            f"INSERTED {label} ({draw['draw_date']}): "
            f"{draw['numbers']} +{draw['bonus']} PB {draw['powerball']}"
            f"{' [dry-run]' if dry_run else ''}",
        )
        time.sleep(rate_limit)

    _log(
        log_path,
        f"backfill finished: {counts['inserted']} inserted, {counts['skipped']} skipped, "
        f"{counts['not_found']} not found",
    )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--end", type=int, default=None, help="Last draw number (default: latest)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(db_path=args.db, log_path=args.log, end=args.end, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
