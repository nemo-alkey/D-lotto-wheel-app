#!/usr/bin/env python3
"""Repair draws stored with powerball = 0 or NULL in the Powerball era.

Root cause of the damage: the old scrapers silently clamped out-of-range or
unparseable Powerball values to 0. This script re-fetches the official result
for every zero/NULL row and writes the validated value. It never invents a
number: draws that cannot be re-fetched are marked MISSING in the repair log
and left untouched.

Idempotent: rows already repaired (powerball != 0) are never selected, so a
re-run performs no writes.

Usage:
    python scripts/repair_powerball_zero.py                 # repair data/lotto.db
    python scripts/repair_powerball_zero.py --db PATH       # another database
    python scripts/repair_powerball_zero.py --dry-run       # log only, no writes
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import requests

# Allow running both as `python scripts/repair_powerball_zero.py` and as an import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from powerball_rules import validate_powerball

DB_PATH = Path("data/lotto.db")
LOG_PATH = Path("data/logs/repair_powerball_zero.log")
API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
PBNZ_BASE = "https://www.powerball.net/newzealand/results"

#: Powerball launched in NZ in August 2001; earlier draws legitimately have none.
POWERBALL_INTRO_DATE = "2001-08-01"

RATE_LIMIT = 0.3  # seconds between network fetches

#: fetcher signature: (draw_number, draw_date, db_numbers, db_bonus)
#:   -> Optional[tuple[int, str]]  i.e. (powerball, source) or None if unfetchable.
Fetcher = Callable[[int, str, list[int], int], tuple[int, str] | None]

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _log(log_path: Path | None, msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# Default fetcher: official API first, powerball.net as corroborated fallback
# ---------------------------------------------------------------------------


def _official_powerball(draw_number: int) -> int | None:
    """Return the Powerball from the official API, or None if unavailable."""
    try:
        r = requests.get(f"{API_BASE}/{draw_number}", headers=_HEADERS, timeout=15)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    pb_raw = (r.json().get("powerBall") or {}).get("powerballWinningNumber", "")
    return int(pb_raw) if str(pb_raw).strip().isdigit() else None


def _pbnz_draw(draw_date: str) -> dict | None:
    """Fetch a draw from powerball.net; caller must cross-check numbers/bonus."""
    try:
        r = requests.get(f"{PBNZ_BASE}/{draw_date}", headers=_HEADERS, timeout=20)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    import re

    lotto_ul = re.search(r'<ul class="balls"[^>]*>(.*?)</ul>', r.text, re.DOTALL)
    if not lotto_ul:
        return None
    balls = [int(n) for n in re.findall(r'<li class="new ball">(\d+)</li>', lotto_ul.group(1))]
    bonus_m = re.search(r'<li class="new bonus-ball">(\d+)</li>', lotto_ul.group(1))
    pb_m = re.search(r'<li class="new powerball">(\d+)</li>', r.text)
    if len(balls) != 6 or not bonus_m or not pb_m:
        return None
    return {"numbers": balls, "bonus": int(bonus_m.group(1)), "powerball": int(pb_m.group(1))}


def default_fetcher(
    draw_number: int, draw_date: str, db_numbers: list[int], db_bonus: int
) -> tuple[int, str] | None:
    """Official API first; powerball.net only when its numbers/bonus match ours."""
    pb = _official_powerball(draw_number)
    if pb is not None:
        return pb, "mylotto-api"
    alt = _pbnz_draw(draw_date)
    if alt and sorted(db_numbers) == alt["numbers"] and db_bonus == alt["bonus"]:
        return alt["powerball"], "powerball.net"
    return None


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


def repair(
    db_path: Path = DB_PATH,
    log_path: Path | None = LOG_PATH,
    fetcher: Fetcher = default_fetcher,
    rate_limit: float = RATE_LIMIT,
    dry_run: bool = False,
) -> dict[str, int]:
    """Repair powerball=0/NULL rows. Returns counts; logs every decision."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    rows = conn.execute(
        "SELECT draw_number, draw_date, numbers, bonus FROM draws "
        "WHERE powerball = 0 OR powerball IS NULL ORDER BY draw_date"
    ).fetchall()

    counts = {"total": len(rows), "pre_powerball": 0, "repaired": 0, "missing": 0}
    _log(
        log_path,
        f"repair started: {len(rows)} row(s) with powerball=0/NULL " f"(dry_run={dry_run})",
    )

    for draw_number, draw_date, numbers, bonus in rows:
        label = f"#{draw_number} ({draw_date})"

        if draw_date < POWERBALL_INTRO_DATE:
            counts["pre_powerball"] += 1
            _log(
                log_path,
                f"PRE-POWERBALL {label}: predates Powerball launch, " "legitimate zero — untouched",
            )
            continue

        db_numbers = [int(x) for x in str(numbers).split(",") if str(x).strip()]
        result = fetcher(draw_number, draw_date, db_numbers, bonus)
        if result is None:
            counts["missing"] += 1
            _log(
                log_path,
                f"MISSING {label}: could not re-fetch from any source — "
                "left as-is (not invented)",
            )
        else:
            powerball, source = result
            # Era-aware; raises ValueError loudly on invalid values — never clamp.
            validate_powerball(powerball, draw_date)
            if not dry_run:
                conn.execute(
                    "UPDATE draws SET powerball = ? WHERE draw_number = ?",
                    (powerball, draw_number),
                )
                conn.commit()
            counts["repaired"] += 1
            _log(
                log_path,
                f"REPAIRED {label}: powerball 0 -> {powerball} "
                f"(source: {source}){' [dry-run]' if dry_run else ''}",
            )
        time.sleep(rate_limit)

    conn.close()
    _log(
        log_path,
        f"repair finished: {counts['repaired']} repaired, {counts['missing']} missing, "
        f"{counts['pre_powerball']} pre-Powerball zeros (legitimate)",
    )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repair(db_path=args.db, log_path=args.log, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
