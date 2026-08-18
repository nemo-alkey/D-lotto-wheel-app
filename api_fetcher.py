#!/usr/bin/env python3
"""
api_fetcher.py — Fetch international lottery results via the APIVerve API.

Supports lotteries like Powerball US, Mega Millions, EuroMillions, etc.
Returns normalised draw data for comparison or supplementary analysis.

API docs: https://docs.apiverve.com/api/lottery

Usage:
    from api_fetcher import fetch_apiverve_lottery
    draw = fetch_apiverve_lottery("YOUR_API_KEY", "powerball")
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

API_BASE = "https://api.apiverve.com/v1/lottery"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
RETRY_DELAYS = [1, 2, 4]


def fetch_apiverve_lottery(
    api_key: str | None = None,
    lottery_name: str = "powerball",
) -> dict[str, Any] | None:
    """Fetch lottery results from APIVerve API.

    Parameters
    ----------
    api_key : str or None
        APIVerve API key. If None, reads from APIVERVE_API_KEY env var.
    lottery_name : str
        Lottery name slug (e.g. 'powerball', 'mega-millions', 'euromillions').

    Returns
    -------
    dict or None
        Normalised: draw_date, main_numbers (list[6 ints]), bonus_ball,
        powerball, source ('APIVerve'). Returns None on failure.
    """
    if api_key is None:
        api_key = os.environ.get("APIVERVE_API_KEY", "")
    if not api_key:
        print("APIVerve API key not configured. Set APIVERVE_API_KEY env var.")
        return None

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    params = {
        "lottery": lottery_name,
    }

    for attempt, delay in enumerate(RETRY_DELAYS, 1):
        try:
            resp = session.get(
                API_BASE,
                params=params,
                headers={"x-api-key": api_key},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # APIVerve response structure varies; adapt here
            if data.get("status") != "ok" and not data.get("data"):
                print(f"  API returned non-ok status: {data.get('message', 'unknown')}")
                return None

            result = data.get("data", data)

            # Extract fields
            draw_date = (
                result.get("drawDate") or result.get("draw_date") or result.get("date") or ""
            )
            numbers_raw = (
                result.get("numbers")
                or result.get("mainNumbers")
                or result.get("winningNumbers")
                or []
            )
            bonus_raw = result.get("bonusBall") or result.get("bonus") or 0
            pb_raw = result.get("powerball") or result.get("powerBall") or 0

            # Normalise numbers to list of ints
            if isinstance(numbers_raw, str):
                numbers = [int(x.strip()) for x in numbers_raw.split(",") if x.strip().isdigit()]
            elif isinstance(numbers_raw, list):
                numbers = [int(n) for n in numbers_raw]
            else:
                numbers = []

            bonus = int(bonus_raw) if bonus_raw and str(bonus_raw).isdigit() else 0
            powerball = int(pb_raw) if pb_raw and str(pb_raw).isdigit() else 0

            return {
                "draw_date": draw_date,
                "main_numbers": numbers,
                "bonus_ball": bonus if 1 <= bonus <= 99 else None,
                "powerball": powerball if 1 <= powerball <= 99 else None,
                "source": "APIVerve",
            }

        except requests.ConnectionError as e:
            print(f"  Connection error (attempt {attempt}): {e}")
            if attempt < len(RETRY_DELAYS):
                time.sleep(delay)
        except requests.Timeout as e:
            print(f"  Timeout (attempt {attempt}): {e}")
            if attempt < len(RETRY_DELAYS):
                time.sleep(delay)
        except requests.HTTPError as e:
            print(f"  HTTP error: {e}")
            return None
        except (ValueError, KeyError, TypeError) as e:
            print(f"  Parse error: {e}")
            return None

    print("  All retries exhausted.")
    return None


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch lottery results via APIVerve.")
    parser.add_argument("--lottery", default="powerball", help="Lottery name")
    parser.add_argument("--api-key", default=None, help="API key (or set APIVERVE_API_KEY env var)")
    args = parser.parse_args()

    print(f"Fetching {args.lottery} from APIVerve...")
    result = fetch_apiverve_lottery(args.api_key, args.lottery)
    if result:
        print(f"  Date:      {result['draw_date']}")
        print(f"  Numbers:   {result['main_numbers']}")
        print(f"  Bonus:     {result['bonus_ball']}")
        print(f"  Powerball: {result['powerball']}")
        print(f"  Source:    {result['source']}")
    else:
        print("  Failed to fetch results.")
