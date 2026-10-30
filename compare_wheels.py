#!/usr/bin/env python3
"""Compare multiple wheel files by backtesting against full history."""

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.cwd() / "data" / "lotto.db"

# Rough average payouts for each division (NZ Lotteries official average)
PAYOUTS = {
    "6": 400000,  # average jackpot (varies, use a placeholder)
    "5+bonus": 20000,
    "5": 600,
    "4+bonus": 100,
    "4": 60,
    "3+bonus": 25,
    "3": 20,
}


def parse_ticket_line(line: str):
    """Parse a line like '  1  2 16 22 27 33  PB:1' -> (numbers, powerball)"""
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


def backtest(tickets):
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    rows = conn.execute(
        "SELECT draw_number, draw_date, numbers, bonus, powerball FROM draws"
    ).fetchall()
    conn.close()

    prize_counts = defaultdict(int)
    draws_with_win = 0
    total_draws = len(rows)

    for _, _, nums_str, bonus, _powerball in rows:
        drawn_set = {int(x) for x in nums_str.split(",")}
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

            # Count each prize category occurrence (not just best)
            if main_matches == 6:
                prize_counts["6"] += 1
            elif main_matches == 5 and bonus_matched:
                prize_counts["5+bonus"] += 1
            elif main_matches == 5:
                prize_counts["5"] += 1
            elif main_matches == 4 and bonus_matched:
                prize_counts["4+bonus"] += 1
            elif main_matches == 4:
                prize_counts["4"] += 1
            elif main_matches == 3 and bonus_matched:
                prize_counts["3+bonus"] += 1
            elif main_matches == 3:
                prize_counts["3"] += 1

        if max_main >= 3:
            draws_with_win += 1

    total_wins = sum(prize_counts.values())
    total_spend = len(tickets) * 0.70 * total_draws
    est_winnings = sum(count * PAYOUTS[cat] for cat, count in prize_counts.items())

    return {
        "tickets": len(tickets),
        "draws": total_draws,
        "winning_draws": draws_with_win,
        "hit_rate": draws_with_win / total_draws,
        "total_wins": total_wins,
        "prize_counts": dict(prize_counts),
        "total_spend": total_spend,
        "est_winnings": est_winnings,
        "roi": (est_winnings - total_spend) / total_spend,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare wheel backtests")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="List of wheel files to compare (default: all wheel_*.txt and key_wheel_*.txt)",
    )
    args = parser.parse_args()

    if args.files:
        files = [Path(f) for f in args.files]
    else:
        files = sorted(Path.cwd().glob("wheel_*.txt")) + sorted(Path.cwd().glob("key_wheel_*.txt"))

    if not files:
        print("No wheel files found.")
        return 1

    print("=" * 80)
    print(
        f"{'Wheel File':<20} {'Tickets':>7} {'Hit Rate':>9} {'Total Wins':>10} {'Spend':>10} {'Est Winnings':>12} {'ROI':>8}"
    )
    print("-" * 80)

    results = []
    for f in files:
        tickets = load_wheel(f)
        if not tickets:
            continue
        res = backtest(tickets)
        results.append((f.name, res))
        print(
            f"{f.name:<20} {res['tickets']:>7} {res['hit_rate']*100:>8.2f}% {res['total_wins']:>10} "
            f"${res['total_spend']:>10,.0f} ${res['est_winnings']:>12,.0f} {res['roi']*100:>7.1f}%"
        )

    print("=" * 80)
    print("\nDetailed prize counts (across all draws):")
    for name, res in results:
        print(f"\n{name}:")
        for cat in ["6", "5+bonus", "5", "4+bonus", "4", "3+bonus", "3"]:
            count = res["prize_counts"].get(cat, 0)
            print(f"  {cat:8s}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
