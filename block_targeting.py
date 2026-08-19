#!/usr/bin/env python3
"""
block_targeting.py — Emil Albert's block-specific hot zones.

Albert's original block definitions (NZ Lotto 6/40)
---------------------------------------------------
Albert splits the 40-number pool into five blocks of eight and observed
that within each block, recent hits cluster in a narrower "favored"
sub-range:

  - Block 1: numbers 1-8    (favors sub-range 0-9,  i.e. 1-9)
  - Block 2: numbers 9-16   (favors 7-15)
  - Block 3: numbers 17-24  (favors 16-23)
  - Block 4: numbers 25-32  (favors 24-31)
  - Block 5: numbers 33-40  (favors 30-36)

Note the favored sub-ranges deliberately CROSS block boundaries (e.g.
block 1 favors 1-9, which reaches into block 2) — they describe where the
weight of hits sits, not hard partitions. This module computes the hot
zone empirically from recent draws instead of hardcoding Albert's
sub-ranges: the contiguous 3-4 number run inside each block with the
highest hit count over the lookback window.

Usage:
    from block_targeting import (
        analyze_block_distribution, score_wheel_blocks,
        generate_block_constraints,
    )
"""

from __future__ import annotations

from collections import Counter
from typing import Any

# Albert's original blocks: block_id -> (block range, Albert's favored sub-range)
BLOCKS: dict[int, dict[str, tuple[int, int]]] = {
    1: {"range": (1, 8), "favored": (1, 9)},
    2: {"range": (9, 16), "favored": (7, 15)},
    3: {"range": (17, 24), "favored": (16, 23)},
    4: {"range": (25, 32), "favored": (24, 31)},
    5: {"range": (33, 40), "favored": (30, 36)},
}

DEFAULT_LOOKBACK = 30
_HOT_ZONE_SIZES = (4, 3)  # prefer the wider zone on ties


def block_of(number: int) -> int:
    """Return the block id (1-5) containing a number (1-40)."""
    for block_id, cfg in BLOCKS.items():
        lo, hi = cfg["range"]
        if lo <= number <= hi:
            return block_id
    raise ValueError(f"Number {number} is outside 1-40.")


def analyze_block_distribution(
    draws: list[list[int]], lookback: int = DEFAULT_LOOKBACK
) -> dict[int, dict[str, Any]]:
    """Analyze how draw numbers distribute across Albert's five blocks.

    For each block, counts how many drawn numbers fell into it over the
    last ``lookback`` draws and finds the hot zone: the contiguous sub-range
    of 3-4 numbers within the block that appeared most frequently.

    Args:
        draws: Draw history, each a list of 6 numbers (chronological).
        lookback: How many recent draws to analyze (default 30).

    Returns:
        {block_id: {"range", "albert_favored", "hot_zone", "frequency",
        "coverage_pct", "block_hits", "avg_per_draw", "number_freq"}}
        where frequency = hot-zone hits and coverage_pct = hot-zone hits as
        a percentage of the block's total hits.
    """
    recent = draws[-lookback:] if len(draws) > lookback else draws

    result: dict[int, dict[str, Any]] = {}
    for block_id, cfg in BLOCKS.items():
        lo, hi = cfg["range"]
        numbers = list(range(lo, hi + 1))

        freq: Counter[int] = Counter()
        for draw in recent:
            freq.update(n for n in draw if lo <= n <= hi)

        # Hot zone: contiguous run of 4 (fallback 3) numbers with max hits
        best_zone: list[int] = numbers[:3]
        best_hits = -1
        for size in _HOT_ZONE_SIZES:
            for start in range(0, len(numbers) - size + 1):
                zone = numbers[start : start + size]
                hits = sum(freq.get(n, 0) for n in zone)
                if hits > best_hits:
                    best_hits = hits
                    best_zone = zone
            if best_hits > 0:
                break  # found a non-empty zone at this size; don't shrink

        block_hits = sum(freq.get(n, 0) for n in numbers)
        result[block_id] = {
            "range": (lo, hi),
            "albert_favored": cfg["favored"],
            "hot_zone": best_zone,
            "frequency": best_hits if best_hits > 0 else 0,
            "coverage_pct": round(best_hits / block_hits * 100, 1) if block_hits else 0.0,
            "block_hits": block_hits,
            "avg_per_draw": round(block_hits / len(recent), 2) if recent else 0.0,
            "number_freq": {n: freq.get(n, 0) for n in numbers},
        }
    return result


def score_wheel_blocks(
    wheel: list[int], block_analysis: dict[int, dict[str, Any]]
) -> tuple[float, str]:
    """Score a wheel/ticket by how many numbers sit in their block's hot zone.

    Args:
        wheel: Numbers to score (a ticket or a pool).
        block_analysis: Output of analyze_block_distribution().

    Returns:
        (score, recommendation) — score is hot-zone hits / len(wheel) in
        0.0-1.0; the recommendation names the coldest uncovered block and
        suggests its two most frequent numbers.
    """
    if not wheel:
        return 0.0, "Empty wheel — nothing to score."

    hits = 0
    uncovered: list[int] = []  # block ids with no hot-zone hit
    for block_id, info in block_analysis.items():
        zone = set(info["hot_zone"])
        block_nums = [n for n in wheel if block_of(n) == block_id]
        if any(n in zone for n in block_nums):
            hits += sum(1 for n in block_nums if n in zone)
        else:
            uncovered.append(block_id)

    score = round(hits / len(wheel), 3)

    if not uncovered:
        return score, "Good coverage — every block's hot zone is represented."

    # Suggest the two most frequent numbers from the first uncovered block
    coldest = uncovered[0]
    freq = block_analysis[coldest]["number_freq"]
    suggestions = [n for n, _ in sorted(freq.items(), key=lambda x: -x[1])[:2]]
    sug_str = " or ".join(str(n) for n in suggestions)
    blocks_str = ", ".join(str(b) for b in uncovered)
    return score, (
        f"Block {coldest} is cold — consider adding {sug_str}."
        + (f" (Also uncovered: blocks {blocks_str}.)" if len(uncovered) > 1 else "")
    )


def generate_block_constraints(block_analysis: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Build wheel-generator constraints from a block analysis.

    Returns:
        - min_per_block: {block_id: int} — 1 per block, 2 for blocks whose
          average hits per draw are at or above the cross-block average.
        - preferred_numbers: flat list of all hot-zone numbers.
        - avoid_numbers: numbers that did not appear at all in the analyzed
          window (i.e., absent for the whole lookback period).
    """
    avgs = [info["avg_per_draw"] for info in block_analysis.values()]
    mean_avg = sum(avgs) / len(avgs) if avgs else 0.0

    min_per_block: dict[int, int] = {}
    preferred: list[int] = []
    avoid: list[int] = []

    for block_id, info in block_analysis.items():
        min_per_block[block_id] = 2 if info["avg_per_draw"] >= mean_avg else 1
        preferred.extend(info["hot_zone"])
        avoid.extend(n for n, c in info["number_freq"].items() if c == 0)

    return {
        "min_per_block": min_per_block,
        "preferred_numbers": sorted(set(preferred)),
        "avoid_numbers": sorted(avoid),
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    random.seed(7)

    # 30 synthetic draws biased toward 17-20 (block 3) and avoiding 33-40
    synthetic: list[list[int]] = []
    for _ in range(30):
        draw = {random.randint(17, 20), random.randint(17, 24)}
        while len(draw) < 6:
            draw.add(random.randint(1, 32))
        synthetic.append(sorted(draw))

    analysis = analyze_block_distribution(synthetic, lookback=30)
    print("Block analysis (30 synthetic draws):")
    for b, info in analysis.items():
        print(
            f"  Block {b} {info['range']}: hot_zone={info['hot_zone']} "
            f"freq={info['frequency']} coverage={info['coverage_pct']}% "
            f"avg/draw={info['avg_per_draw']}"
        )

    # The bias should surface in block 3
    assert analysis[3]["block_hits"] >= analysis[1]["block_hits"]
    assert set(analysis[3]["hot_zone"]) & {
        17,
        18,
        19,
        20,
    }, "hot zone should overlap the biased numbers"

    score, rec = score_wheel_blocks([2, 10, 18, 26, 34, 38], analysis)
    print(f"\nScore [2,10,18,26,34,38]: {score} — {rec}")
    assert 0.0 <= score <= 1.0

    constraints = generate_block_constraints(analysis)
    print("\nConstraints:")
    print(f"  min_per_block:     {constraints['min_per_block']}")
    print(f"  preferred_numbers: {constraints['preferred_numbers']}")
    print(f"  avoid_numbers:     {constraints['avoid_numbers']}")
    # Block 5 never appeared in the synthetic draws -> all of 33-40 avoided
    assert set(range(33, 41)) <= set(constraints["avoid_numbers"])
    assert constraints["preferred_numbers"]

    print("\nAll block_targeting self-tests passed.")
