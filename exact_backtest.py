#!/usr/bin/env python3
"""Exact per-draw backtest using real prize values from API for draws 2512-2616."""

import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

DB_PATH = Path.cwd() / "data" / "lotto.db"
API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}


def fetch_draw_payouts(draw_num: int):
    """Return dict of {division: prize_per_winner} for a specific draw, or None."""
    url = f"{API_BASE}/{draw_num}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        lotto = data.get("lotto", {})
        winners = lotto.get("lottoWinners", [])
        payouts = {}
        for entry in winners:
            div = entry.get("division")
            prize_str = entry.get("prizeValue", "0")
            if div == 7:
                payouts[div] = 0.70  # Bonus ticket
            else:
                try:
                    payouts[div] = float(prize_str)
                except ValueError:
                    payouts[div] = 0.0
        return payouts
    except Exception:
        return None


def parse_ticket_line(line: str):
    parts = line.strip().split()
    if not parts:
        return None, None
    numbers = []
    powerball = None
    i = 0
    while i < len(parts):
        token = parts[i]
        if token.upper().startswith("PB:"):
            powerball = int(token.split(":")[1])
            i += 1
        elif token.isdigit():
            numbers.append(int(token))
            i += 1
        else:
            i += 1
    if len(numbers) != 6:
        return None, None
    return tuple(sorted(numbers)), powerball


def load_wheel(filepath: Path):
    tickets = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            nums, pb = parse_ticket_line(line)
            if nums is not None:
                tickets.append((nums, pb))
    return tickets


def score_ticket(ticket_nums, drawn_set, bonus):
    main_matches = len(set(ticket_nums) & drawn_set)
    bonus_matched = bonus in ticket_nums
    if main_matches == 6:
        return 1
    elif main_matches == 5 and bonus_matched:
        return 2
    elif main_matches == 5:
        return 3
    elif main_matches == 4 and bonus_matched:
        return 4
    elif main_matches == 4:
        return 5
    elif main_matches == 3 and bonus_matched:
        return 6
    elif main_matches == 3:
        return 7
    return None


def backtest_exact(tickets, draw_payouts):
    """draw_payouts: dict of {draw_number: {div: prize}}"""
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    # Only backtest draws where we have payout data
    placeholders = ",".join("?" * len(draw_payouts))
    rows = conn.execute(
        f"SELECT draw_number, draw_date, numbers, bonus, powerball FROM draws "
        f"WHERE draw_number IN ({placeholders})",
        tuple(draw_payouts.keys()),
    ).fetchall()
    conn.close()

    total_draws = len(rows)
    total_spend = len(tickets) * 0.70 * total_draws
    total_winnings = 0.0
    draws_with_win = 0
    prize_counts = defaultdict(int)

    for draw_num, _, nums_str, bonus, _ in rows:
        drawn_set = {int(x) for x in nums_str.split(",")}
        payouts = draw_payouts[draw_num]
        draw_won = False

        for ticket_nums, _ in tickets:
            div = score_ticket(ticket_nums, drawn_set, bonus)
            if div is not None:
                draw_won = True
                prize_counts[div] += 1
                total_winnings += payouts.get(div, 0.0)

        if draw_won:
            draws_with_win += 1

    roi = (total_winnings - total_spend) / total_spend if total_spend > 0 else 0.0
    return {
        "draws": total_draws,
        "tickets": len(tickets),
        "winning_draws": draws_with_win,
        "hit_rate": draws_with_win / total_draws if total_draws else 0,
        "total_wins": sum(prize_counts.values()),
        "prize_counts": dict(prize_counts),
        "total_spend": total_spend,
        "total_winnings": total_winnings,
        "roi": roi,
    }


def main():
    # Fetch payout data for all recent draws
    print("Fetching exact payout data for draws 2512-2616...")
    draw_payouts = {}
    for num in range(2512, 2617):
        payouts = fetch_draw_payouts(num)
        if payouts:
            draw_payouts[num] = payouts
        time.sleep(0.15)
    print(f"Loaded payout data for {len(draw_payouts)} draws.\n")

    if not draw_payouts:
        print("No payout data available.")
        return 1

    files = sorted(Path.cwd().glob("wheel_*.txt")) + sorted(Path.cwd().glob("key_wheel_*.txt"))
    if not files:
        print("No wheel files found.")
        return 1

    print("=" * 95)
    print(
        f"{'Wheel File':<22} {'Draws':>6} {'Tickets':>8} {'Hit Rate':>9} {'Wins':>6} "
        f"{'Spend':>10} {'Winnings':>10} {'ROI':>8}"
    )
    print("-" * 95)

    results = []
    for f in files:
        tickets = load_wheel(f)
        if not tickets:
            continue
        res = backtest_exact(tickets, draw_payouts)
        results.append((f.name, res))
        print(
            f"{f.name:<22} {res['draws']:>6} {res['tickets']:>8} {res['hit_rate']*100:>8.2f}% "
            f"{res['total_wins']:>6} ${res['total_spend']:>10,.0f} ${res['total_winnings']:>10,.0f} "
            f"{res['roi']*100:>7.1f}%"
        )

    print("=" * 95)

    print("\nDetailed prize counts (exact per-draw values):")
    for name, res in results:
        print(f"\n{name}:")
        for div in range(1, 8):
            count = res["prize_counts"].get(div, 0)
            print(f"  Division {div}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
