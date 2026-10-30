"""Frequency, hot/cold, odd/even, sum ranges, co-occurrence.

Prompts #8 and #13. Read-only.
"""

from __future__ import annotations

import statistics
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import main_number_draws, section  # noqa: E402


def main() -> int:
    draws = main_number_draws()
    print(f"Loaded {len(draws)} draws")
    if not draws:
        return 1

    # ---- Frequency ----
    section("Main number frequency (1-40)")
    counts: Counter = Counter()
    for d in draws:
        for n in d["numbers"]:
            counts[n] += 1
    total = sum(counts.values())
    expected = total / 40
    ranked = sorted(range(1, 41), key=lambda n: -counts.get(n, 0))

    print(f"{'Rank':>4}  {'Num':>4}  {'Count':>6}  {'Delta':>8}  {'%':>6}")
    print("-" * 36)
    for rank, n in enumerate(ranked, 1):
        c = counts.get(n, 0)
        print(f"{rank:>4}  {n:>4}  {c:>6}  {c - expected:>+8.1f}  " f"{100 * c / total:>5.2f}%")

    print()
    print(f"Hot 5:   {ranked[:5]}")
    print(f"Cold 5:  {ranked[-5:]}")

    # ---- Overdue ----
    section("Overdue numbers (draws since last appearance)")
    last_seen = {n: -1 for n in range(1, 41)}
    for i, d in enumerate(draws):
        for n in d["numbers"]:
            last_seen[n] = i
    gap = {n: len(draws) - 1 - last_seen[n] for n in range(1, 41)}
    overdue = sorted(range(1, 41), key=lambda n: -gap[n])
    print(f"{'Num':>4}  {'Draws since':>12}")
    print("-" * 20)
    for n in overdue[:10]:
        print(f"{n:>4}  {gap[n]:>12}")

    # ---- Odd/even ----
    section("Odd/even distribution")
    odd_counts: Counter = Counter()
    for d in draws:
        odd_counts[sum(1 for n in d["numbers"] if n % 2 == 1)] += 1
    print(f"{'Odds':>4}  {'Draws':>6}  {'%':>7}")
    print("-" * 22)
    for k in range(7):
        c = odd_counts.get(k, 0)
        print(f"{k:>4}  {c:>6}  {100 * c / len(draws):>6.1f}%")

    # ---- High/low ----
    section("High/low split (low 1-20, high 21-40)")
    high_counts: Counter = Counter()
    for d in draws:
        high_counts[sum(1 for n in d["numbers"] if n > 20)] += 1
    print(f"{'High':>4}  {'Draws':>6}  {'%':>7}")
    print("-" * 22)
    for k in range(7):
        c = high_counts.get(k, 0)
        print(f"{k:>4}  {c:>6}  {100 * c / len(draws):>6.1f}%")

    # ---- Sum ranges ----
    section("Sum range distribution")
    sums = [sum(d["numbers"]) for d in draws]
    print(f"Min:     {min(sums)}")
    print(f"Max:     {max(sums)}")
    print(f"Mean:    {statistics.mean(sums):.1f}")
    print(f"Median:  {statistics.median(sums):.1f}")
    print(f"Stdev:   {statistics.stdev(sums):.1f}")
    print()
    buckets = [(0, 60), (60, 90), (90, 120), (120, 150), (150, 180), (180, 210), (210, 250)]
    print(f"{'Range':>11}  {'Draws':>6}  {'%':>7}")
    print("-" * 28)
    for lo, hi in buckets:
        c = sum(1 for s in sums if lo <= s < hi)
        print(f"{lo:>4}-{hi:<5}  {c:>6}  {100 * c / len(sums):>6.1f}%")

    # ---- Consecutive pairs ----
    section("Consecutive-number pairs per draw")
    consec: Counter = Counter()
    for d in draws:
        pairs = sum(
            1 for i in range(len(d["numbers"]) - 1) if d["numbers"][i + 1] - d["numbers"][i] == 1
        )
        consec[pairs] += 1
    print(f"{'Pairs':>5}  {'Draws':>6}  {'%':>7}")
    print("-" * 22)
    for k in range(6):
        c = consec.get(k, 0)
        print(f"{k:>5}  {c:>6}  {100 * c / len(draws):>6.1f}%")

    # ---- Co-occurrence ----
    section("Top 15 co-occurring number pairs")
    pair_counts: Counter = Counter()
    for d in draws:
        for a, b in combinations(sorted(d["numbers"]), 2):
            pair_counts[(a, b)] += 1
    print(f"{'Pair':>10}  {'Count':>6}")
    print("-" * 20)
    for (a, b), c in pair_counts.most_common(15):
        print(f"{a:>4}, {b:<4}  {c:>6}")

    section("Interpretation")
    print("""
Frequency, hot/cold, and overdue stats describe the past. They do NOT
predict future draws: each draw is an independent event.

Useful for:

  - Sanity: confirming uniform behaviour over long history.
  - Design: knowing the typical distribution of sums, odd/even splits,
    and consecutive pairs, so a chosen set can be evaluated against it.
  - Split-risk: co-occurrence shows historical pair trends; if a line
    matches common patterns, it may be more likely to be split.

A "hot" number is only interesting if the chi-square test rejects
uniformity. Under a fair machine, individual variations are noise.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
