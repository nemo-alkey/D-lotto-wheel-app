#!/usr/bin/env python3
"""Backfill NZ Lotto draws via API discovery or Selenium archive scraping."""

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

DB_PATH = Path("data/lotto.db")
ARCHIVE_URL = "https://mylotto.co.nz/results/lotto/archive"
JS_BUNDLE_URL = "https://mylotto.co.nz/static/js/mylotto-37.0.23.3af83e09.js"


def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(draw_date)")
    conn.commit()
    conn.close()


def get_existing_dates() -> set[str]:
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    rows = conn.execute("SELECT draw_date FROM draws").fetchall()
    conn.close()
    return {r[0] for r in rows}


def insert_draw(
    draw_date: str,
    numbers: list[int],
    bonus: int,
    powerball: int | None,
    draw_number: int = 0,
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
        conn.close()
        return False


def discover_api_from_bundle() -> str | None:
    """Search the JS bundle for draw/history API endpoints."""
    print("Searching JS bundle for hidden API endpoints...")
    try:
        r = requests.get(JS_BUNDLE_URL, timeout=15)
        if r.status_code != 200:
            print(f"  Could not fetch bundle: {r.status_code}")
            return None

        text = r.text
        candidates = set()

        for m in re.findall(r'["\'](/[^"\s<>]+)["\']', text):
            if any(k in m.lower() for k in ["draw", "result", "history", "lotto", "api"]):
                candidates.add("https://mylotto.co.nz" + m)

        for m in re.findall(r'(https?://[^"\s<>]+)', text):
            if any(k in m.lower() for k in ["draw", "result", "history", "lotto", "api"]):
                candidates.add(m)

        candidates = {c for c in candidates if c.endswith((".json", "")) or "/api/" in c}

        print(f"  Found {len(candidates)} candidate endpoints")
        for url in sorted(candidates)[:20]:
            try:
                resp = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
                ct = resp.headers.get("content-type", "")
                if resp.status_code == 200 and "json" in ct:
                    data = resp.json()
                    sample = str(data)[:200].lower()
                    if any(k in sample for k in ["drawnumber", "drawdate", "numbers", "bonusball"]):
                        print(f"  ✓ WORKING: {url}")
                        return url
                    else:
                        print(f"  ? JSON but not draw data: {url}")
                else:
                    print(f"  ✗ {url} -> {resp.status_code}")
            except Exception as e:
                print(f"  ✗ {url} -> {e}")

        return None
    except Exception as e:
        print(f"  Error inspecting bundle: {e}")
        return None


def backfill_from_api(api_url: str) -> None:
    """Backfill using a discovered bulk API."""
    print(f"\nFetching from: {api_url}")
    try:
        resp = requests.get(api_url, headers={"Accept": "application/json"}, timeout=30)
        data = resp.json()

        draws: list[dict] = []
        if isinstance(data, list):
            draws = data
        elif isinstance(data, dict):
            for key in ["draws", "results", "data", "lotto", "items"]:
                if key in data and isinstance(data[key], list):
                    draws = data[key]
                    break

        print(f"Found {len(draws)} draws in API response")

        existing = get_existing_dates()
        inserted = skipped = 0

        for draw in draws:
            try:
                draw_date = draw.get("drawDate") or draw.get("date") or draw.get("draw_date")
                draw_num = draw.get("drawNumber") or draw.get("draw_number") or 0

                nums_raw = draw.get("numbers") or draw.get("mainBalls") or []
                if isinstance(nums_raw, str):
                    nums = [int(n.strip()) for n in nums_raw.split(",")]
                else:
                    nums = [int(n) for n in nums_raw]

                bonus = int(draw.get("bonusBall") or draw.get("bonus") or 0)
                pb = draw.get("powerball")
                powerball = int(pb) if pb is not None else None

                if draw_date in existing:
                    skipped += 1
                    continue

                if insert_draw(
                    draw_date, sorted(nums), bonus, powerball, int(draw_num) if draw_num else 0
                ):
                    inserted += 1
                    if inserted % 100 == 0:
                        print(f"  ... {inserted} inserted")
                else:
                    skipped += 1
            except Exception as e:
                print(f"  ! Skipping draw: {e}")

        print(f"\nDone. Inserted: {inserted} | Skipped: {skipped}")
    except Exception as e:
        print(f"API backfill failed: {e}")


def backfill_selenium() -> None:
    """Backfill using Selenium to scrape the archive page."""
    print("\n" + "=" * 60)
    print("FALLBACK: Selenium archive scraper")
    print("=" * 60)

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError:
        print("Selenium not installed. Run: pip install selenium webdriver-manager")
        return

    try:
        from webdriver_manager.chrome import ChromeDriverManager

        service = Service(ChromeDriverManager().install())
    except ImportError:
        service = Service()

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=options)
        driver.get(ARCHIVE_URL)

        WebDriverWait(driver, 20).until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "main"))
        )
        time.sleep(3)

        existing = get_existing_dates()
        inserted = skipped = 0
        last_count = 0
        stagnant = 0

        while stagnant < 3:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

            from bs4 import BeautifulSoup

            soup = BeautifulSoup(driver.page_source, "html.parser")

            cards = (
                soup.find_all("article")
                or soup.find_all(class_=re.compile(r"draw|result", re.I))
                or soup.find_all("div", class_=lambda x: x and "card" in x.lower())
            )

            print(f"  Found {len(cards)} cards on page")

            for card in cards:
                try:
                    date_el = (
                        card.find("time")
                        or card.find("h3")
                        or card.find(class_=re.compile(r"date", re.I))
                    )
                    if not date_el:
                        continue
                    date_str = date_el.get_text(strip=True)

                    for fmt in ["%A %d %B %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y"]:
                        try:
                            parsed = datetime.strptime(date_str, fmt)
                            date_str = parsed.strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue
                    else:
                        continue

                    if date_str in existing:
                        skipped += 1
                        continue

                    text = card.get_text(separator=" ", strip=True)
                    nums = [int(n) for n in re.findall(r"\b([1-9]|[12]\d|3[0-9]|40)\b", text)]
                    if len(nums) < 6:
                        continue

                    main = sorted(nums[:6])
                    bonus = nums[6] if len(nums) > 6 else 0

                    pb_match = re.search(r"Powerball[:\s]*(\d+)", text, re.I)
                    powerball = int(pb_match.group(1)) if pb_match else None

                    dn_match = re.search(r"#?(\d{1,4})", text)
                    draw_num = int(dn_match.group(1)) if dn_match else 0

                    if insert_draw(date_str, main, bonus, powerball, draw_num):
                        inserted += 1
                    else:
                        skipped += 1
                except Exception:
                    continue

            if len(cards) == last_count:
                stagnant += 1
                print(f"  No new cards loaded ({stagnant}/3)")
            else:
                stagnant = 0
                last_count = len(cards)

            try:
                load_more = driver.find_element(
                    By.XPATH, "//button[contains(text(), 'Load') or contains(text(), 'More')]"
                )
                if load_more.is_displayed():
                    load_more.click()
                    time.sleep(3)
                    stagnant = 0
            except Exception:
                pass

        print(f"\nDone. Inserted: {inserted} | Skipped: {skipped}")

    except Exception as e:
        print(f"Selenium error: {e}")
    finally:
        if driver:
            driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill NZ Lotto historical draws")
    parser.add_argument("--method", choices=["auto", "api", "selenium"], default="auto")
    args = parser.parse_args()

    ensure_db()
    existing = get_existing_dates()
    print(f"Existing draws in DB: {len(existing)}")

    if args.method == "auto":
        api_url = discover_api_from_bundle()
        if api_url:
            backfill_from_api(api_url)
        else:
            print("\nNo bulk API found. Falling back to Selenium...")
            backfill_selenium()
    elif args.method == "api":
        api_url = discover_api_from_bundle()
        if api_url:
            backfill_from_api(api_url)
        else:
            print("No bulk API found. Try --method selenium")
    elif args.method == "selenium":
        backfill_selenium()

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    conn.close()
    print(f"\nTotal draws in database: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
