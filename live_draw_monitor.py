#!/usr/bin/env python3
"""
live_draw_monitor.py — Headless monitor for NZ Lotto live draws.

Polls the MyLotto results page during draw time (Wednesdays and Saturdays,
20:20 NZ time), screenshots the result element, and OCRs the balls as they
drop. When a new draw is detected (compared against the last draw in the
database), the monitor:

  1. Inserts the draw via database.insert_draw()
  2. Calls accuracy_tracker.on_new_draw_fetched() to backfill predictions
     and refresh scorecards
  3. Checks all preset wheels and sends winner alerts via notifier.py
  4. Logs everything to data/logs/live_monitor.log

If OCR fails 3 polls in a row, the monitor falls back to HTML scraping
(html_scraper.py), and finally to the official MyLotto API
(update_draws.fetch_draw) — the API is also used to enrich OCR results with
the canonical draw date and the Powerball number (OCR targets only the 6
main numbers + bonus; a draw is NOT inserted unless the Powerball is known,
to keep the database clean).

Dependencies
------------
Required regardless:  pillow, requests, beautifulsoup4 (already installed)
For the browser/OCR path:
    pip install selenium webdriver-manager pytesseract
    # plus the Tesseract binary itself:
    #   Windows: https://github.com/UB-Mannheim/tesseract/wiki (installer)
    #   Linux:   sudo apt-get install tesseract-ocr
Optional OCR alternative:
    pip install easyocr
Optional (timezone database on Windows):
    pip install tzdata

Usage
-----
    python live_draw_monitor.py                # run the monitor loop
    python live_draw_monitor.py --dry-run      # log actions, write nothing
    python live_draw_monitor.py --once         # single poll cycle, then exit
    python live_draw_monitor.py --interval 15  # override poll interval (s)

Run as a service: see monitor_service.py.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import time
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, cast

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RESULTS_URL = "https://mylotto.co.nz/lotto/results"
LOG_FILE = Path("data/logs/live_monitor.log")

POLL_INTERVAL = 30  # seconds between polls during the draw window
DRAW_HOUR = 20  # 20:20 NZ time
DRAW_MINUTE = 20
WINDOW_START_MIN = 15  # start polling at 20:15
WINDOW_END_MIN = 90  # stop polling at 21:30
DRAW_WEEKDAYS = {2, 5}  # Wednesday, Saturday (Monday = 0)

OCR_MAX_FAILURES = 3  # consecutive OCR failures before HTML fallback
POOL_SIZE = 40  # main numbers 1..40
NUM_MAIN = 6

# NZ timezone — zoneinfo needs the tzdata package on Windows
try:
    from zoneinfo import ZoneInfo

    NZ_TZ: tzinfo = ZoneInfo("Pacific/Auckland")
except Exception:  # pragma: no cover - Windows without tzdata
    NZ_TZ = timezone(timedelta(hours=12))  # NZST fallback (no DST!)

# ---------------------------------------------------------------------------
# Optional dependencies
# ---------------------------------------------------------------------------
try:
    from selenium_scraper import SELENIUM_AVAILABLE, _get_driver
except ImportError:
    SELENIUM_AVAILABLE = False
    _get_driver = None  # type: ignore[assignment]  # optional dependency fallback

try:
    import pytesseract
    from PIL import Image, ImageOps

    OCR_ENGINE: str | None = "pytesseract"
except ImportError:
    pytesseract = None
    try:
        from PIL import Image, ImageOps  # pillow alone is still useful
    except ImportError:
        Image = None  # type: ignore[assignment]  # optional dependency fallback
    OCR_ENGINE = None

try:
    import easyocr  # noqa: F401

    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    """Append a timestamped line to the log file and print to stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # logging must never crash the monitor


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def nz_now() -> datetime:
    """Current time in New Zealand."""
    return datetime.now(NZ_TZ)


def in_draw_window(now: datetime | None = None) -> bool:
    """True if `now` is a Wed/Sat between 20:15 and 21:30 NZ time."""
    now = now or nz_now()
    if now.weekday() not in DRAW_WEEKDAYS:
        return False
    minutes = now.hour * 60 + now.minute
    start = DRAW_HOUR * 60 + WINDOW_START_MIN
    end = DRAW_HOUR * 60 + WINDOW_END_MIN
    return start <= minutes <= end


def seconds_until_window(now: datetime | None = None) -> float:
    """Seconds until the next draw window opens (capped at 1 day)."""
    now = now or nz_now()
    for days_ahead in range(0, 8):
        day = now.date() + timedelta(days=days_ahead)
        candidate = datetime(
            day.year,
            day.month,
            day.day,
            DRAW_HOUR,
            WINDOW_START_MIN,
            tzinfo=NZ_TZ,
        )
        if candidate.weekday() not in DRAW_WEEKDAYS:
            continue
        if candidate > now:
            return (candidate - now).total_seconds()
    return 24 * 3600.0


# ---------------------------------------------------------------------------
# Number extraction & validation
# ---------------------------------------------------------------------------


def validate_numbers(main: list[int], bonus: int) -> tuple[list[int], int]:
    """Validate 6 main numbers + 1 bonus: 7 unique integers in 1..40.

    Returns (sorted_main, bonus). Raises ValueError on any violation.
    """
    if len(main) != NUM_MAIN:
        raise ValueError(f"Expected {NUM_MAIN} main numbers, got {len(main)}: {main}")
    all_nums = list(main) + [bonus]
    if len(set(all_nums)) != NUM_MAIN + 1:
        raise ValueError(f"Numbers not unique: {all_nums}")
    for n in all_nums:
        if not (1 <= n <= POOL_SIZE):
            raise ValueError(f"Number {n} out of range (1-{POOL_SIZE})")
    return sorted(all_nums[:NUM_MAIN]), all_nums[NUM_MAIN]


def _parse_numbers_from_text(text: str) -> list[int]:
    """Pull 1-2 digit integers out of OCR text, in reading order."""
    return [int(t) for t in re.findall(r"\d{1,2}", text)]


def extract_numbers_ocr(image_bytes: bytes) -> tuple[list[int], int, int | None]:
    """OCR a result screenshot -> (main6, bonus, powerball or None).

    Tries pytesseract first, then easyocr. Raises ValueError if fewer than
    7 plausible ball numbers are found.
    """
    raw_text = ""

    if OCR_ENGINE == "pytesseract" and Image is not None:
        img = Image.open(io.BytesIO(image_bytes))
        # Preprocess: grayscale -> upscale -> threshold (balls are white
        # digits on coloured circles)
        proc = ImageOps.grayscale(img)
        proc = proc.resize((proc.width * 3, proc.height * 3))
        proc = proc.point(lambda px: 255 if px > 140 else 0)
        raw_text = pytesseract.image_to_string(
            proc, config="--psm 6 -c tessedit_char_whitelist=0123456789"
        )
    elif EASYOCR_AVAILABLE and Image is not None:
        reader = easyocr.Reader(["en"], gpu=False)
        results = reader.readtext(io.BytesIO(image_bytes).read())
        raw_text = " ".join(r[1] for r in results)
    else:
        raise RuntimeError("No OCR engine available (install pytesseract or easyocr).")

    found = _parse_numbers_from_text(raw_text)
    plausible = [n for n in found if 1 <= n <= POOL_SIZE]
    if len(plausible) < NUM_MAIN + 1:
        raise ValueError(
            f"OCR found only {len(plausible)} plausible numbers: {plausible}"
        )

    main = plausible[:NUM_MAIN]
    bonus = plausible[NUM_MAIN]
    pb: int | None = None
    if len(plausible) > NUM_MAIN + 1 and 1 <= plausible[NUM_MAIN + 1] <= 10:
        pb = plausible[NUM_MAIN + 1]

    main, bonus = validate_numbers(main, bonus)
    return main, bonus, pb


# ---------------------------------------------------------------------------
# Fallback fetchers
# ---------------------------------------------------------------------------


def fetch_via_html_scraper(date: str | None = None) -> dict[str, Any] | None:
    """HTML-scrape fallback (reuses html_scraper.py)."""
    try:
        from html_scraper import scrape_my_lotto_results
    except ImportError:
        log("  HTML scraper unavailable (missing beautifulsoup4?).")
        return None
    try:
        result = scrape_my_lotto_results(date)
    except Exception as e:
        log(f"  HTML scraper error: {e}")
        return None
    if result:
        log(f"  HTML fallback got draw {result['draw_date']}")
    return result


def fetch_via_api(date: str | None = None) -> dict[str, Any] | None:
    """Official MyLotto API (reuses update_draws.fetch_draw)."""
    try:
        from update_draws import fetch_draw
    except ImportError:
        log("  update_draws.fetch_draw unavailable.")
        return None
    try:
        return fetch_draw(date)
    except Exception as e:
        log(f"  API fetch error: {e}")
        return None


# ---------------------------------------------------------------------------
# Browser capture
# ---------------------------------------------------------------------------


def capture_results_screenshot(driver: Any) -> bytes | None:
    """Screenshot the results element on the MyLotto page."""
    from selenium.webdriver.common.by import By

    # Candidate selectors for the container showing the drawn balls
    selectors = [
        "[data-testid='winning-numbers']",
        ".winning-numbers",
        ".results-numbers",
        ".lotto-balls",
        ".draw-results",
        "main",
    ]
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el and el.size.get("width", 0) > 0:
                return cast(bytes, el.screenshot_as_png)
        except Exception:
            continue
    return None


def poll_once_ocr(driver: Any) -> dict[str, Any]:
    """One OCR poll cycle. Returns {numbers, bonus, powerball} or None."""
    driver.get(RESULTS_URL)
    time.sleep(3)  # let the page render
    shot = capture_results_screenshot(driver)
    if not shot:
        raise RuntimeError("Could not locate results element on page.")
    main, bonus, pb = extract_numbers_ocr(shot)
    return {"numbers": main, "bonus": bonus, "powerball": pb}


# ---------------------------------------------------------------------------
# API broadcast (WebSocket clients)
# ---------------------------------------------------------------------------


def publish_draw_event(
    draw: dict[str, Any],
    winners: list[dict[str, Any]] | None = None,
    source: str = "live_draw_monitor",
) -> bool:
    """Announce a new draw to the API's WebSocket broadcaster (best-effort).

    Tries Redis pub/sub (channel lotto:draw-events) first — that reaches the
    API process directly — then falls back to the HTTP hook
    POST /internal/new-draw. Never raises; returns True if either worked.
    """
    import json as _json
    import os

    payload = {
        "type": "new_draw",
        "draw_date": draw.get("draw_date"),
        "numbers": sorted(draw.get("numbers", [])),
        "bonus": draw.get("bonus"),
        "powerball": draw.get("powerball"),
        "winners": winners or [],
        "source": source,
    }

    try:
        import redis

        r = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379"),
            socket_timeout=1,
        )
        r.publish("lotto:draw-events", _json.dumps(payload))
        log("  Draw event published via Redis.")
        return True
    except Exception:
        pass

    try:
        import requests

        headers = {}
        token = os.environ.get("INTERNAL_NOTIFY_TOKEN", "")
        if token:
            headers["X-Internal-Token"] = token
        resp = requests.post(
            "http://localhost:8000/internal/new-draw",
            json=payload,
            headers=headers,
            timeout=2,
        )
        ok = resp.status_code == 200
        log(f"  Draw event POST to API: {'ok' if ok else resp.status_code}")
        return ok
    except Exception as e:
        log(f"  Draw event publish failed (API offline?): {e}")
        return False


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def get_latest_db_draw() -> dict[str, Any] | None:
    """The most recent draw currently in the database (via database.py)."""
    from database import fetch_recent_draws

    recent = fetch_recent_draws(limit=1)
    return recent[0] if recent else None


# ---------------------------------------------------------------------------
# New-draw processing
# ---------------------------------------------------------------------------


def process_new_draw(draw: dict[str, Any], dry_run: bool = False) -> bool:
    """Insert a newly detected draw and fire all downstream actions.

    draw: {"draw_date", "numbers", "bonus", "powerball"}.
    Returns True if the draw was processed (or would be, in dry-run).
    """
    date = draw["draw_date"]
    numbers = draw["numbers"]
    bonus = draw["bonus"]
    pb = draw.get("powerball")

    nums_str = ", ".join(f"{n:02d}" for n in numbers)
    log(f"NEW DRAW DETECTED: {date} -> {nums_str} | Bonus {bonus:02d} | PB {pb}")

    if pb is None:
        log(
            "  Powerball unknown — refusing to insert incomplete draw. "
            "Will retry next poll (API enrichment)."
        )
        return False

    # 1) Insert into the database
    if dry_run:
        log(f"  [DRY-RUN] would insert draw {date} into the database")
    else:
        from database import draw_exists, insert_draw

        if draw_exists(date):
            log(f"  Draw {date} already in database, skipping insert.")
        else:
            new_id = insert_draw(date, numbers, bonus, pb)
            if new_id is None:
                log("  ERROR: insert_draw failed — aborting downstream actions.")
                return False
            log(f"  Inserted as draw_id {new_id}")

    # 2) Backfill predictions + update scorecards
    if dry_run:
        log("  [DRY-RUN] would call accuracy_tracker.on_new_draw_fetched()")
    else:
        try:
            import accuracy_tracker

            result = accuracy_tracker.on_new_draw_fetched(date, numbers, bonus)
            log(
                f"  Scorecards updated: {result['scorecards_updated']}, "
                f"predictions backfilled: {result['backfilled_predictions']}, "
                f"hot predictor: {result['hot_predictor_20']}"
            )
        except Exception as e:
            log(f"  WARNING: accuracy_tracker failed (non-fatal): {e}")

    # 3) Check wheels and alert on wins
    summary: list[dict[str, Any]] = []
    try:
        from lotto_wheels import check_all_wheels

        wheel_results = check_all_wheels(tuple(numbers), pb, bonus, date)
        winners = [r for r in wheel_results if r.get("Winning Tickets", 0) > 0]
        summary = [
            {
                "wheel_name": r["Wheel"],
                "division": r.get("Division Breakdown", "?"),
                "matches": 0,
                "bonus_match": False,
                "ticket_count": r["Winning Tickets"],
                "prize_estimate": r.get("Total Prize", 0.0),
            }
            for r in winners
        ]
        if dry_run:
            log(f"  [DRY-RUN] would notify: {len(winners)} wheel(s) with wins")
            for r in winners:
                log(
                    f"    - {r['Wheel']}: {r['Winning Tickets']} winner(s), "
                    f"~${r.get('Total Prize', 0):,.2f}"
                )
        else:
            import notifier

            notifier.notify_draw_results(date, numbers, bonus, pb, summary)
            if winners:
                total = sum(r.get("Total Prize", 0.0) for r in winners)
                notifier.send_alert(
                    f"Lotto win detected: {date}",
                    f"{len(winners)} wheel(s) won ~${total:,.2f} total.\n"
                    f"Numbers: {nums_str} | Bonus {bonus:02d} | PB {pb}",
                )
            log(f"  Notifications sent ({len(winners)} winning wheel(s)).")
    except Exception as e:
        log(f"  WARNING: wheel check/notification failed (non-fatal): {e}")

    # 4) Broadcast to WebSocket clients via the API (skipped in dry-run)
    if dry_run:
        log("  [DRY-RUN] would publish draw event to API/WebSocket clients")
    else:
        publish_draw_event(draw, winners=summary, source="live_draw_monitor")

    return True


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------


def run_monitor(
    dry_run: bool = False, once: bool = False, interval: int = POLL_INTERVAL
) -> None:
    """Poll during draw windows; detect, validate and process new draws."""
    mode = "DRY-RUN" if dry_run else "LIVE"
    log(f"=== Live draw monitor starting ({mode}, interval {interval}s) ===")
    if not SELENIUM_AVAILABLE:
        log("Selenium not installed — OCR path disabled; will use HTML/API.")
    if OCR_ENGINE is None and not EASYOCR_AVAILABLE:
        log("No OCR engine installed — OCR path disabled (pip install pytesseract).")

    driver = None
    ocr_failures = 0
    use_fallback = not SELENIUM_AVAILABLE

    try:
        while True:
            if not once and not in_draw_window():
                wait = min(seconds_until_window(), 3600)
                log(f"Outside draw window; sleeping {wait / 60:.0f} min.")
                time.sleep(wait)
                continue

            latest = get_latest_db_draw()
            latest_date = latest["draw_date"] if latest else None
            log(f"Polling... (latest DB draw: {latest_date})")

            draw: dict[str, Any] | None = None

            # --- OCR path (early detection) ---
            if not use_fallback:
                try:
                    if driver is None:
                        driver = _get_driver(headless=True)
                        if driver is None:
                            raise RuntimeError("Could not start Chrome driver.")
                    ocr_result = poll_once_ocr(driver)
                    ocr_failures = 0
                    log(
                        f"  OCR detected: {ocr_result['numbers']} "
                        f"+ bonus {ocr_result['bonus']}"
                    )

                    # Enrich with canonical date/powerball from the API
                    api_draw = fetch_via_api()
                    if api_draw:
                        draw = api_draw
                        if sorted(api_draw["numbers"]) != sorted(ocr_result["numbers"]):
                            log(
                                "  WARNING: OCR numbers differ from API — "
                                "trusting the API."
                            )
                    else:
                        # API not updated yet — trust OCR, use today's date
                        draw = {
                            "draw_date": nz_now().strftime("%Y-%m-%d"),
                            "numbers": ocr_result["numbers"],
                            "bonus": ocr_result["bonus"],
                            "powerball": ocr_result["powerball"],
                        }
                except Exception as e:
                    ocr_failures += 1
                    log(
                        f"  OCR attempt failed ({ocr_failures}/"
                        f"{OCR_MAX_FAILURES}): {e}"
                    )
                    if ocr_failures >= OCR_MAX_FAILURES:
                        log(
                            "  OCR failed 3 times in a row — "
                            "falling back to HTML scraping."
                        )
                        use_fallback = True

            # --- Fallback path: HTML scrape, then official API ---
            if draw is None and use_fallback:
                draw = fetch_via_html_scraper() or fetch_via_api()

            # --- New draw? ---
            if draw and draw.get("draw_date") != latest_date:
                process_new_draw(draw, dry_run=dry_run)
            elif draw:
                log(f"  Draw {draw['draw_date']} already known.")
            else:
                log("  No result available yet.")

            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        log("Monitor stopped by user.")
    finally:
        if driver is not None:
            with contextlib.suppress(Exception):
                driver.quit()
        log("=== Live draw monitor stopped ===")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor NZ Lotto live draws (OCR + fallbacks)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without writing to the database.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle and exit (ignores the draw window).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=POLL_INTERVAL,
        help=f"Poll interval in seconds (default {POLL_INTERVAL}).",
    )
    args = parser.parse_args()
    run_monitor(dry_run=args.dry_run, once=args.once, interval=args.interval)


if __name__ == "__main__":
    main()
