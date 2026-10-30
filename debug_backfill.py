#!/usr/bin/env python3
"""Debug version with extensive SQLite logging."""

import sqlite3
import time
from pathlib import Path

import requests

DB_PATH = Path.cwd() / "data" / "lotto.db"
API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"


def test_insert():
    print("=" * 60)
    print("DEBUG: Testing single insert")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)

    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"Journal mode: {journal}")

    print("\nTable schema:")
    for row in conn.execute("PRAGMA table_info(draws)"):
        print(f"  {row}")

    before = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    print(f"\nCount before: {before}")

    test_data = (9999, "2026-01-01", "1,2,3,4,5,6", 10, 5)
    print(f"\nInserting: {test_data}")

    try:
        conn.execute(
            "INSERT INTO draws (draw_number, draw_date, numbers, bonus, powerball) VALUES (?, ?, ?, ?, ?)",
            test_data,
        )
        print("INSERT executed without exception")
    except Exception as e:
        print(f"INSERT failed: {type(e).__name__}: {e}")

    after_insert = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    print(f"Count after INSERT (before commit): {after_insert}")

    conn.commit()
    print("COMMIT executed")

    after_commit = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    print(f"Count after COMMIT: {after_commit}")

    try:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        print(f"Checkpoint result: {result}")
    except Exception as e:
        print(f"Checkpoint error: {e}")

    after_checkpoint = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    print(f"Count after checkpoint: {after_checkpoint}")

    row = conn.execute("SELECT * FROM draws WHERE draw_number = 9999").fetchone()
    print(f"Row lookup: {row}")

    if row:
        conn.execute("DELETE FROM draws WHERE draw_number = 9999")
        conn.commit()
        print("Test row deleted")

    conn.close()
    print("Connection closed")

    conn2 = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    final_count = conn2.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    conn2.close()
    print(f"Count after reopen: {final_count}")

    wal = DB_PATH.parent / (DB_PATH.name + "-wal")
    shm = DB_PATH.parent / (DB_PATH.name + "-shm")
    print(f"WAL file: {wal.exists()}")
    print(f"SHM file: {shm.exists()}")


def fetch_draw(draw_number: int) -> dict | None:
    url = f"{API_BASE}/{draw_number}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
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
    except Exception:
        return None


def debug_backfill():
    print("\n" + "=" * 60)
    print("DEBUG: Backfilling with trace")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    start_count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    conn.close()
    print(f"Starting count: {start_count}")

    for num in range(2615, 2610, -1):
        draw = fetch_draw(num)
        if not draw:
            print(f"#{num}: fetch failed")
            continue

        conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
        try:
            conn.execute(
                "INSERT INTO draws (draw_number, draw_date, numbers, bonus, powerball) VALUES (?, ?, ?, ?, ?)",
                (
                    draw["draw_number"],
                    draw["draw_date"],
                    ",".join(map(str, draw["numbers"])),
                    draw["bonus"],
                    draw["powerball"],
                ),
            )
            conn.commit()

            verify = conn.execute(
                "SELECT * FROM draws WHERE draw_number = ?", (draw["draw_number"],)
            ).fetchone()
            print(f"#{num}: {draw['draw_date']} | Verify: {verify is not None} | Row: {verify}")
        except Exception as e:
            print(f"#{num}: ERROR {type(e).__name__}: {e}")
        finally:
            conn.close()

        time.sleep(0.5)

    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    final_count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    conn.close()
    print(f"\nFinal count: {final_count}")


if __name__ == "__main__":
    test_insert()
    debug_backfill()
