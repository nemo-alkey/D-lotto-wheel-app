#!/usr/bin/env python3
"""Refined backtest using actual recent payout averages from Lotto NZ API."""

import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

DB_PATH = Path.cwd() / "data" / "lotto.db"
API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

# Range of draws with full payout data in the API (based on earlier investigation)
FIRST_DRAW_WITH_DATA = 2512
LAST_DRAW_WITH_DATA = 2616   # will adjust dynamically if needed


def fetch_payout_averages():
    """Fetch recent draws and compute average prize value per division."""
    print("Fetching payout data from API...")
    sums = defaultdict(float)
    counts = defaultdict(int)

    for num in range(FIRST_DRAW_WITH_DATA, LAST_DRAW_WITH_DATA + 1):
        url = f"{API_BASE}/{num}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            lotto = data.get("lotto", {})
            winners = lotto.get("lottoWinners", [])
            for entry in winners:
                div = entry.get("division")
                prize_str = entry.get("prizeValue", "0")
                if div == 7:
                    # Bonus ticket
                    prize = 0.70
                else:
                    try:
                        prize = float(prize_str)
                    except ValueError:
                        prize = 0.0
                sums[div] += prize
                counts[div] += 1
        except Exception:
            pass
        time.sleep(0.2)  # gentle rate limit

    averages = {}
    for div in range(1, 8):
        if counts[div] > 0:
            averages[div] = sums[div] / counts[div]
        else:
            averages[div] = 0.0

    print("Average prize values per division (recent draws):")
    for div in range(1, 8):
        print(f"  Division {div}: ${averages[div]:.2f}")
    return averages


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


def load_wheel(filepath):
    tickets = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            nums, pb = parse_ticket_line(line)
            if nums is not None:
                tickets.append((nums, pb))
    return tickets


def backtest(tickets, averages):
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    rows = conn.execute(
        "SELECT draw_number, draw_date, numbers, bonus, powerball FROM draws"
    ).fetchall()
    conn.close()

    prize_counts = defaultdict(int)
    draws_with_win = 0
    total_draws = len(rows)

    for _, _, nums_str, bonus, powerball in rows:
        drawn_set = set(int(x) for x in nums_str.split(','))
        max_main = 0
        best_bonus = False

        for ticket_nums, _ in tickets:
            main_matches = len(set(ticket_nums) & drawn_set)
            bonus_matched = bonus in ticket_nums

            if main_matches > max_main:
                max_main = main_matches
                best_bonus = bonus_matched
            elif main_matches == max_main:
                best_bonus = best_bonus or bonus_matched

            # Count prize categories using division mapping
            if main_matches == 6:
                prize_counts[1] += 1
            elif main_matches == 5 and bonus_matched:
                prize_counts[2] += 1
            elif main_matches == 5:
                prize_counts[3] += 1
            elif main_matches == 4 and bonus_matched:
                prize_counts[4] += 1
            elif main_matches == 4:
                prize_counts[5] += 1
            elif main_matches == 3 and bonus_matched:
                prize_counts[6] += 1
            elif main_matches == 3:
                prize_counts[7] += 1

        if max_main >= 3:
            draws_with_win += 1

    total_wins = sum(prize_counts.values())
    total_spend = len(tickets) * 0.70 * total_draws

    # Calculate winnings using average prizes per division
    est_winnings = 0.0
    for div, count in prize_counts.items():
        est_winnings += count * averages.get(div, 0.0)

    roi = (est_winnings - total_spend) / total_spend if total_spend > 0 else 0.0

    return {
        'tickets': len(tickets),
        'draws': total_draws,
        'winning_draws': draws_with_win,
        'hit_rate': draws_with_win / total_draws if total_draws else 0,
        'total_wins': total_wins,
        'prize_counts': dict(prize_counts),
        'total_spend': total_spend,
        'est_winnings': est_winnings,
        'roi': roi,
    }


def main():
    averages = fetch_payout_averages()

    # Find all wheel files
    files = sorted(Path.cwd().glob("wheel_*.txt")) + sorted(Path.cwd().glob("key_wheel_*.txt"))
    if not files:
        print("No wheel files found.")
        return 1

    print("\n" + "=" * 90)
    print(f"{'Wheel File':<20} {'Tickets':>7} {'Hit Rate':>9} {'Total Wins':>10} "
          f"{'Spend':>10} {'Est Winnings':>12} {'ROI':>8}")
    print("-" * 90)

    results = []
    for f in files:
        tickets = load_wheel(f)
        if not tickets:
            continue
        res = backtest(tickets, averages)
        results.append((f.name, res))
        print(f"{f.name:<20} {res['tickets']:>7} {res['hit_rate']*100:>8.2f}% {res['total_wins']:>10} "
              f"${res['total_spend']:>10,.0f} ${res['est_winnings']:>12,.0f} {res['roi']*100:>7.1f}%")

    print("=" * 90)

    # Show detailed prize counts
    print("\nDetailed prize counts (by division):")
    for name, res in results:
        print(f"\n{name}:")
        for div in range(1, 8):
            count = res['prize_counts'].get(div, 0)
            print(f"  Division {div}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())