#!/usr/bin/env python3
"""
backfill_bonus.py — Backfill bonus ball data for historical draws from NZCity.

Scrapes https://home.nzcity.co.nz/lotto/lotto.aspx?draw={draw_id}
for the bonus ball number and updates lotto_working.db.

Uses burst-based rate limiting: 15 requests at 2s intervals, then waits
300s on 429 (NZCity limit). Resumable — tracks progress in the DB itself.

Usage:
    python3 backfill_bonus.py              # backfill all missing
    python3 backfill_bonus.py --start 1000  # start from a specific draw_id
    python3 backfill_bonus.py --dry-run     # just show what needs filling
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

import requests
from bs4 import BeautifulSoup

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lotto_working.db")
BASE_URL = "https://home.nzcity.co.nz/lotto/lotto.aspx?draw={}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://home.nzcity.co.nz/lotto/",
}
# Rate-limiting strategy: NZCity allows ~15-20 requests before 429 with Retry-After: 300s.
# Best throughput: fire 15 requests at ~2s intervals, then wait the 300s.
BURST_SIZE = 10  # requests per burst before expected 429
BURST_DELAY = 2.5  # seconds between requests within a burst
RETRY_AFTER = 330  # seconds to wait on 429 (sliding window clearance)
MAX_RETRIES = 10
PAUSE_AFTER_BURST = 60  # short pause between bursts to help sliding window


def get_connection():
    import sqlite3

    return sqlite3.connect(DB_PATH)


def get_missing_draws(conn):
    """Return list of (draw_id, draw_date) for draws missing bonus data."""
    rows = conn.execute(
        "SELECT draw_id, draw_date FROM draws WHERE bonus IS NULL OR bonus = 0 ORDER BY draw_id"
    ).fetchall()
    return rows


def fetch_bonus_from_nzcity(draw_id: int) -> int | None:
    """Scrape NZCity page for bonus ball number. Returns int or None on failure."""
    url = BASE_URL.format(draw_id)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    bonus_img = soup.find("img", id="ctl00_ContentPlaceHolder1_bonus1")
    if bonus_img and bonus_img.get("alt"):
        # alt attribute like "Bonus number 29"
        alt = bonus_img["alt"]
        parts = alt.split()
        for p in parts:
            try:
                n = int(p)
                if 1 <= n <= 40:
                    return n
            except ValueError:
                continue

    # Fallback: try finding the bonus label text
    bonus_label = soup.find("span", id="ctl00_ContentPlaceHolder1_lblBonus")
    if bonus_label:
        text = bonus_label.get_text(strip=True)
        for word in text.split():
            try:
                n = int(word)
                if 1 <= n <= 40:
                    return n
            except ValueError:
                continue

    return None


def update_bonus(conn, draw_id: int, bonus: int) -> bool:
    """Update bonus ball in DB. Returns True if updated."""
    cur = conn.execute(
        "UPDATE draws SET bonus = ? WHERE draw_id = ? AND (bonus IS NULL OR bonus = 0)",
        (bonus, draw_id),
    )
    conn.commit()
    return cur.rowcount > 0


def main():
    parser = argparse.ArgumentParser(description="Backfill bonus ball data from NZCity")
    parser.add_argument("--start", type=int, default=None, help="Start from this draw_id")
    parser.add_argument(
        "--dry-run", action="store_true", help="Just list missing draws, don't fetch"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=BURST_DELAY,
        help=f"Delay between requests (default {BURST_DELAY}s)",
    )
    parser.add_argument(
        "--max-retries", type=int, default=MAX_RETRIES, help="Max retries on persistent errors"
    )
    args = parser.parse_args()

    conn = get_connection()
    missing = get_missing_draws(conn)

    if not missing:
        print("All draws already have bonus data!")
        conn.close()
        return

    if args.start:
        missing = [(did, dt) for did, dt in missing if did >= args.start]

    total = len(missing)
    print(f"Need to backfill {total} draws (draw_ids {missing[0][0]}–{missing[-1][0]})")

    if args.dry_run:
        for did, dt in missing[:20]:
            print(f"  {did}: {dt}")
        if total > 20:
            print(f"  ... and {total - 20} more")
        conn.close()
        return

    success = 0
    failed = 0
    skipped = 0
    start_time = time.time()
    last_success_time = 0.0  # timestamp of the last successful request

    i = 0
    while i < total:
        draw_id, draw_date = missing[i]
        i += 1
        retries = 0
        bonus = None

        while retries <= args.max_retries:
            try:
                bonus = fetch_bonus_from_nzcity(draw_id)
                if bonus is not None:
                    last_success_time = time.time()
                    break
                retries += 1
                time.sleep(args.delay)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code
                if status == 429:
                    # Wait 300s from the LAST SUCCESS, not from the 429 response.
                    # This prevents retry-reset loops when the sliding window hasn't fully cleared.
                    if last_success_time > 0:
                        elapsed_since_success = time.time() - last_success_time
                        wait = max(RETRY_AFTER + random.uniform(5, 30) - elapsed_since_success, 60)
                    else:
                        wait = RETRY_AFTER + random.uniform(0, 30)
                    print(
                        f"\n  429 after {success+skipped+failed} draws! Waiting {wait:.0f}s...",
                        end=" ",
                        flush=True,
                    )
                    elapsed = time.time() - start_time
                    rate = success / elapsed * 60 if elapsed > 0 else 0
                    eta = (total - i) / rate * 60 if rate > 0 else 0
                    print(
                        f"({success} ok, {failed} failed, {skipped} skipped, "
                        f"{total - i + 1} remaining, ETA {eta/60:.1f} min)"
                    )
                    time.sleep(wait)
                    retries += 1
                    continue
                elif status == 404:
                    print(f"\n  404 for draw {draw_id} ({draw_date}), skipping")
                    bonus = -1
                    break
                else:
                    print(f"\n  HTTP {status} for draw {draw_id}: {e}")
                    retries += 1
                    time.sleep(args.delay * 2)
                    continue
            except (requests.ConnectionError, requests.Timeout) as e:
                print(f"\n  Network error for draw {draw_id}: {e}")
                retries += 1
                time.sleep(args.delay * 3)
                continue

        if bonus is None:
            print(f"  FAILED draw {draw_id} ({draw_date}) — no bonus after {retries} retries")
            failed += 1
        elif bonus == -1:
            skipped += 1
        else:
            if update_bonus(conn, draw_id, bonus):
                success += 1
            else:
                skipped += 1

        # Progress report
        if i % 15 == 0 or i == total:
            elapsed = time.time() - start_time
            rate = success / elapsed * 60 if elapsed > 0 else 0
            eta = (total - i) / rate * 60 if rate > 0 else 0
            print(
                f"  [{i}/{total}] {success} ok, {failed} failed, {skipped} skipped "
                f"| {rate:.1f}/min | ETA {eta/60:.1f} min"
            )
            sys.stdout.flush()

        # Rate-limiting: pause between bursts to let the sliding window breathe
        if i < total:
            if i % BURST_SIZE == 0:
                time.sleep(PAUSE_AFTER_BURST + random.uniform(0, 5))
            else:
                time.sleep(args.delay + random.uniform(0, 0.5))

    conn.close()

    elapsed = time.time() - start_time
    print(f"\nDone! {success} updated, {failed} failed, {skipped} skipped in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
