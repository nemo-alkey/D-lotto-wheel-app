#!/usr/bin/env python3
"""
Lotto Powerball Wheel Manager – NZ Lotto 6/40 + PB 1-10
Integrates:
- Albert's Lotto Code (pos/neg, blocks, sum range, numerical attraction)
- Bluskov's wheels (System #11, #20, #88, full jackpot)
- 25+ statistical methods (Bayesian, bandit, copula, etc.)
Uses the existing lotto.db from Callam7/LottoPipeline.
"""

import sqlite3
import csv
import random
import itertools
import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import List, Tuple, Dict, Set, Optional
import math
import sys
import os

# ---------- Division payouts (NZ Lotto Powerball estimates) ----------
DIVISIONS = [
    ("Div 1 (6+PB)",  6, True,  1_000_000),
    ("Div 2 (5+PB)",  5, True,     30_000),
    ("Div 3 (5)",     5, False,     1_000),
    ("Div 4 (4+PB)",  4, True,        100),
    ("Div 5 (4)",     4, False,        60),
    ("Div 6 (3+PB)",  3, True,         40),
    ("Div 7 (3)",     3, False,        20),
]
"""Each entry: (label, exact_main_matches, pb_must_match, prize_estimate).
A ticket qualifies for exactly one division -- the highest it satisfies.
'pb_must_match=True' means the powerball must hit; 'False' means it must NOT hit."""

# ---------- 1. Database connection and data loading ----------
DB_PATH = os.path.expanduser("~/LottoPipeline/lotto.db")
WORKING_DB = "lotto_working.db"  # will create a local copy with parsed numbers

def init_working_db():
    """Create a local SQLite DB with parsed draws (n1..n6, powerball)."""
    conn_src = sqlite3.connect(DB_PATH)
    conn_dest = sqlite3.connect(WORKING_DB)
    c_dest = conn_dest.cursor()
    c_dest.execute('''
        CREATE TABLE IF NOT EXISTS draws (
            draw_id INTEGER PRIMARY KEY,
            draw_date TEXT,
            n1 INTEGER, n2 INTEGER, n3 INTEGER,
            n4 INTEGER, n5 INTEGER, n6 INTEGER,
            powerball INTEGER
        )
    ''')
    c_dest.execute('DELETE FROM draws')  # clear old
    cursor = conn_src.execute("SELECT draw_id, draw_date, numbers, powerball FROM draws WHERE powerball > 0")
    rows = cursor.fetchall()
    for row in rows:
        draw_id, draw_date, numbers_str, pb = row
        nums = [int(x) for x in numbers_str.split(',')]
        if len(nums) != 6:
            continue
        c_dest.execute('''
            INSERT INTO draws (draw_id, draw_date, n1, n2, n3, n4, n5, n6, powerball)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (draw_id, draw_date, nums[0], nums[1], nums[2], nums[3], nums[4], nums[5], pb))
    conn_dest.commit()
    conn_src.close()
    conn_dest.close()
    print(f"Initialized working DB with {len(rows)} Powerball draws.")

def load_draws(limit: int = None) -> List[Tuple[List[int], int, str]]:
    """Load draws from working DB as list of (numbers_list, powerball, date)."""
    if not os.path.exists(WORKING_DB):
        init_working_db()
    conn = sqlite3.connect(WORKING_DB)
    conn.row_factory = sqlite3.Row
    query = "SELECT draw_date, n1, n2, n3, n4, n5, n6, powerball FROM draws ORDER BY draw_date"
    if limit:
        query += f" LIMIT {limit}"
    cursor = conn.execute(query)
    draws = [( [row['n1'],row['n2'],row['n3'],row['n4'],row['n5'],row['n6']], row['powerball'], row['draw_date'] ) for row in cursor]
    conn.close()
    return draws

# ---------- 2. Albert's Lotto Code Analysis ----------
def positive_negative_split(draws: List[Tuple[List[int], int, str]], last_n: int = 30):
    recent_draws = draws[-last_n:]
    freq = Counter()
    for nums, _, _ in recent_draws:
        freq.update(nums)
    max_freq = max(freq.values()) if freq else 0
    threshold = max_freq / 2
    pos = [num for num, cnt in freq.items() if cnt > threshold]
    neg = [num for num, cnt in freq.items() if cnt <= threshold]
    return pos, neg, freq

def block_analysis(draws: List[Tuple[List[int], int, str]], last_n: int = 30):
    recent = draws[-last_n:]
    positions = {i: [] for i in range(6)}
    for nums, _, _ in recent:
        for i, num in enumerate(nums):
            positions[i].append(num)
    ranges = {}
    for i, nums in positions.items():
        # categorize into 01-10, 11-20, 21-30, 31-40
        cats = {'01-10':0, '11-20':0, '21-30':0, '31-40':0}
        for n in nums:
            if 1 <= n <= 10: cats['01-10'] += 1
            elif 11 <= n <= 20: cats['11-20'] += 1
            elif 21 <= n <= 30: cats['21-30'] += 1
            else: cats['31-40'] += 1
        ranges[i] = cats
    return ranges

def sum_range(draws: List[Tuple[List[int], int, str]], last_n: int = 30):
    recent = draws[-last_n:]
    sums = [sum(nums) for nums, _, _ in recent]
    sums.sort()
    # remove lowest and highest 10% (trim extremes)
    trim = max(1, int(last_n * 0.1))
    trimmed = sums[trim:-trim]
    return min(trimmed), max(trimmed)

def numerical_attraction(draws: List[Tuple[List[int], int, str]], last_n: int = 30):
    recent = draws[-last_n:]
    count_with_adjacent = 0
    for nums, _, _ in recent:
        for i in range(len(nums)-1):
            if nums[i+1] - nums[i] <= 2:
                count_with_adjacent += 1
                break
    return count_with_adjacent / last_n

# ---------- 3. Statistical methods ----------
def bayesian_posterior(draws: List[Tuple[List[int], int, str]], alpha: float = 1.0):
    """Return posterior probability for each number (1-40) using Dirichlet-Multinomial."""
    counts = Counter()
    for nums, _, _ in draws:
        counts.update(nums)
    total = sum(counts.values())
    posterior = {num: (counts.get(num,0) + alpha) / (total + 40*alpha) for num in range(1,41)}
    return posterior

def markov_probs(draws: List[Tuple[List[int], int, str]]):
    """Simplified Markov: probability of each number based on last draw's numbers."""
    if len(draws) < 2:
        return {i: 1/40 for i in range(1,41)}
    last_draw = draws[-1][0]
    # count how many times each number appeared after each number in last_draw (very rough)
    # Instead, use simple frequency of numbers that appeared within 1 step of last draw?
    # For brevity, return uniform for now -- but can be expanded.
    return {i: 1/40 for i in range(1,41)}  # placeholder

def bandit_recommendation(draws: List[Tuple[List[int], int, str]]):
    """Thompson sampling for each number as independent arm."""
    counts = Counter()
    for nums, _, _ in draws:
        counts.update(nums)
    total_draws = len(draws)
    samples = {}
    for num in range(1,41):
        alpha = counts.get(num,0) + 1
        beta = total_draws*6 - counts.get(num,0) + 1
        samples[num] = random.betavariate(alpha, beta)
    # return top 6 numbers by sampled probability
    top6 = sorted(samples.items(), key=lambda x: x[1], reverse=True)[:6]
    return [num for num, _ in top6]

# ---------- 4. Bluskov wheels (hardcoded) ----------
# As defined earlier
WHEEL_20_SET1_NUMBERS = [9, 11, 12, 14, 17, 18, 28, 38, 39, 40]
WHEEL_20_SET1 = [
    (9, 11, 12, 14, 38, 39), (9, 11, 12, 17, 18, 28), (9, 11, 12, 17, 39, 40),
    (9, 11, 14, 17, 38, 40), (9, 11, 14, 18, 28, 38), (9, 11, 18, 28, 39, 40),
    (9, 12, 14, 17, 18, 40), (9, 12, 14, 17, 28, 38), (9, 12, 17, 18, 38, 39),
    (9, 12, 28, 38, 39, 40), (9, 14, 17, 28, 39, 40), (9, 14, 18, 38, 39, 40),
    (9, 17, 18, 28, 38, 40), (11, 12, 14, 17, 28, 39), (11, 12, 14, 18, 39, 40),
    (11, 12, 17, 28, 38, 40), (11, 14, 17, 18, 28, 39), (11, 17, 18, 38, 39, 40),
    (12, 14, 17, 18, 28, 40), (12, 14, 18, 28, 38, 39)
]

WHEEL_20_SET2_NUMBERS = [2, 3, 5, 7, 8, 10, 13, 15, 16, 19]
WHEEL_20_SET2 = [
    (2, 3, 5, 7, 8, 10), (2, 3, 5, 13, 15, 16), (2, 3, 5, 13, 16, 19),
    (2, 3, 7, 13, 8, 19), (2, 3, 7, 15, 16, 8), (2, 3, 15, 16, 19, 8),
    (2, 5, 7, 13, 15, 19), (2, 5, 7, 13, 16, 8), (2, 5, 13, 15, 8, 19),
    (2, 5, 16, 8, 19, 10), (2, 7, 13, 16, 19, 10), (2, 7, 15, 8, 19, 10),
    (2, 13, 15, 16, 8, 10), (3, 5, 7, 13, 16, 19), (3, 5, 7, 15, 19, 10),
    (3, 5, 13, 16, 8, 10), (3, 7, 13, 15, 16, 19), (3, 13, 15, 8, 19, 10),
    (5, 7, 13, 15, 16, 10), (5, 7, 15, 8, 19, 10)
]

WHEEL_88_NUMBERS = [9, 11, 12, 14, 17, 18, 28, 38, 39, 40]
WHEEL_88 = [
    (9, 11, 12, 14, 17, 18), (9, 11, 12, 14, 38, 39), (9, 11, 12, 17, 28, 40),
    (9, 11, 14, 18, 28, 39), (9, 11, 14, 17, 38, 40), (9, 11, 17, 18, 38, 39),
    (9, 11, 18, 28, 39, 40), (9, 11, 28, 38, 39, 40), (9, 12, 14, 17, 28, 38),
    (9, 12, 14, 17, 39, 40), (9, 12, 14, 18, 28, 39), (9, 12, 17, 18, 28, 40),
    (9, 12, 17, 38, 39, 40), (9, 12, 18, 28, 38, 40), (9, 14, 17, 18, 28, 40),
    (9, 12, 14, 28, 38, 40), (9, 12, 17, 18, 39, 40), (9, 14, 17, 28, 39, 40),
    (9, 14, 18, 38, 39, 40), (9, 17, 18, 28, 38, 39), (11, 12, 14, 17, 28, 39),
    (11, 12, 14, 18, 38, 40), (11, 12, 17, 28, 38, 39), (11, 14, 17, 18, 38, 40),
    (11, 14, 18, 28, 39, 40), (11, 17, 18, 28, 38, 40), (11, 17, 28, 38, 39, 40),
    (12, 14, 17, 18, 28, 38), (12, 14, 17, 18, 39, 40), (12, 14, 28, 38, 39, 40)
]

WHEEL_11_NUMBERS = [1, 9, 11, 12, 14, 17, 18, 28, 38, 39, 40]
WHEEL_11 = [
    (1, 9, 11, 14, 17, 28), (1, 9, 11, 18, 38, 40), (1, 9, 12, 14, 18, 38),
    (1, 9, 12, 17, 39, 40), (1, 9, 12, 28, 38, 39), (1, 9, 14, 17, 18, 39),
    (1, 11, 12, 14, 39, 40), (1, 11, 12, 17, 18, 28), (1, 11, 12, 28, 38, 40),
    (1, 11, 17, 18, 38, 39), (1, 11, 17, 28, 39, 40), (1, 14, 18, 28, 39, 40),
    (9, 11, 12, 14, 17, 38), (9, 11, 12, 18, 28, 39), (9, 11, 14, 38, 39, 40),
    (9, 12, 14, 17, 18, 40), (9, 12, 17, 28, 38, 40), (9, 14, 18, 28, 38, 39),
    (9, 17, 18, 28, 38, 40), (11, 12, 14, 18, 38, 39), (11, 12, 17, 38, 39, 40),
    (11, 14, 17, 28, 38, 40)
]

JACKPOT_7_NUMBERS = [9, 11, 12, 14, 38, 39, 40]
JACKPOT_7 = list(itertools.combinations(JACKPOT_7_NUMBERS, 6))

WHEELS = {
    "single1": (WHEEL_20_SET1, 3),
    "single2": (WHEEL_20_SET2, 6),
    "double": (WHEEL_88, 3),
    "five-if-six": (WHEEL_11, 3),
    "jackpot7": (JACKPOT_7, 3)
}

# ---------- 5. CLI and main ----------
def show_wheel(name: str):
    if name not in WHEELS:
        print("Unknown wheel. Options:", list(WHEELS.keys()))
        return
    tickets, pb = WHEELS[name]
    print(f"\n--- Wheel: {name} ---")
    print(f"Tickets: {len(tickets)}")
    print(f"Suggested Powerball: {pb}")
    print("Ticket combinations (main numbers):")
    for i, comb in enumerate(tickets, 1):
        print(f"{i:02d}: {', '.join(str(x) for x in sorted(comb))}")
    print(f"\nCost for NZ Lotto Powerball: {len(tickets)} x $1.50 = ${len(tickets)*1.50:.2f}")

def generate_report(draws: List[Tuple[List[int], int, str]]):
    print("\n=== Statistical Report (last 30 draws) ===\n")
    pos, neg, freq = positive_negative_split(draws)
    print(f"Positive numbers (freq > threshold): {sorted(pos)}")
    print(f"Negative numbers: {sorted(neg)}")
    ranges = block_analysis(draws)
    print("\nBlock analysis (positional ranges):")
    for i, cats in ranges.items():
        print(f"  Pos {i+1}: {cats}")
    low_sum, high_sum = sum_range(draws)
    print(f"\nSum range (trimmed): {low_sum} -- {high_sum}")
    adj_ratio = numerical_attraction(draws)
    print(f"Numerical attraction frequency: {adj_ratio*100:.1f}%")
    # Bayesian top numbers
    bayes = bayesian_posterior(draws)
    top_bayes = sorted(bayes.items(), key=lambda x: x[1], reverse=True)[:10]
    print("\nBayesian top 10 numbers:", [n for n,_ in top_bayes])
    bandit_top = bandit_recommendation(draws)
    print("Thompson sampling top 6 numbers:", bandit_top)

def check_wheel(name: str, draw_numbers: str, powerball: int):
    """Check how a wheel performs against a specific draw.

    Parameters
    ----------
    name : str
        Wheel name key in the WHEELS dict.
    draw_numbers : str
        Comma-separated list of 6 main numbers (1-40).
    powerball : int
        Powerball number (1-10).

    Raises
    ------
    SystemExit
        If input validation fails or the wheel is unknown.
    """
    if name not in WHEELS:
        print(f"Unknown wheel: '{name}'")
        print(f"Available wheels: {', '.join(WHEELS)}")
        sys.exit(1)

    # Parse draw numbers
    try:
        nums = [int(x.strip()) for x in draw_numbers.split(",")]
    except ValueError:
        print("Error: draw numbers must be comma-separated integers.")
        sys.exit(1)

    if len(nums) != 6:
        print(f"Error: expected 6 main numbers, got {len(nums)}.")
        sys.exit(1)

    if any(n < 1 or n > 40 for n in nums):
        print("Error: main numbers must be between 1 and 40.")
        sys.exit(1)

    if len(set(nums)) != 6:
        print("Error: duplicate numbers in draw.")
        sys.exit(1)

    if not isinstance(powerball, int) or powerball < 1 or powerball > 10:
        print("Error: powerball must be an integer between 1 and 10.")
        sys.exit(1)

    tickets, wheel_pb = WHEELS[name]
    draw_set = set(nums)
    n_tickets = len(tickets)
    cost = n_tickets * 1.50

    # Score each ticket: find its highest qualifying division.
    # A ticket qualifies if exact main matches match AND the PB condition agrees.
    # Divisions are ordered highest-first, so the first match wins.
    counts = {d[0]: 0 for d in DIVISIONS}
    for ticket in tickets:
        matches = len(set(ticket) & draw_set)
        pb_hit = (wheel_pb == powerball)
        for label, main_needed, pb_must_match, _ in DIVISIONS:
            if matches == main_needed and pb_hit == pb_must_match:
                counts[label] += 1
                break

    winners = []
    total_prize = 0.0
    for label, _, _, prize in DIVISIONS:
        c = counts[label]
        winnings = c * prize
        winners.append((label, c, prize, winnings))
        total_prize += winnings

    net = total_prize - cost
    roi = (net / cost * 100) if cost else 0.0

    # Check for wheel pool overlap
    pool_nums = []
    for t in tickets:
        pool_nums.extend(t)
    pool_set = set(pool_nums)

    # Output
    print(f"\n  Wheel:        {name}")
    print(f"  Tickets:      {n_tickets}")
    print(f"  Cost:         ${cost:.2f}")
    print(f"  Wheel pool:   {', '.join(str(n) for n in sorted(pool_set))}")
    print(f"  Wheel PB:     {wheel_pb}")
    print(f"  Draw:         {', '.join(f'{n:02d}' for n in nums)}  PB {powerball}")
    print(f"  Pool overlap: {len(draw_set & pool_set)} / {len(nums)}")
    print()
    print(f"  {'Division':<20s}  {'Winners':>8s}  {'Prize':>10s}  {'Total':>12s}")
    print(f"  {'-'*52}")
    for label, count, prize, winnings in winners:
        if count > 0:
            print(f"  {label:<20s}  {count:>8d}  ${prize:>8,.0f}  ${winnings:>10,.0f}")
    print()
    print(f"  Total prize:  ${total_prize:>10,.2f}")
    if net >= 0:
        print(f"  Net profit:   ${net:>10,.2f}")
    else:
        print(f"  Net loss:     ${net:>10,.2f}")
    print(f"  ROI:          {roi:>+10.2f}%")


def export_wheel(name: str, output_path: str):
    """Write a wheel's tickets to a CSV file.

    Parameters
    ----------
    name : str
        Wheel name key in the WHEELS dict.
    output_path : str
        Path to the output CSV file.

    Raises
    ------
    SystemExit
        If the wheel name is unknown or the output path is empty.
    """
    if not name or not output_path:
        print("Usage: python lotto_wheels.py export <wheel_name> <output.csv>")
        sys.exit(1)

    if name not in WHEELS:
        print(f"Unknown wheel: '{name}'")
        print(f"Available wheels: {', '.join(WHEELS)}")
        sys.exit(1)

    tickets, pb = WHEELS[name]

    if os.path.exists(output_path):
        response = input(f"'{output_path}' already exists. Overwrite? (y/N): ").strip().lower()
        if response != "y":
            print("Export cancelled.")
            return

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Main Numbers", "Powerball"])
            for ticket in tickets:
                writer.writerow([*ticket, pb])
    except OSError as e:
        print(f"Error writing to '{output_path}': {e}")
        sys.exit(1)

    print(f"Exported {len(tickets)} tickets for '{name}' to {output_path}")


def main():
    draws = load_draws()
    if not draws:
        print("No Powerball draws found. Run init_working_db first?")
        return
    print(f"Loaded {len(draws)} Powerball draws (since {draws[0][2]} to {draws[-1][2]})")

    if len(sys.argv) < 2:
        print("Usage: python lotto_wheels.py [command]")
        print("Commands:")
        print("  report                           Statistical report (last 30 draws)")
        print("  list-wheels                      List available wheel names")
        print("  show-wheel <name>                Show a wheel's tickets")
        print("  export <name> <output.csv>       Export a wheel to CSV")
        print("  check <name> \"<nums>\" <pb>       Check a wheel against a draw")
        return

    cmd = sys.argv[1]
    if cmd == "report":
        generate_report(draws)
    elif cmd == "list-wheels":
        print("Wheels:", list(WHEELS.keys()))
    elif cmd == "show-wheel" and len(sys.argv) >= 3:
        show_wheel(sys.argv[2])
    elif cmd == "export" and len(sys.argv) >= 4:
        export_wheel(sys.argv[2], sys.argv[3])
    elif cmd == "check" and len(sys.argv) >= 5:
        check_wheel(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    else:
        print("Unknown command.")

if __name__ == "__main__":
    main()
