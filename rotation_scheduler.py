#!/usr/bin/env python3
"""
rotation_scheduler.py -- 6-Week Rotation Planner for NZ Lotto Powerball

Loads historical draws from lotto_working.db, computes Bayesian posterior
probabilities (Dirichlet-Multinomial) for numbers 1-40, and generates a
6-week rotation plan. Each week's 11-number set swaps out the weakest
number and brings in the next-best from the Bayesian ranking.

Outputs a terminal table and saves to rotation_plan.csv.
"""

import csv
import math
import os
import sqlite3
import sys
from collections import Counter

WORKING_DB = "lotto_working.db"
WEEKS = 6
POOL_SIZE = 11
DEFAULT_PB = 3
ALPHA = 1.0  # Dirichlet prior concentration


# ---------------------------------------------------------------------------
# 1. Load draws
# ---------------------------------------------------------------------------

def load_draws(db_path: str = WORKING_DB) -> list[tuple]:
    """Return list of (numbers_tuple, powerball, date) from the DB."""
    if not os.path.exists(db_path):
        print(f"Error: database '{db_path}' not found.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT draw_date, n1, n2, n3, n4, n5, n6, powerball "
        "FROM draws ORDER BY draw_date"
    ).fetchall()
    conn.close()

    draws = []
    for r in rows:
        nums = (r["n1"], r["n2"], r["n3"], r["n4"], r["n5"], r["n6"])
        draws.append((nums, r["powerball"], r["draw_date"]))
    return draws


# ---------------------------------------------------------------------------
# 2. Bayesian posterior probabilities
# ---------------------------------------------------------------------------

def bayesian_posterior(draws: list[tuple], alpha: float = ALPHA) -> dict[int, float]:
    """Dirichlet-Multinomial posterior P(number) for 1-40.

    Posterior mean:  (count_i + alpha) / (total + 40 * alpha)
    """
    counts: Counter[int] = Counter()
    for nums, _pb, _date in draws:
        for n in nums:
            counts[n] += 1

    total = sum(counts.values())
    posterior: dict[int, float] = {}
    for n in range(1, 41):
        posterior[n] = (counts.get(n, 0) + alpha) / (total + 40 * alpha)
    return posterior


# ---------------------------------------------------------------------------
# 3. Rotation schedule
# ---------------------------------------------------------------------------

def build_rotation(posterior: dict[int, float]) -> list[list[int]]:
    """Generate 6 weeks of 11-number pools.

    Week 1 gets the top 11 by Bayesian score.
    Each subsequent week swaps out the lowest-scoring number in the pool
    and brings in the next-best from the remaining candidates.
    """
    # All numbers ranked by posterior probability (descending)
    ranked = sorted(range(1, 41), key=lambda n: -posterior[n])

    week1 = set(ranked[:POOL_SIZE])
    remaining = ranked[POOL_SIZE:]  # numbers not yet used
    next_idx = 0

    schedule = [sorted(week1)]

    for week in range(2, WEEKS + 1):
        current = set(schedule[-1])
        if next_idx < len(remaining):
            # Find the worst-ranked number in the current pool
            # (lowest Bayesian score among current members)
            worst = min(current, key=lambda n: posterior[n])
            current.remove(worst)
            current.add(remaining[next_idx])
            next_idx += 1
        schedule.append(sorted(current))

    return schedule


# ---------------------------------------------------------------------------
# 4. Output
# ---------------------------------------------------------------------------

def print_plan(schedule: list[list[int]], posterior: dict[int, float]) -> None:
    """Print the rotation plan as a formatted table."""
    print()
    print("  Bayesian Rotation Plan (6 weeks) -- NZ Lotto Powerball")
    print("  Recommended Powerball: {}".format(DEFAULT_PB))
    print()
    print(f"  {'Week':>6s}  {'Numbers (11 per week)':^49s}  {'Weakest':>7s}  {'Incoming':>8s}")
    print(f"  {'-'*74}")

    previous_set: set[int] | None = None
    for i, week_nums in enumerate(schedule, 1):
        nums_str = "  ".join(f"{n:02d}" for n in week_nums)
        current_set = set(week_nums)

        weakest = ""
        incoming = ""
        if previous_set is not None:
            dropped = previous_set - current_set
            added = current_set - previous_set
            if dropped:
                weakest = f"out {min(dropped):02d}"
            if added:
                incoming = f"in {min(added):02d}"

        print(f"  Week {i:>1d}    {nums_str}    {weakest:>7s}  {incoming:>8s}")
        previous_set = current_set

    print()

    # Show the full ranking for reference
    ranked = sorted(range(1, 41), key=lambda n: -posterior[n])
    bars = []
    max_prob = posterior[ranked[0]] if ranked else 1
    for n in ranked[:20]:
        pct = posterior[n] / max_prob
        bar_len = round(pct * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        prob_str = f"{posterior[n]:.6f}"
        bars.append(f"    #{n:02d}  {bar}  {prob_str}")

    print(f"  Top 20 Bayesian probabilities:")
    print(f"  {'-'*52}")
    for line in bars:
        print(line)
    print()


def save_plan(schedule: list[list[int]], path: str = "rotation_plan.csv") -> None:
    """Save the rotation plan to a CSV file."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Week", "Number_1", "Number_2", "Number_3", "Number_4",
                          "Number_5", "Number_6", "Number_7", "Number_8",
                          "Number_9", "Number_10", "Number_11", "Powerball"])
        for i, week_nums in enumerate(schedule, 1):
            writer.writerow([i, *week_nums, DEFAULT_PB])
    print(f"  Saved rotation plan to {path}")


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("  Loading draws...", end=" ", flush=True)
    draws = load_draws()
    print(f"{len(draws)} draws loaded.")

    print("  Computing Bayesian posteriors...", end=" ", flush=True)
    posterior = bayesian_posterior(draws)
    print("done.")
    print(f"  Draws used:      {len(draws)}")
    print(f"  Pool size:       {POOL_SIZE} numbers per week")
    print(f"  Rotation weeks:  {WEEKS}")
    print(f"  Prior alpha:     {ALPHA}")

    schedule = build_rotation(posterior)
    print_plan(schedule, posterior)
    save_plan(schedule)


if __name__ == "__main__":
    main()
