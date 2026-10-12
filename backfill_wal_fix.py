#!/usr/bin/env python3
"""Backfill with explicit WAL checkpointing to ensure persistence."""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

import requests

DB_PATH = Path.cwd() / "data" / "lotto.db"
API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
RATE_LIMIT = 0.3


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"Database: {DB_PATH.resolve()}")
    
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    
    # Check journal mode
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"Journal mode: {journal_mode}")
    
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
    
    cols = {row[1] for row in conn.execute("PRAGMA table_info(draws)")}
    if "draw_number" not in cols:
        conn.execute("ALTER TABLE draws ADD COLUMN draw_number INTEGER")
    
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    print(f"Starting count: {count}")
    conn.close()


def fetch_draw(draw_number: int) -> Optional[dict]:
    url = f"{API_BASE}/{draw_number}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            return None

        data = r.json()
        lotto = data.get("lotto", {})
        winning = lotto.get("lottoWinningNumbers", {})
        numbers_raw = winning.get("numbers", [])
        bonus_raw = winning.get("bonusBalls", "0")

        numbers = [int(n) for n in numbers_raw if str(n).isdigit()]
        if len(numbers) != 6:
            return None

        bonus = int(bonus_raw) if str(bonus_raw).isdigit() else 0

        powerball = None
        pb_section = data.get("powerBall", {})
        if pb_section:
            pb_winning = pb_section.get("powerBallWinningNumbers", {})
            if pb_winning:
                pb_nums = pb_winning.get("numbers", [])
                if pb_nums:
                    powerball = int(pb_nums[0]) if str(pb_nums[0]).isdigit() else None

        return {
            "draw_number": lotto.get("drawNumber"),
            "draw_date": lotto.get("drawDate"),
            "numbers": sorted(numbers),
            "bonus": bonus,
            "powerball": powerball,
        }
    except Exception as e:
        print(f"  ! Error #{draw_number}: {e}")
        return None


def save_draws_batch(draws: list[dict]) -> int:
    """Save multiple draws in a single transaction with explicit checkpoint."""
    if not draws:
        return 0
    
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    saved = 0
    try:
        for draw in draws:
            try:
                conn.execute(
                    "INSERT INTO draws (draw_number, draw_date, numbers, bonus, powerball) VALUES (?, ?, ?, ?, ?)",
                    (draw["draw_number"], draw["draw_date"], ",".join(map(str, draw["numbers"])), 
                     draw["bonus"], draw["powerball"]),
                )
                saved += 1
            except sqlite3.IntegrityError:
                try:
                    conn.execute(
                        "UPDATE draws SET draw_number = ? WHERE draw_date = ?",
                        (draw["draw_number"], draw["draw_date"]),
                    )
                    saved += 1
                except Exception:
                    pass
        
        conn.commit()
        # Force WAL checkpoint to ensure data is written to main db file
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
        conn.close()
        return saved
    except Exception as e:
        print(f"  ! Batch save error: {e}")
        conn.close()
        return 0


def backfill(start: int, end: int) -> None:
    init_db()
    
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    existing = {r[0] for r in conn.execute("SELECT draw_number FROM draws WHERE draw_number > 0")}
    conn.close()
    
    print(f"Existing: {len(existing)} | Fetching #{start} to #{end}")
    print("=" * 60)

    inserted = failed = 0
    batch: list[dict] = []
    t0 = time.time()

    for num in range(start, end + 1):
        if num in existing:
            continue

        draw = fetch_draw(num)
        if draw is None:
            failed += 1
            if failed <= 3:
                print(f"  - #{num}: not found")
        else:
            batch.append(draw)
            
            if len(batch) >= 10:
                saved = save_draws_batch(batch)
                inserted += saved
                batch = []
                if inserted % 20 == 0:
                    elapsed = time.time() - t0
                    print(f"  ... {inserted} saved ({elapsed:.0f}s elapsed)")

        time.sleep(RATE_LIMIT)

    if batch:
        saved = save_draws_batch(batch)
        inserted += saved

    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    conn.close()

    print("=" * 60)
    print(f"Done. Inserted: {inserted} | Failed: {failed}")
    print(f"Total in DB: {count}")
    
    wal_file = DB_PATH.parent / (DB_PATH.name + "-wal")
    shm_file = DB_PATH.parent / (DB_PATH.name + "-shm")
    print(f"WAL file exists: {wal_file.exists()}")
    print(f"SHM file exists: {shm_file.exists()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2512)
    parser.add_argument("--end", type=int, default=2615)
    parser.add_argument("--test", type=int)
    args = parser.parse_args()

    if args.test:
        draw = fetch_draw(args.test)
        print(json.dumps(draw, indent=2) if draw else "Not found")
        return 0

    backfill(args.start, args.end)
    return 0


if __name__ == "__main__":
    sys.exit(main())