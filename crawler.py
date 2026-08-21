#!/usr/bin/env python3
"""
crawler.py — Crawl MyLotto historical results archive to backfill the database.

Walks through "Previous Results" links, scrapes each page for draw data,
and inserts new draws into lotto.db.

Respects robots.txt, uses polite delays (2-5s), and avoids revisiting pages.

Usage:
    python crawler.py --start-date 2020-01-01 --max-pages 100
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sqlite3
import time
from datetime import datetime
from typing import Any, cast
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://mylotto.co.nz/results/lotto"
ROBOTS_URL = "https://mylotto.co.nz/robots.txt"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

NUMBER_RE = re.compile(r"\b([1-9]|[12]\d|3[0-9]|40)\b")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lotto.db")
PROGRESS_FILE = "crawl_progress.txt"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _init_db(conn: sqlite3.Connection) -> None:
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


def _insert_draw(conn: sqlite3.Connection, draw: dict[str, Any]) -> bool:
    """Insert a draw. Returns True if inserted, False if duplicate/error."""
    nums_str = ",".join(str(n) for n in draw["numbers"])
    try:
        cur = conn.execute("SELECT COALESCE(MAX(draw_id), 0) FROM draws")
        new_id = cur.fetchone()[0] + 1
        conn.execute(
            "INSERT INTO draws (draw_id, draw_date, numbers, bonus, powerball) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                new_id,
                draw["draw_date"],
                nums_str,
                draw.get("bonus", 0),
                draw["powerball"],
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


# ---------------------------------------------------------------------------
# Robots.txt check
# ---------------------------------------------------------------------------


def _check_robots() -> bool:
    """Return True if crawling is allowed per robots.txt."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        resp = session.get(ROBOTS_URL, timeout=10)
        if resp.status_code != 200:
            return True  # no robots.txt = assume allowed
        for line in resp.text.splitlines():
            if line.strip().lower().startswith("disallow:") and "/results/lotto" in line:
                return False
        return True
    except requests.RequestException:
        return True  # can't check = assume allowed


# ---------------------------------------------------------------------------
# Page scraping
# ---------------------------------------------------------------------------


def _extract_draws_from_page(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Extract all draws from a results page.

    Returns list of dicts with draw_date, numbers (6 ints), bonus, powerball.
    """
    draws: list[dict[str, Any]] = []

    # Find result cards
    cards = (
        soup.find_all(class_=re.compile(r"result.?card", re.I))
        or soup.find_all("article")
        or soup.find_all(class_=re.compile(r"draw", re.I))
    )

    for card in cards:
        # Date
        date_el = card.find("time") or card.find("h3")
        date_str = date_el.get_text(strip=True) if date_el else None
        if not date_str:
            continue

        # Normalise date
        date_iso = date_str
        for fmt in ("%A, %d %B %Y", "%d %B %Y", "%Y-%m-%d"):
            try:
                date_iso = datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

        # Numbers
        full_text = card.get_text(separator=" ", strip=True)
        all_nums = [int(m) for m in NUMBER_RE.findall(full_text) if 1 <= int(m) <= 40]
        seen: set[int] = set()
        numbers: list[int] = []
        for n in all_nums:
            if n not in seen and len(numbers) < 6:
                numbers.append(n)
                seen.add(n)

        if len(numbers) != 6:
            continue

        # Bonus
        bonus = 0
        bonus_el = card.find(string=re.compile(r"bonus", re.I))
        if bonus_el:
            bp = bonus_el.find_parent()
            if bp:
                bm = NUMBER_RE.findall(bp.get_text())
                if bm:
                    bonus = int(bm[-1])

        # Powerball
        powerball = 0
        pb_el = card.find(string=re.compile(r"powerball", re.I))
        if pb_el:
            pp = pb_el.find_parent()
            if pp:
                pm = re.findall(r"\b(10|[1-9])\b", pp.get_text())
                if pm:
                    powerball = int(pm[-1])

        draws.append(
            {
                "draw_date": date_iso,
                "numbers": sorted(numbers),
                "bonus": bonus if 1 <= bonus <= 40 else 0,
                "powerball": powerball if 1 <= powerball <= 10 else 0,
            }
        )

    return draws


def _find_previous_link(soup: BeautifulSoup, base_url: str) -> str | None:
    """Find the 'Previous Results' or 'Next' pagination link."""
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = cast(str, a["href"])
        if any(kw in text or kw in href.lower() for kw in ("previous", "older", "next", "prev")):
            return urljoin(base_url, href)
    return None


# ---------------------------------------------------------------------------
# Main crawler
# ---------------------------------------------------------------------------


def _save_progress(url: str, pages: int, inserted: int) -> None:
    """Save crawl state to progress file for resumption."""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        f.write(f"{url}\n{pages}\n{inserted}\n")


def _load_progress() -> tuple[str | None, int, int]:
    """Load crawl state from progress file. Returns (url, pages, inserted)."""
    if not os.path.exists(PROGRESS_FILE):
        return None, 0, 0
    with open(PROGRESS_FILE, encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
    if len(lines) < 3:
        return None, 0, 0
    return lines[0], int(lines[1]), int(lines[2])


def crawl_historical_results(
    start_url: str = BASE_URL,
    max_pages: int = 50,
    start_date: str | None = None,
) -> int:
    """Crawl historical MyLotto results and backfill the database.

    Parameters
    ----------
    start_url : str
        Starting URL for the crawl.
    max_pages : int
        Maximum number of pages to visit.
    start_date : str or None
        Stop crawling when draws are older than this date (YYYY-MM-DD).

    Returns
    -------
    int
        Number of new draws inserted.
    """
    if not _check_robots():
        print("Crawling disallowed by robots.txt. Aborting.")
        return 0

    # Parse start_date if provided
    stop_date = None
    if start_date:
        try:
            stop_date = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            print(f"Invalid --start-date: {start_date}")
            return 0

    conn = sqlite3.connect(DB_PATH)
    _init_db(conn)
    before = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    visited: set[str] = set()

    # Resume from saved progress if available
    saved_url, saved_pages, saved_inserted = _load_progress()
    if saved_url:
        print(f"Resuming from {PROGRESS_FILE}: page {saved_pages}, {saved_inserted} inserted")
        url = saved_url
        pages = saved_pages
        inserted = saved_inserted
    else:
        url = start_url
        pages = 0
        inserted = 0

    while url and pages < max_pages:
        if url in visited:
            break
        visited.add(url)

        pages += 1
        print(f"[Page {pages}/{max_pages}] {url}")

        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  Request failed: {e}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        draws = _extract_draws_from_page(soup)
        print(f"  Found {len(draws)} draw(s)")

        for draw in draws:
            # Stop if draw is older than start_date
            try:
                draw_dt = datetime.strptime(draw["draw_date"], "%Y-%m-%d")
                if stop_date and draw_dt < stop_date:
                    print(f"  Reached {draw['draw_date']} (< {start_date}). Stopping.")
                    conn.close()
                    after = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
                    print(f"Total: {after - before} new draws inserted.")
                    return inserted
            except ValueError:
                pass

            if _insert_draw(conn, draw):
                inserted += 1

        # Navigate to previous page
        next_url = _find_previous_link(soup, url)
        if not next_url or next_url == url:
            print("  No more pages.")
            break
        url = next_url

        # Save progress for resumption
        _save_progress(url, pages, inserted)

        # Polite delay
        delay = random.uniform(2, 5)
        time.sleep(delay)

    conn.close()
    after = sqlite3.connect(DB_PATH).execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    total_new = after - before
    print(f"\nDone. {pages} pages visited, {total_new} new draws inserted. DB: {after} draws.")

    # Clear progress file on successful completion
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("Progress file cleared.")

    return inserted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl MyLotto historical results.")
    parser.add_argument("--start-date", help="Stop when draws are older than YYYY-MM-DD")
    parser.add_argument("--max-pages", type=int, default=50, help="Max pages to visit")
    parser.add_argument("--resume", action="store_true", help="Resume from saved progress")
    args = parser.parse_args()

    # Load progress if resuming
    start_url = BASE_URL
    visited_pages = 0
    inserted_count = 0
    if args.resume:
        saved_url, saved_pages, saved_inserted = _load_progress()
        if saved_url:
            start_url = saved_url
            visited_pages = saved_pages
            inserted_count = saved_inserted
            print(f"Resuming from: {start_url} (page {visited_pages}, {inserted_count} inserted)")

    crawl_historical_results(
        start_url=start_url,
        max_pages=args.max_pages,
        start_date=args.start_date,
    )


if __name__ == "__main__":
    main()
