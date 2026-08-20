#!/usr/bin/env python3
"""
scheduler.py — Background scheduler for NZ Lotto result checking and alerts.

Runs every Thursday 8am and Sunday 8am (after draws are published):
  1. Fetches latest draw results via the MyLotto API.
  2. Compares against stored ticket sets from the latest prediction run.
  3. Triggers email + desktop alerts if any ticket matches 4+ main numbers
     or has a bonus upgrade.

Usage:
    python scheduler.py                 # run once (foreground, for testing)
    python scheduler.py --daemon        # run as background scheduler
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, cast

TICKET_STORE = "latest_tickets.json"
CHECK_LOG = "scheduler_checks.log"


# ---------------------------------------------------------------------------
# Ticket loading
# ---------------------------------------------------------------------------


def load_stored_tickets() -> list[Any]:
    """Load the latest generated tickets from the ticket store."""
    if not os.path.exists(TICKET_STORE):
        return []
    with open(TICKET_STORE, encoding="utf-8") as f:
        data = json.load(f)
    return cast(list[Any], data.get("tickets", []))


def save_tickets(tickets: list[Any]) -> None:
    """Save a ticket list to the store."""
    with open(TICKET_STORE, "w", encoding="utf-8") as f:
        json.dump(
            {"tickets": tickets, "saved_at": datetime.now().isoformat()}, f, indent=2
        )


# ---------------------------------------------------------------------------
# Draw fetching
# ---------------------------------------------------------------------------


def fetch_latest_draw() -> dict[str, Any] | None:
    """Fetch the latest draw from the MyLotto API.

    Returns a dict with keys: draw_date, numbers (list[int]), bonus (int),
    powerball (int), or None on failure.
    """
    try:
        from prize_calculator import fetch_payouts

        payouts = fetch_payouts()
        if not payouts:
            return None

        # We have the draw date and prize data, but we also need the numbers.
        # Try the full API response.
        import requests

        api_url = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
        resp = requests.get(api_url, timeout=15)
        resp.raise_for_status()
        raw = resp.json()

        lotto = raw.get("lotto", {})
        nums_str = lotto.get("lottoWinningNumbers", "")
        bonus_num = lotto.get("bonusBall", 0)
        pb_num = raw.get("powerBall", {}).get("powerball", 0)
        draw_date = lotto.get("drawDate", payouts.get("draw_date", ""))

        # Parse winning numbers
        numbers = [int(x.strip()) for x in nums_str.split(",")] if nums_str else []

        return {
            "draw_date": draw_date,
            "numbers": numbers,
            "bonus": int(bonus_num) if bonus_num else 0,
            "powerball": int(pb_num) if pb_num else 0,
        }
    except Exception as exc:
        from notifier import log_alert

        log_alert(f"Draw fetch failed: {exc}", "ERROR")
        return None


# ---------------------------------------------------------------------------
# Ticket checking
# ---------------------------------------------------------------------------


def check_tickets(tickets: list[Any], draw: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare stored tickets against a draw and return winning matches.

    Returns list of dicts with keys: ticket_index, matches, bonus_match,
    divisions_hit.
    """
    if not draw or not draw.get("numbers"):
        return []

    draw_set = set(draw["numbers"])
    draw_bonus = draw.get("bonus", 0)
    winners = []

    for idx, ticket in enumerate(tickets):
        matches = len(set(ticket) & draw_set)
        bonus_match = draw_bonus > 0 and draw_bonus in set(ticket)

        if matches >= 4 or (matches == 3 and bonus_match):
            from prize_calculator import resolve_divisions

            lotto_div, pb_div = resolve_divisions(matches, bonus_match, False)
            winners.append(
                {
                    "ticket_index": idx,
                    "ticket": sorted(ticket),
                    "matches": matches,
                    "bonus_match": bonus_match,
                    "lotto_division": lotto_div,
                }
            )

    return winners


# ---------------------------------------------------------------------------
# Scheduler job
# ---------------------------------------------------------------------------


def check_job() -> None:
    """The scheduled job: fetch draw via pipeline, check tickets, alert on wins."""
    from data_pipeline import DataFetcher
    from notifier import log_alert, notify_draw_results

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CHECK_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] Running scheduled check...\n")

    # Use unified pipeline (API → HTML → Selenium fallback)
    fetcher = DataFetcher()
    result = fetcher.fetch_latest()

    # Convert pipeline result to draw dict format
    if result:
        draw = {
            "draw_date": result["draw_date"],
            "numbers": result["numbers"],
            "bonus": result.get("bonus", 0),
            "powerball": result.get("powerball", 0),
        }
    else:
        draw = None

    if not draw:
        log_alert("Scheduled check: could not fetch draw.", "WARN")
        with open(CHECK_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] FAILED: could not fetch draw\n")
        return

    tickets = load_stored_tickets()
    if not tickets:
        log_alert("Scheduled check: no stored tickets to compare.", "INFO")
        with open(CHECK_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] No tickets stored\n")
        return

    winners = check_tickets(tickets, draw)
    nums_str = ", ".join(str(n) for n in draw["numbers"])
    result_line = (
        f"[{ts}] Draw {draw['draw_date']}: {nums_str} | Bonus {draw['bonus']} | "
        f"PB {draw['powerball']} → {len(winners)} winning tickets"
    )

    with open(CHECK_LOG, "a", encoding="utf-8") as f:
        f.write(result_line + "\n")
    log_alert(
        f"Check complete: {len(winners)} winner(s) out of {len(tickets)} tickets.",
        "INFO",
    )

    # --- Build structured results summary for notify_draw_results ---
    if winners:
        results_summary = []
        for w in winners:
            results_summary.append(
                {
                    "wheel_name": "Stored Ticket",
                    "division": f"Div {w.get('lotto_division', '?')}",
                    "matches": w["matches"],
                    "bonus_match": w["bonus_match"],
                    "ticket_count": 1,
                    "prize_estimate": 0,
                }
            )

        notify_draw_results(
            draw_date=draw["draw_date"],
            numbers=draw["numbers"],
            bonus=draw["bonus"],
            pb=draw["powerball"],
            results_summary=results_summary,
        )

        # Also log to pipeline_stats
        try:
            from data_pipeline import DataFetcher

            fetcher._record_stat(
                source="scheduler",
                draw_date=draw["draw_date"],
                success=True,
                error=f"{len(winners)} winner(s)",
            )
        except Exception:
            pass  # non-critical


# ---------------------------------------------------------------------------
# Main / daemon
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Lotto Alert Scheduler")
    parser.add_argument(
        "--daemon", action="store_true", help="Run as background scheduler"
    )
    args = parser.parse_args()

    if args.daemon:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            scheduler = BackgroundScheduler()
            # Thursday 8am and Sunday 8am
            scheduler.add_job(
                check_job,
                "cron",
                day_of_week="thu,sun",
                hour=8,
                minute=0,
                id="lotto_check",
            )
            scheduler.start()
            print("Scheduler started. Checks run Thu/Sun at 8am. Press Ctrl+C to stop.")
            try:
                while True:
                    import time

                    time.sleep(60)
            except KeyboardInterrupt:
                scheduler.shutdown()
                print("Scheduler stopped.")
        except ImportError:
            print("APScheduler not installed. Install with: pip install apscheduler")
            sys.exit(1)
    else:
        # Run once for testing
        print("Running one-off check...")
        check_job()
        print("Check complete.")


if __name__ == "__main__":
    main()
