#!/usr/bin/env python3
"""
Lotto Powerball Wheel Manager – NZ Lotto 6/40 + PB 1-10
Integrates:
- Albert's Lotto Code (pos/neg, blocks, sum range, numerical attraction)
- Bluskov's wheels (System #11, #20, #88, full jackpot)
- 25+ statistical methods (Bayesian, bandit, copula, etc.)
Uses the existing lotto.db from Callam7/LottoPipeline.
"""

import csv
import itertools
import math
import os
import random
import sys
from collections import Counter
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

# Use the unified database layer (SQLAlchemy, supports SQLite + PostgreSQL)
from database_engine import get_engine

# ---------- Division payouts (NZ Lotto Powerball estimates) ----------
DIVISIONS = [
    ("Div 1 (6+PB)", 6, True, 1_000_000),
    ("Div 2 (5+PB)", 5, True, 30_000),
    ("Div 3 (5)", 5, False, 1_000),
    ("Div 4 (4+PB)", 4, True, 100),
    ("Div 5 (4)", 4, False, 60),
    ("Div 6 (3+PB)", 3, True, 40),
    ("Div 7 (3)", 3, False, 20),
]
"""Each entry: (label, exact_main_matches, pb_must_match, prize_estimate).
A ticket qualifies for exactly one division -- the highest it satisfies.
'pb_must_match=True' means the powerball must hit; 'False' means it must NOT hit."""

# ---------- 1. Database connection and data loading ----------
DB_PATH = os.path.expanduser("~/LottoPipeline/lotto.db")
WORKING_DB = "lotto.db"  # unified: all components use lotto.db


def init_working_db() -> None:
    """Initialise the unified lotto.db schema if it doesn't exist."""
    from database import initialize_database

    initialize_database()


def load_draws(limit: int | None = None) -> list[tuple[list[int], int, int, str]]:
    """Load draws from the database as list of (numbers_list, powerball, bonus, date)."""
    engine = get_engine()
    with engine.connect() as conn:
        query = "SELECT draw_date, numbers, bonus, powerball FROM draws ORDER BY draw_date"
        params = {}
        if limit:
            query += " LIMIT :limit"
            params["limit"] = limit
        result = conn.execute(text(query), params)
        draws = []
        for row in result:
            draw_date, nums_str, bonus, powerball = row
            try:
                nums = [int(x.strip()) for x in nums_str.split(",")]
            except (ValueError, AttributeError):
                continue
            if len(nums) != 6:
                continue
            draws.append((nums, powerball, bonus or 0, draw_date))
        return draws


# ---------- 2. Albert's Lotto Code Analysis ----------
def positive_negative_split(
    draws: list[tuple[list[int], int, int, str]], last_n: int = 30
) -> tuple[list[int], list[int], Counter[int]]:
    recent_draws = draws[-last_n:]
    freq: Counter[int] = Counter()
    for nums, _, _, _ in recent_draws:
        freq.update(nums)
    max_freq = max(freq.values()) if freq else 0
    threshold = max_freq / 2
    pos = [num for num, cnt in freq.items() if cnt > threshold]
    neg = [num for num, cnt in freq.items() if cnt <= threshold]
    return pos, neg, freq


def block_analysis(
    draws: list[tuple[list[int], int, int, str]], last_n: int = 30
) -> dict[int, dict[str, int]]:
    recent = draws[-last_n:]
    positions: dict[int, list[int]] = {i: [] for i in range(6)}
    for nums, _, _, _ in recent:
        for i, num in enumerate(nums):
            positions[i].append(num)
    ranges = {}
    for i, nums in positions.items():
        # categorize into 01-10, 11-20, 21-30, 31-40
        cats = {"01-10": 0, "11-20": 0, "21-30": 0, "31-40": 0}
        for n in nums:
            if 1 <= n <= 10:
                cats["01-10"] += 1
            elif 11 <= n <= 20:
                cats["11-20"] += 1
            elif 21 <= n <= 30:
                cats["21-30"] += 1
            else:
                cats["31-40"] += 1
        ranges[i] = cats
    return ranges


def sum_range(draws: list[tuple[list[int], int, int, str]], last_n: int = 30) -> tuple[int, int]:
    recent = draws[-last_n:]
    sums = [sum(nums) for nums, _, _, _ in recent]
    sums.sort()
    # remove lowest and highest 10% (trim extremes)
    trim = max(1, int(last_n * 0.1))
    trimmed = sums[trim:-trim]
    return min(trimmed), max(trimmed)


def numerical_attraction(draws: list[tuple[list[int], int, int, str]], last_n: int = 30) -> float:
    recent = draws[-last_n:]
    count_with_adjacent = 0
    for nums, _, _, _ in recent:
        for i in range(len(nums) - 1):
            if nums[i + 1] - nums[i] <= 2:
                count_with_adjacent += 1
                break
    return count_with_adjacent / last_n


# ---------- 3. Statistical methods ----------
def bayesian_posterior(
    draws: list[tuple[list[int], int, int, str]], alpha: float = 1.0
) -> dict[int, float]:
    """Return posterior probability for each number (1-40) using Dirichlet-Multinomial."""
    counts: Counter[int] = Counter()
    for nums, _, _, _ in draws:
        counts.update(nums)
    total = sum(counts.values())
    posterior = {num: (counts.get(num, 0) + alpha) / (total + 40 * alpha) for num in range(1, 41)}
    return posterior


def markov_probs(draws: list[tuple[list[int], int, str]]) -> dict[int, float]:
    """Simplified Markov: probability of each number based on last draw's numbers."""
    if len(draws) < 2:
        return {i: 1 / 40 for i in range(1, 41)}
    # count how many times each number appeared after each number in last_draw (very rough)
    # Instead, use simple frequency of numbers that appeared within 1 step of last draw?
    # For brevity, return uniform for now -- but can be expanded.
    return {i: 1 / 40 for i in range(1, 41)}  # placeholder


def bandit_recommendation(draws: list[tuple[list[int], int, int, str]]) -> list[int]:
    """Thompson sampling for each number as independent arm."""
    counts: Counter[int] = Counter()
    for nums, _, _, _ in draws:
        counts.update(nums)
    total_draws = len(draws)
    samples = {}
    for num in range(1, 41):
        alpha = counts.get(num, 0) + 1
        beta = total_draws * 6 - counts.get(num, 0) + 1
        samples[num] = random.betavariate(alpha, beta)
    # return top 6 numbers by sampled probability
    top6 = sorted(samples.items(), key=lambda x: x[1], reverse=True)[:6]
    return [num for num, _ in top6]


def get_bonus_stats(
    conn: Any, start_date: str | None = None, end_date: str | None = None
) -> list[dict[str, Any]]:
    """Return list of dicts with bonus ball statistics for numbers 1-40.

    Each dict has: number, count, frequency, last_drawn, gap, z_score.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to a database with a 'draws' table.
    start_date : str or None
        Optional lower-bound date filter (inclusive, YYYY-MM-DD).
    end_date : str or None
        Optional upper-bound date filter (inclusive, YYYY-MM-DD).

    Returns
    -------
    list[dict]
    """
    conditions = []
    params = []
    if start_date:
        conditions.append("draw_date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("draw_date <= ?")
        params.append(end_date)
    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # Max draw_id in filtered range (for gap calculation)
    max_id_row = conn.execute(f"SELECT MAX(draw_id) FROM draws{where_clause}", params).fetchone()
    max_draw_id = max_id_row[0] if max_id_row and max_id_row[0] is not None else 0

    # Count, last date, last draw_id per bonus number
    query = f"""
        SELECT bonus, COUNT(*) AS cnt, MAX(draw_date) AS last_date, MAX(draw_id) AS last_id
        FROM draws{where_clause}
        GROUP BY bonus
        ORDER BY bonus
    """
    rows = conn.execute(query, params).fetchall()

    bonus_map = {row[0]: (row[1], row[2], row[3]) for row in rows}
    counts = [bonus_map.get(n, (0, None, 0))[0] for n in range(1, 41)]
    total = sum(counts)
    mean_val = total / 40.0 if total > 0 else 0.0
    std_val = math.sqrt(sum((c - mean_val) ** 2 for c in counts) / 40) if total > 0 else 0.0

    results = []
    for n in range(1, 41):
        cnt, last_date, last_id = bonus_map.get(n, (0, None, 0))
        freq_pct = (cnt / total * 100) if total > 0 else 0.0
        gap = (max_draw_id - last_id) if last_id and max_draw_id else None
        z = abs(cnt - mean_val) / std_val if std_val > 0 else 0.0
        results.append(
            {
                "number": n,
                "count": cnt,
                "frequency": round(freq_pct, 2),
                "last_drawn": last_date or "Never",
                "gap": gap if gap is not None else "N/A",
                "z_score": round(z, 2),
            }
        )
    return results


# ---------- 4. Bluskov wheels (hardcoded) ----------
# As defined earlier
WHEEL_20_SET1_NUMBERS = [9, 11, 12, 14, 17, 18, 28, 38, 39, 40]
WHEEL_20_SET1: list[tuple[int, ...]] = [
    (9, 11, 12, 14, 38, 39),
    (9, 11, 12, 17, 18, 28),
    (9, 11, 12, 17, 39, 40),
    (9, 11, 14, 17, 38, 40),
    (9, 11, 14, 18, 28, 38),
    (9, 11, 18, 28, 39, 40),
    (9, 12, 14, 17, 18, 40),
    (9, 12, 14, 17, 28, 38),
    (9, 12, 17, 18, 38, 39),
    (9, 12, 28, 38, 39, 40),
    (9, 14, 17, 28, 39, 40),
    (9, 14, 18, 38, 39, 40),
    (9, 17, 18, 28, 38, 40),
    (11, 12, 14, 17, 28, 39),
    (11, 12, 14, 18, 39, 40),
    (11, 12, 17, 28, 38, 40),
    (11, 14, 17, 18, 28, 39),
    (11, 17, 18, 38, 39, 40),
    (12, 14, 17, 18, 28, 40),
    (12, 14, 18, 28, 38, 39),
]

WHEEL_20_SET2_NUMBERS = [2, 3, 5, 7, 8, 10, 13, 15, 16, 19]
WHEEL_20_SET2: list[tuple[int, ...]] = [
    (2, 3, 5, 7, 8, 10),
    (2, 3, 5, 13, 15, 16),
    (2, 3, 5, 13, 16, 19),
    (2, 3, 7, 13, 8, 19),
    (2, 3, 7, 15, 16, 8),
    (2, 3, 15, 16, 19, 8),
    (2, 5, 7, 13, 15, 19),
    (2, 5, 7, 13, 16, 8),
    (2, 5, 13, 15, 8, 19),
    (2, 5, 16, 8, 19, 10),
    (2, 7, 13, 16, 19, 10),
    (2, 7, 15, 8, 19, 10),
    (2, 13, 15, 16, 8, 10),
    (3, 5, 7, 13, 16, 19),
    (3, 5, 7, 15, 19, 10),
    (3, 5, 13, 16, 8, 10),
    (3, 7, 13, 15, 16, 19),
    (3, 13, 15, 8, 19, 10),
    (5, 7, 13, 15, 16, 10),
    (5, 7, 15, 8, 19, 10),
]

WHEEL_88_NUMBERS = [9, 11, 12, 14, 17, 18, 28, 38, 39, 40]
WHEEL_88: list[tuple[int, ...]] = [
    (9, 11, 12, 14, 17, 18),
    (9, 11, 12, 14, 38, 39),
    (9, 11, 12, 17, 28, 40),
    (9, 11, 14, 18, 28, 39),
    (9, 11, 14, 17, 38, 40),
    (9, 11, 17, 18, 38, 39),
    (9, 11, 18, 28, 39, 40),
    (9, 11, 28, 38, 39, 40),
    (9, 12, 14, 17, 28, 38),
    (9, 12, 14, 17, 39, 40),
    (9, 12, 14, 18, 28, 39),
    (9, 12, 17, 18, 28, 40),
    (9, 12, 17, 38, 39, 40),
    (9, 12, 18, 28, 38, 40),
    (9, 14, 17, 18, 28, 40),
    (9, 12, 14, 28, 38, 40),
    (9, 12, 17, 18, 39, 40),
    (9, 14, 17, 28, 39, 40),
    (9, 14, 18, 38, 39, 40),
    (9, 17, 18, 28, 38, 39),
    (11, 12, 14, 17, 28, 39),
    (11, 12, 14, 18, 38, 40),
    (11, 12, 17, 28, 38, 39),
    (11, 14, 17, 18, 38, 40),
    (11, 14, 18, 28, 39, 40),
    (11, 17, 18, 28, 38, 40),
    (11, 17, 28, 38, 39, 40),
    (12, 14, 17, 18, 28, 38),
    (12, 14, 17, 18, 39, 40),
    (12, 14, 28, 38, 39, 40),
]

WHEEL_11_NUMBERS = [1, 9, 11, 12, 14, 17, 18, 28, 38, 39, 40]
WHEEL_11: list[tuple[int, ...]] = [
    (1, 9, 11, 14, 17, 28),
    (1, 9, 11, 18, 38, 40),
    (1, 9, 12, 14, 18, 38),
    (1, 9, 12, 17, 39, 40),
    (1, 9, 12, 28, 38, 39),
    (1, 9, 14, 17, 18, 39),
    (1, 11, 12, 14, 39, 40),
    (1, 11, 12, 17, 18, 28),
    (1, 11, 12, 28, 38, 40),
    (1, 11, 17, 18, 38, 39),
    (1, 11, 17, 28, 39, 40),
    (1, 14, 18, 28, 39, 40),
    (9, 11, 12, 14, 17, 38),
    (9, 11, 12, 18, 28, 39),
    (9, 11, 14, 38, 39, 40),
    (9, 12, 14, 17, 18, 40),
    (9, 12, 17, 28, 38, 40),
    (9, 14, 18, 28, 38, 39),
    (9, 17, 18, 28, 38, 40),
    (11, 12, 14, 18, 38, 39),
    (11, 12, 17, 38, 39, 40),
    (11, 14, 17, 28, 38, 40),
]

JACKPOT_7_NUMBERS = [9, 11, 12, 14, 38, 39, 40]
JACKPOT_7 = list(itertools.combinations(JACKPOT_7_NUMBERS, 6))

WHEELS: dict[str, tuple[list[tuple[int, ...]], int]] = {
    "single1": (WHEEL_20_SET1, 3),
    "single2": (WHEEL_20_SET2, 6),
    "double": (WHEEL_88, 3),
    "five-if-six": (WHEEL_11, 3),
    "jackpot7": (JACKPOT_7, 3),
}


def get_bonus_coverage(name: str) -> int:
    """Return bonus coverage (count of distinct main numbers) for a wheel.

    The bonus ball is drawn from 1-40 and any main number can appear as the
    bonus.  Higher coverage means more of your numbers are eligible for the
    bonus-upgrade divisions (Div 2/4/6).
    """
    if name not in WHEELS:
        return 0
    tickets, _ = WHEELS[name]
    all_nums: set[int] = set()
    for t in tickets:
        all_nums.update(t)
    return len(all_nums)


# ---------- 5. CLI and main ----------
def show_wheel(name: str) -> None:
    if name not in WHEELS:
        print("Unknown wheel. Options:", list(WHEELS.keys()))
        return
    tickets, pb = WHEELS[name]
    print(f"\n--- Wheel: {name}  (bonus coverage: {get_bonus_coverage(name)}) ---")
    print(f"Tickets: {len(tickets)}")
    print(f"Suggested Powerball: {pb}")
    print("Ticket combinations (main numbers):")
    for i, comb in enumerate(tickets, 1):
        print(f"{i:02d}: {', '.join(str(x) for x in sorted(comb))}")
    print(f"\nCost for NZ Lotto Powerball: {len(tickets)} x $1.50 = ${len(tickets)*1.50:.2f}")


def generate_report(draws: list[tuple[list[int], int, int, str]]) -> None:
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
    print("\nBayesian top 10 numbers:", [n for n, _ in top_bayes])
    bandit_top = bandit_recommendation(draws)
    print("Thompson sampling top 6 numbers:", bandit_top)


def check_wheel(name: str, draw_numbers: str, powerball: int) -> None:
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

    # Try to find this draw in the database to get real prize payouts
    draw_date = None
    draws = load_draws()
    sorted_nums = sorted(nums)
    for dn, dpb, _, ddate in draws:
        if sorted(dn) == sorted_nums and dpb == powerball:
            draw_date = ddate
            break

    # Fetch real prize amounts
    from prize_calculator import get_prize_for_matches

    try:
        # Get real prize lookup: (main_matches, pb_hit) -> total_prize
        real_prizes: dict[tuple[int, bool], float] = {}
        is_real = True
        for m in [6, 5, 4, 3]:
            for pb_hit in [True, False]:
                info = get_prize_for_matches(m, False, pb_hit, draw_date=draw_date)
                real_prizes[(m, pb_hit)] = info["total_prize"]
                if info["is_estimated"]:
                    is_real = False
    except Exception:
        real_prizes = {}
        is_real = False

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
        pb_hit = wheel_pb == powerball
        for label, main_needed, pb_must_match, _ in DIVISIONS:
            if matches == main_needed and pb_hit == pb_must_match:
                counts[label] += 1
                break

    winners = []
    total_prize = 0.0
    for label, main_needed, pb_must_match, static_prize in DIVISIONS:
        c = counts[label]
        # Use real prize if available, otherwise static estimate
        prize = real_prizes.get((main_needed, pb_must_match), static_prize)
        winnings = c * prize
        winners.append((label, c, prize, winnings))
        total_prize += winnings

    net = total_prize - cost
    roi = (net / cost * 100) if cost else 0.0

    # Check for wheel pool overlap
    pool_nums: list[int] = []
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
    prize_source = "live" if is_real and draw_date else "estimated"
    print(f"  Prizes:       {prize_source}{' (from ' + draw_date + ')' if draw_date else ''}")
    print()
    print(f"  {'Division':<20s}  {'Winners':>8s}  {'Prize':>10s}  {'Total':>12s}")
    print(f"  {'-'*52}")
    for label, count, prize, winnings in winners:
        if count > 0:
            suffix = " (live)" if is_real else " (est)"
            print(f"  {label:<20s}  {count:>8d}  ${prize:>8,.0f}{suffix}  ${winnings:>10,.0f}")
    print()
    print(f"  Total prize:  ${total_prize:>10,.2f}")
    if net >= 0:
        print(f"  Net profit:   ${net:>10,.2f}")
    else:
        print(f"  Net loss:     ${net:>10,.2f}")
    print(f"  ROI:          {roi:>+10.2f}%")


def check_all_wheels(
    draw_nums: list[int] | tuple[int, ...],
    draw_pb: int,
    draw_bonus: int,
    draw_date: str,
    bonus_matched: bool = False,
) -> list[dict[str, Any]]:
    """Check all 5 preset wheels against the given draw.

    Parameters
    ----------
    draw_nums : list[int] or tuple[int]
        6 main draw numbers (1-40).
    draw_pb : int
        Powerball number (1-10).
    draw_bonus : int
        Bonus ball number (1-40).
    draw_date : str
        Draw date string (YYYY-MM-DD) for live prize lookups.
    bonus_matched : bool
        If True, the draw's bonus ball is treated as matched for all tickets,
        triggering Div 2/4/6 upgrades (marked with * in division labels).

    Returns
    -------
    list[dict]
        Each dict: Wheel, Tickets, Pool, Pool Overlap, Wheel PB,
        Winning Tickets, Total Prize, Division Breakdown.
    """
    from prize_calculator import get_prize_for_matches, resolve_divisions

    def _div_label(lotto_div: int | None, pb_hit: bool, upgraded: bool) -> str:
        labels = {
            1: "Div 1 (6)",
            2: "Div 2 (5+bonus)",
            3: "Div 3 (5)",
            4: "Div 4 (4+bonus)",
            5: "Div 5 (4)",
            6: "Div 6 (3+bonus)",
            7: "Div 7 (3)",
        }
        base = labels.get(lotto_div if lotto_div is not None else 0, f"Div {lotto_div}")
        if pb_hit:
            base += "+PB"
        if upgraded:
            base += "*"
        return base

    draw_set = set(draw_nums)
    results = []
    for name in ["single1", "single2", "double", "five-if-six", "jackpot7"]:
        tickets, wheel_pb = WHEELS[name]
        pool: set[int] = set()
        for t in tickets:
            pool.update(t)
        pool_overlap = len(draw_set & pool)
        pb_hit = wheel_pb == draw_pb

        winning_tickets = 0
        total_prize = 0.0
        div_hits: dict[str, int] = {}

        for ticket in tickets:
            matches = len(set(ticket) & draw_set)
            ticket_bonus = (draw_bonus in set(ticket)) if bonus_matched else False

            lotto_div, _ = resolve_divisions(matches, ticket_bonus, pb_hit)

            if lotto_div is not None:
                winning_tickets += 1
                try:
                    info = get_prize_for_matches(matches, ticket_bonus, pb_hit, draw_date=draw_date)
                    prize = info["total_prize"]
                except Exception:
                    fb = {1: 1_000_000, 2: 30_000, 3: 1_000, 4: 100, 5: 60, 6: 40, 7: 20}
                    prize = fb.get(lotto_div, 0)
                total_prize += prize

                upgraded = ticket_bonus and lotto_div in (2, 4, 6)
                label = _div_label(lotto_div, pb_hit, upgraded)
                div_hits[label] = div_hits.get(label, 0) + 1

        results.append(
            {
                "Wheel": name,
                "Bonus Coverage": get_bonus_coverage(name),
                "Tickets": len(tickets),
                "Pool": len(pool),
                "Pool Overlap": f"{pool_overlap}/6",
                "Wheel PB": wheel_pb,
                "Winning Tickets": winning_tickets,
                "Total Prize": total_prize,
                "Division Breakdown": (
                    ", ".join(f"{k}: {v}" for k, v in sorted(div_hits.items()))
                    if div_hits
                    else "None"
                ),
            }
        )
    return results


def export_wheel(name: str, output_path: str, fmt: str = "standard") -> None:
    """Write a wheel's tickets to a CSV file.

    Parameters
    ----------
    name : str
        Wheel name key in the WHEELS dict.
    output_path : str
        Path to the output CSV file.
    fmt : str, optional
        Output format: "standard" (header + space-separated CSV) or
        "mylotto" (no header, comma-separated numbers, PB as 7th column).

    Raises
    ------
    SystemExit
        If the wheel name is unknown or the output path is empty.
    """
    if not name or not output_path:
        print("Usage: python lotto_wheels.py export <wheel_name> <output.csv> [--format mylotto]")
        sys.exit(1)

    if name not in WHEELS:
        print(f"Unknown wheel: '{name}'")
        print(f"Available wheels: {', '.join(WHEELS)}")
        sys.exit(1)

    if fmt not in ("standard", "mylotto"):
        print(f"Unknown format: '{fmt}' (use 'standard' or 'mylotto')")
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
            if fmt == "mylotto":
                # No header; numbers comma-separated, PB as 7th column
                for ticket in tickets:
                    writer.writerow([*ticket, pb])
            else:
                # Standard format: header row
                writer.writerow(["Main Numbers", "Powerball"])
                for ticket in tickets:
                    writer.writerow([*ticket, pb])
    except OSError as e:
        print(f"Error writing to '{output_path}': {e}")
        sys.exit(1)

    print(f"Exported {len(tickets)} tickets for '{name}' to {output_path}")


# ---------- 6. Predict Command ----------


def predict_cmd(
    draws: list[tuple[list[int], int, int, str]], weights: list[float] | None = None
) -> None:
    """Run 6 prediction methods + ensemble and display results."""
    from predictions import (
        bayesian,
        due_numbers,
        ensemble,
        frequency,
        markov,
        pattern,
        weighted_random,
    )

    method_list: list[tuple[str, Callable[..., Any]]] = [
        ("Frequency", frequency),
        ("Bayesian", bayesian),
        ("Markov", markov),
        ("Weighted Random", weighted_random),
        ("Due Numbers", due_numbers),
        ("Pattern", pattern),
    ]

    print()
    print("  === Individual Predictions (Top 3) ===")
    print()
    for name, method in method_list:
        result = method(draws)
        top3 = result["numbers"][:3]
        print(
            f"  {name:<18s}  {', '.join(f'{n:02d}' for n in top3):>10s}  |  PB {result['powerball']}"
        )

    ensemble_result = ensemble(draws, weights)
    nums = ensemble_result["numbers"]
    pb = ensemble_result["powerball"]

    # Stats
    s = sum(nums)
    odd = sum(1 for n in nums if n % 2 == 1)
    even = 6 - odd

    pos, neg, _ = positive_negative_split(draws)
    n_pos = sum(1 for n in nums if n in set(pos))
    n_neg = 6 - n_pos

    adj_ratio = numerical_attraction(draws)
    has_adj = any(nums[i + 1] - nums[i] <= 2 for i in range(len(nums) - 1))
    low_sum, high_sum = sum_range(draws)

    print()
    print("  === Ensemble Prediction ===")
    print(f"  Numbers:    {', '.join(f'{n:02d}' for n in nums)}  |  PB {pb}")
    print(f"  Sum:        {s}  (range {low_sum}–{high_sum})")
    print(f"  Pos/Neg:    {n_pos:>2d}+ / {n_neg:>2d}-")
    print(f"  Odd/Even:   {odd}o / {even}e")
    print(f"  Adjacent:   {'Yes' if has_adj else 'No'}")
    print(f"  Num Attr:   {adj_ratio*100:.1f}% of recent draws have adjacent pairs")
    print()


# ---------- 7. Lucky Dip ----------


def lucky_dip(draws: list[tuple[list[int], int, int, str]]) -> None:
    """Generate a single random ticket respecting constraints from the last 30 draws.

    Constraints:
      - >= 4 numbers from Positive pool, <= 2 from Negative pool
      - Sum within trimmed min/max of recent draws
      - >= 1 adjacent or diff-by-2 pair
      - 3o+3e, 4o+2e, or 2o+4e
      - Powerball from top 3 most frequent in last 30 draws

    If no ticket satisfies all constraints after 1000 attempts, constraints
    are gradually relaxed stage by stage.
    """
    if len(draws) == 0:
        nums = sorted(random.sample(range(1, 41), 6))
        pb = random.randint(1, 10)
        _print_dip(nums, pb, None)
        return

    recent = draws[-30:] if len(draws) >= 30 else draws

    # ---- constraint data ----
    pos, neg, _ = positive_negative_split(draws)
    pos_pool = set(pos)
    neg_pool = {n for n in range(1, 41) if n not in pos_pool}

    low_sum, high_sum = sum_range(draws)

    # Powerball top 3
    pb_counts = Counter(pb for _, pb, _, _ in recent)
    top3_pbs = [pb for pb, _ in pb_counts.most_common(3)]
    if not top3_pbs:
        top3_pbs = list(range(1, 11))

    best = None

    for attempt in range(5000):
        # ---- relaxation stages ----
        # 0–999:   all constraints
        # 1000–1999: relax pos/neg
        # 2000–2999: + widen sum range
        # 3000–3999: + relax odd/even
        # 4000–4999: + relax adjacency

        relax_pn = attempt >= 1000
        relax_sum = attempt >= 2000
        relax_oe = attempt >= 3000
        relax_adj = attempt >= 4000

        # -- Powerball (always from top 3) --
        pb = random.choice(top3_pbs)

        # -- Main numbers --
        if not relax_pn:
            n_pos = random.randint(4, min(6, len(pos_pool)))
            n_neg = 6 - n_pos
            if n_pos > len(pos_pool) or n_neg > len(neg_pool):
                continue
            pos_sample = random.sample(list(pos_pool), n_pos)
            neg_sample = random.sample(list(neg_pool), n_neg)
            nums = sorted(pos_sample + neg_sample)
        else:
            nums = sorted(random.sample(range(1, 41), 6))

        # -- Sum range --
        s = sum(nums)
        if not relax_sum:
            if not (low_sum <= s <= high_sum):
                continue
        else:
            margin = int((high_sum - low_sum) * 0.3) + 1
            if not (low_sum - margin <= s <= high_sum + margin):
                continue

        # -- Odd/even --
        odd = sum(1 for n in nums if n % 2 == 1)
        if not relax_oe and odd not in (2, 3, 4):
            continue

        # -- Adjacent or diff-by-2 pair --
        if not relax_adj:
            has_pair = any(nums[i + 1] - nums[i] <= 2 for i in range(len(nums) - 1))
            if not has_pair:
                continue

        best = (nums, pb)
        break

    # Absolute fallback
    if best is None:
        nums = sorted(random.sample(range(1, 41), 6))
        pb = random.randint(1, 10)
        best = (nums, pb)
        n_pos = sum(1 for n in nums if n in pos_pool)
        n_neg = 6 - n_pos

    nums, pb = best
    n_pos = sum(1 for n in nums if n in pos_pool)
    n_neg = 6 - n_pos
    _print_dip(nums, pb, (low_sum, high_sum), n_pos, n_neg)


def _print_dip(
    nums: list[int], pb: int, sum_range: tuple[int, int] | None, n_pos: int = 0, n_neg: int = 0
) -> None:
    """Print a lucky-dip ticket and its statistics."""
    s = sum(nums)
    odd = sum(1 for n in nums if n % 2 == 1)
    even = 6 - odd
    has_adj = any(nums[i + 1] - nums[i] <= 2 for i in range(len(nums) - 1))
    adj_pairs = sum(1 for i in range(len(nums) - 1) if nums[i + 1] - nums[i] <= 2)

    print()
    print("  Lucky Dip:")
    print(f"  Numbers:    {', '.join(f'{n:02d}' for n in nums)}  |  PB {pb}")
    print(f"  Sum:        {s}" + (f"  (range {sum_range[0]}–{sum_range[1]})" if sum_range else ""))
    print(f"  Pos/Neg:    {n_pos:>2d}+ / {n_neg:>2d}-")
    print(f"  Odd/Even:   {odd}o / {even}e")
    print(
        f"  Adjacent:   {'Yes' if has_adj else 'No'}"
        + (f"  ({adj_pairs} pair{'s' if adj_pairs != 1 else ''})" if has_adj else "")
    )


def main() -> None:
    draws = load_draws()
    if not draws:
        print("No Powerball draws found. Run init_working_db first?")
        return
    print(f"Loaded {len(draws)} Powerball draws (since {draws[0][3]} to {draws[-1][3]})")

    if len(sys.argv) < 2:
        print("Usage: python lotto_wheels.py [command]")
        print("Commands:")
        print("  report                           Statistical report (last 30 draws)")
        print("  list-wheels                      List available wheel names")
        print("  show-wheel <name>                Show a wheel's tickets")
        print("  export <name> <output.csv>       Export a wheel to CSV")
        print("    --format mylotto               No header, numbers comma-sep, PB 7th col")
        print('  check <name> "<nums>" <pb>       Check a wheel against a draw')
        print("  lucky-dip                        Generate a random ticket with constraints")
        print("  predict [--weights w1..w6]       Ensemble prediction (6 methods + weighted vote)")
        print("  print-pdf <name> [output.pdf]    Generate A4 PDF playslip for a wheel")

    cmd = sys.argv[1]
    if cmd == "report":
        generate_report(draws)
    elif cmd == "list-wheels":
        print("Wheels:", list(WHEELS.keys()))
    elif cmd == "show-wheel" and len(sys.argv) >= 3:
        show_wheel(sys.argv[2])
    elif cmd == "export" and len(sys.argv) >= 4:
        # Parse optional --format flag from the remaining args
        rest = sys.argv[2:]
        fmt = "standard"
        if "--format" in rest:
            idx = rest.index("--format")
            if idx + 1 < len(rest):
                fmt = rest.pop(idx + 1)
            rest.pop(idx)
        if len(rest) >= 2:
            export_wheel(rest[0], rest[1], fmt)
        else:
            print(
                "Usage: python lotto_wheels.py export <wheel_name> <output.csv> [--format mylotto]"
            )
    elif cmd == "check" and len(sys.argv) >= 5:
        check_wheel(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    elif cmd == "lucky-dip":
        lucky_dip(draws)
    elif cmd == "predict":
        rest = sys.argv[2:]
        weights = None
        if "--weights" in rest:
            idx = rest.index("--weights")
            if idx + 1 < len(rest):
                try:
                    weights = [float(w) for w in rest[idx + 1].split(",")]
                except ValueError:
                    print("Error: --weights must be comma-separated floats")
                    sys.exit(1)
                if len(weights) != 6:
                    print("Error: --weights expects exactly 6 values (one per method)")
                    sys.exit(1)
        predict_cmd(draws, weights)
    elif cmd == "print-pdf":
        from print_wheel import build_pdf

        if len(sys.argv) >= 3:
            name = sys.argv[2]
            out = sys.argv[3] if len(sys.argv) >= 4 else "wheel_playslip.pdf"
            build_pdf(name, out)
        else:
            print("Usage: python lotto_wheels.py print-pdf <wheel_name> [output.pdf]")
            print(f"  wheel_name: {', '.join(WHEELS)}")
    else:
        print("Unknown command.")


if __name__ == "__main__":
    main()
