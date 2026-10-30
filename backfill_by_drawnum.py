#!/usr/bin/env python3
"""Backfill NZ Lotto draws by draw number via API."""

import argparse
import contextlib
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests

DB_PATH = Path("data/lotto.db")
API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
RATE_LIMIT = 0.3

#: Draws from this date onward are in the Powerball era (game began Aug 2001).
POWERBALL_INTRO_DATE = "2001-08-01"


def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)

    # Create table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_number INTEGER,
            draw_date TEXT UNIQUE,
            numbers TEXT,
            bonus INTEGER,
            powerball INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Check if draw_number column exists — add it if missing
    cursor = conn.execute("PRAGMA table_info(draws)")
    columns = {row[1] for row in cursor.fetchall()}

    if "draw_number" not in columns:
        print("Adding draw_number column to existing draws table...")
        conn.execute("ALTER TABLE draws ADD COLUMN draw_number INTEGER")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(draw_date)")

    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_draws_number ON draws(draw_number)")

    conn.commit()
    conn.close()


def get_existing_draw_numbers() -> set[int]:
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    try:
        rows = conn.execute("SELECT draw_number FROM draws WHERE draw_number > 0").fetchall()
        conn.close()
        return {r[0] for r in rows}
    except sqlite3.OperationalError:
        conn.close()
        return set()


def insert_draw(
    draw_number: int,
    draw_date: str,
    numbers: list[int],
    bonus: int,
    powerball: int | None,
) -> bool:
    ensure_db()
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    try:
        conn.execute(
            "INSERT INTO draws (draw_number, draw_date, numbers, bonus, powerball) VALUES (?, ?, ?, ?, ?)",
            (draw_number, draw_date, ",".join(map(str, numbers)), bonus, powerball),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        # draw_date already exists — update with draw_number
        try:
            conn.execute(
                "UPDATE draws SET draw_number = ? WHERE draw_date = ?",
                (draw_number, draw_date),
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            conn.close()
            return False
    except Exception:
        conn.close()
        return False


def fetch_draw(draw_number: int) -> dict | None:
    url = f"{API_BASE}/{draw_number}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as e:
        print(f"  ! Draw #{draw_number}: request error: {e}")
        return None
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        print(f"  ! Draw #{draw_number}: HTTP {r.status_code}")
        return None

    data = r.json()
    lotto = data.get("lotto", {})
    draw_num = lotto.get("drawNumber")
    draw_date = lotto.get("drawDate")
    winning = lotto.get("lottoWinningNumbers", {})
    numbers_raw = winning.get("numbers", [])
    bonus_raw = winning.get("bonusBalls", "0")

    numbers = [int(n) for n in numbers_raw if str(n).isdigit()]
    if len(numbers) != 6:
        raise ValueError(f"Draw #{draw_number}: expected 6 numbers, got {numbers_raw!r}")

    bonus = int(bonus_raw) if str(bonus_raw).isdigit() else 0

    powerball = 0
    pb_section = data.get("powerBall", {})
    if pb_section:
        # The live payload key is "powerballWinningNumber" (a string).
        pb_raw = pb_section.get("powerballWinningNumber", "")
        if str(pb_raw).strip().isdigit():
            powerball = int(pb_raw)
    # Era-aware validation: raises loudly on invalid values — never clamp.
    if powerball:
        from powerball_rules import validate_powerball

        validate_powerball(powerball, draw_date)
    elif draw_date >= POWERBALL_INTRO_DATE:
        raise ValueError(f"Draw #{draw_number} ({draw_date}): Powerball missing from API payload")

    return {
        "draw_number": draw_num,
        "draw_date": draw_date,
        "numbers": sorted(numbers),
        "bonus": bonus,
        "powerball": powerball,
    }


PBNZ_BASE = "https://www.powerball.net/newzealand/results"


def fetch_draw_from_powerball_net(draw_date: str) -> dict | None:
    """Fetch a draw from powerball.net (secondary corroborating source).

    Used only for draws outside the official API's retention window. The
    caller MUST cross-check the returned main numbers/bonus against an
    authoritative local record before trusting the Powerball value.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    r = requests.get(f"{PBNZ_BASE}/{draw_date}", headers=headers, timeout=20)
    if r.status_code != 200:
        print(f"  ! powerball.net {draw_date}: HTTP {r.status_code}")
        return None

    # Lotto line: first <ul class="balls"> — 6 balls + 1 bonus-ball.
    lotto_ul = re.search(r'<ul class="balls"[^>]*>(.*?)</ul>', r.text, re.DOTALL)
    if not lotto_ul:
        print(f"  ! powerball.net {draw_date}: no lotto ball list found")
        return None
    balls = [int(n) for n in re.findall(r'<li class="new ball">(\d+)</li>', lotto_ul.group(1))]
    bonus_m = re.search(r'<li class="new bonus-ball">(\d+)</li>', lotto_ul.group(1))
    if len(balls) != 6 or not bonus_m:
        print(f"  ! powerball.net {draw_date}: expected 6 balls + bonus, got {balls!r}")
        return None

    # Powerball: the <li class="new powerball"> entry in the Powerball line.
    pb_m = re.search(r'<li class="new powerball">(\d+)</li>', r.text)
    if not pb_m:
        print(f"  ! powerball.net {draw_date}: no powerball value found")
        return None

    return {
        "numbers": balls,
        "bonus": int(bonus_m.group(1)),
        "powerball": int(pb_m.group(1)),
    }


def latest_draw_number() -> int:
    """Fetch the latest published draw number from the API (no path)."""
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    r = requests.get(API_BASE, headers=headers, timeout=15)
    r.raise_for_status()
    return int(r.json()["lotto"]["drawNumber"])


def backfill(start: int = 1, end: int | None = None) -> None:
    ensure_db()
    if end is None:
        end = latest_draw_number()
        print(f"Latest draw number from API: {end}")
    existing = get_existing_draw_numbers()
    print(f"Existing draws in DB: {len(existing)}")
    print(f"Fetching draws {start} to {end}...")
    print("=" * 60)

    inserted = skipped = failed = 0
    t0 = time.time()

    for draw_number in range(start, end + 1):
        if draw_number in existing:
            skipped += 1
            continue

        draw = fetch_draw(draw_number)
        if draw is None:
            failed += 1
            if failed <= 3 or draw_number % 100 == 0:
                print(f"  - #{draw_number}: not found (404)")
        else:
            if insert_draw(**draw):
                inserted += 1
                if inserted % 50 == 0:
                    elapsed = time.time() - t0
                    rate = inserted / elapsed if elapsed > 0 else 0
                    print(f"  ... {inserted} inserted ({rate:.1f}/sec)")
            else:
                skipped += 1

        time.sleep(RATE_LIMIT)

    elapsed = time.time() - t0
    print("=" * 60)
    print(f"Done in {elapsed:.1f}s")
    print(f"Inserted: {inserted} | Skipped: {skipped} | Failed/404: {failed}")

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    cursor = conn.execute("SELECT MIN(draw_date), MAX(draw_date) FROM draws")
    min_date, max_date = cursor.fetchone()
    conn.close()
    print(f"Total draws in DB: {count}")
    if min_date and max_date:
        print(f"Date range: {min_date} to {max_date}")


def repair_powerballs() -> None:
    """Repair draws stored with powerball=0 in the Powerball era.

    Fetches each affected draw by its draw number, validates the Powerball
    against the rules in force on that date, and updates the row. Aborts
    loudly on any validation failure — never writes an unvalidated value.
    """
    ensure_db()
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    rows = conn.execute(
        "SELECT draw_number, draw_date FROM draws "
        "WHERE powerball = 0 AND draw_date >= ? AND draw_number > 0 "
        "ORDER BY draw_number",
        (POWERBALL_INTRO_DATE,),
    ).fetchall()
    conn.close()
    print(f"Found {len(rows)} Powerball-era draws with powerball=0 to repair")

    repaired = skipped_pre_pb = 0
    for draw_number, draw_date in rows:
        draw = fetch_draw(draw_number)
        if draw is None:
            # Outside official API retention — try the corroborating source,
            # but only trust it if its main numbers/bonus match our record.
            alt = fetch_draw_from_powerball_net(draw_date)
            if alt is None:
                print(f"  ! #{draw_number} ({draw_date}): no source available — left as-is")
                continue
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            row = conn.execute(
                "SELECT numbers, bonus FROM draws WHERE draw_number = ?", (draw_number,)
            ).fetchone()
            conn.close()
            db_numbers = [int(n) for n in row[0].split(",")]
            if sorted(db_numbers) != alt["numbers"] or row[1] != alt["bonus"]:
                raise ValueError(
                    f"Draw #{draw_number} ({draw_date}): powerball.net data does not match "
                    f"local record (remote {alt['numbers']} b{alt['bonus']} vs local "
                    f"{db_numbers} b{row[1]}) — refusing to write"
                )
            draw = {
                "draw_number": draw_number,
                "draw_date": draw_date,
                "numbers": db_numbers,
                "bonus": row[1],
                "powerball": alt["powerball"],
            }
        if draw["draw_date"] != draw_date:
            raise ValueError(
                f"Draw #{draw_number}: source date {draw['draw_date']} does not match "
                f"local date {draw_date} — refusing to write"
            )
        if draw["powerball"] == 0:
            if draw_date < POWERBALL_INTRO_DATE:
                skipped_pre_pb += 1
                continue
            raise ValueError(
                f"Draw #{draw_number} ({draw_date}): source also reports powerball=0 — "
                "refusing to write an unvalidated value"
            )
        # Era-aware validation: raises loudly on invalid values — never clamp.
        from powerball_rules import validate_powerball

        validate_powerball(draw["powerball"], draw_date)
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute(
            "UPDATE draws SET powerball = ? WHERE draw_number = ?",
            (draw["powerball"], draw_number),
        )
        conn.commit()
        conn.close()
        repaired += 1
        print(f"  #{draw_number} ({draw_date}): powerball 0 -> {draw['powerball']}")
        time.sleep(RATE_LIMIT)

    print(f"Repaired {repaired} of {len(rows)} draws ({skipped_pre_pb} pre-Powerball, skipped)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument(
        "--end",
        type=int,
        default=None,
        help="Last draw number (default: latest published draw from the API)",
    )
    parser.add_argument("--test", type=int, help="Test one draw and show parsed data")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Repair Powerball-era draws stored with powerball=0",
    )
    args = parser.parse_args()

    if args.repair:
        repair_powerballs()
        return 0

    if args.test:
        print(f"Testing draw #{args.test}...")
        draw = fetch_draw(args.test)
        if draw:
            import json

            print(json.dumps(draw, indent=2))
        else:
            print("Not found (404)")
        return 0

    backfill(args.start, args.end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
