#!/usr/bin/env python3
"""
html_scraper.py — Scrape MyLotto results page as fallback when the API is unavailable.

Parses https://mylotto.co.nz/results/lotto using requests + BeautifulSoup to
extract draw numbers, bonus ball, and Powerball from the result cards.

Usage:
    from html_scraper import scrape_my_lotto_results
    draw = scrape_my_lotto_results()              # latest
    draw = scrape_my_lotto_results("2026-01-15")  # specific date
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://mylotto.co.nz/results/lotto"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Match numbers 1-40
NUMBER_RE = re.compile(r"\b([1-9]|[12]\d|3[0-9]|40)\b")


def _parse_draw_card(card: Tag) -> dict[str, Any] | None:
    """Extract draw data from a single result card element.

    Tries multiple DOM patterns used by the MyLotto results page.

    Returns dict with draw_date, numbers, bonus, powerball, or None.
    """
    # --- Date ---
    date_el = (
        card.find("time") or card.find(class_=re.compile(r"draw.?date", re.I)) or card.find("h3")
    )
    date_str = date_el.get_text(strip=True) if date_el else None
    if not date_str:
        return None

    # Try to normalise date to YYYY-MM-DD
    try:
        # Handle "Wednesday, 15 January 2026" format
        parsed = datetime.strptime(date_str, "%A, %d %B %Y")
        date_iso = parsed.strftime("%Y-%m-%d")
    except ValueError:
        try:
            parsed = datetime.strptime(date_str, "%d %B %Y")
            date_iso = parsed.strftime("%Y-%m-%d")
        except ValueError:
            date_iso = date_str  # keep as-is

    # --- Numbers ---
    # Look for elements with class containing "ball" or "number"
    ball_els = card.find_all(class_=re.compile(r"ball|number|result", re.I))
    if not ball_els:
        # Try finding all spans/divs with numeric text
        ball_els = card.find_all(["span", "div"], string=NUMBER_RE)  # type: ignore[call-overload]

    numbers: list[int] = []
    bonus = 0
    powerball = 0

    for el in ball_els:
        text = el.get_text(strip=True)
        found = NUMBER_RE.findall(text)
        for n_str in found:
            n = int(n_str)
            if 1 <= n <= 40 and n not in numbers and len(numbers) < 6:
                numbers.append(n)

    # If not enough numbers found, try text-based extraction
    if len(numbers) < 6:
        full_text = card.get_text(separator=" ", strip=True)
        all_nums = [int(m) for m in NUMBER_RE.findall(full_text) if 1 <= int(m) <= 40]
        # Deduplicate preserving order
        seen: set[int] = set()
        unique: list[int] = []
        for n in all_nums:
            if n not in seen and len(unique) < 6:
                unique.append(n)
                seen.add(n)
        if len(unique) == 6:
            numbers = unique

    if len(numbers) != 6:
        return None

    # --- Bonus ---
    bonus_el = card.find(string=re.compile(r"bonus", re.I))
    if bonus_el:
        bonus_parent = bonus_el.find_parent()
        if bonus_parent:
            bonus_text = bonus_parent.get_text()
            bonus_match = NUMBER_RE.findall(bonus_text)
            if bonus_match:
                bonus = int(bonus_match[-1])

    # --- Powerball ---
    pb_el = card.find(string=re.compile(r"powerball", re.I))
    if pb_el:
        pb_parent = pb_el.find_parent()
        if pb_parent:
            pb_text = pb_parent.get_text()
            pb_match = re.findall(r"\b(10|[1-9])\b", pb_text)
            if pb_match:
                powerball = int(pb_match[-1])

    return {
        "draw_date": date_iso,
        "numbers": sorted(numbers),
        "bonus": bonus if 1 <= bonus <= 40 else 0,
        "powerball": powerball if 1 <= powerball <= 10 else 0,
    }


def scrape_my_lotto_results(draw_date: str | None = None) -> dict[str, Any] | None:
    """Scrape MyLotto results page for draw numbers.

    Parameters
    ----------
    draw_date : str or None
        Specific date (YYYY-MM-DD) to find, or None for latest.

    Returns
    -------
    dict or None
        Keys: draw_date, numbers (list[6 ints]), bonus (int), powerball (int).
        Returns None if scraping fails.
    """
    import time

    retry_delays = [1, 2, 4]
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    for attempt, delay in enumerate(retry_delays, 1):
        try:
            resp = session.get(BASE_URL, timeout=15)
            resp.raise_for_status()
            break  # success, exit retry loop
        except requests.ConnectionError as e:
            print(f"  HTML scraper connection error (attempt {attempt}/{len(retry_delays)}): {e}")
            if attempt < len(retry_delays):
                time.sleep(delay)
        except requests.Timeout as e:
            print(f"  HTML scraper timeout (attempt {attempt}/{len(retry_delays)}): {e}")
            if attempt < len(retry_delays):
                time.sleep(delay)
        except requests.HTTPError:
            return None  # don't retry on HTTP errors
        except requests.RequestException as e:
            print(f"  HTML scraper error: {e}")
            return None
    else:
        # All retries exhausted
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find result cards — try multiple common patterns
    cards = (
        soup.find_all(class_=re.compile(r"result.?card", re.I))
        or soup.find_all("article")
        or soup.find_all(class_=re.compile(r"draw", re.I))
    )

    if not cards:
        # Fallback: look for any structured block with numbers
        cards = soup.find_all(["div", "section"])

    for card in cards:
        result = _parse_draw_card(card)
        if result is None:
            continue
        if draw_date is None or result["draw_date"] == draw_date:
            return result

    return None


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Testing html_scraper...")
    result = scrape_my_lotto_results()
    if result:
        print(f"Date:      {result['draw_date']}")
        print(f"Numbers:   {result['numbers']}")
        print(f"Bonus:     {result['bonus']}")
        print(f"Powerball: {result['powerball']}")
    else:
        print("Scraping failed (network or page structure changed).")
