#!/usr/bin/env python3
"""
block_analysis.py — Emil Albert's positional block analysis for NZ Lotto 6/40.

Analyses the 6 positional slots (1st through 6th, sorted ascending) over a
sliding window of historical draws to compute optimal bucket ranges and
validate whether candidate tickets conform to positional expectations.

Buckets: (1-10), (11-20), (21-30), (31-40).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

BUCKETS: list[tuple[int, int]] = [(1, 10), (11, 20), (21, 30), (31, 40)]


def _bucket_index(value: int) -> int:
    """Return the 0-based bucket index for a number (1-40)."""
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= value <= hi:
            return i
    return -1


def _bucket_label(idx: int) -> str:
    """Return human-readable label for a bucket index."""
    lo, hi = BUCKETS[idx]
    return f"{lo}-{hi}"


def compute_block_ranges(
    draws: list[tuple[list[int], int, int, str]], window_draws: int = 30
) -> dict[str, dict[str, Any]]:
    """Compute positional block statistics from historical draws.

    For each position (1st to 6th, sorted ascending), computes which bucket
    (1-10, 11-20, 21-30, 31-40) the number most frequently falls into, along
    with the full distribution across all 4 buckets.

    Parameters
    ----------
    draws : list
        Draw tuples in the format returned by lotto_wheels.load_draws():
        [(numbers_list, powerball, bonus, date), ...]
    window_draws : int
        Number of most-recent draws to analyse (default 30).

    Returns
    -------
    dict
        Keys per position (0-5):
          - optimal_bucket: bucket index (0-3)
          - optimal_label: e.g. "11-20"
          - confidence: fraction of draws in optimal bucket
          - bucket_distribution: {label: count, ...}
    """
    if not draws:
        return {}

    recent = draws[-window_draws:] if len(draws) > window_draws else draws
    n = len(recent)

    # Accumulate: positions[slot][bucket] = count
    positions: list[Counter[int]] = [Counter() for _ in range(6)]

    for nums, _, _, _ in recent:
        sorted_nums = sorted(nums)
        for slot in range(6):
            val = sorted_nums[slot]
            b_idx = _bucket_index(val)
            if b_idx >= 0:
                positions[slot][b_idx] += 1

    result: dict[str, dict[str, Any]] = {}
    for slot in range(6):
        total = sum(positions[slot].values())
        if total == 0:
            continue
        optimal_idx, optimal_count = positions[slot].most_common(1)[0]
        confidence = optimal_count / n

        dist = {}
        for b_idx in range(4):
            label = _bucket_label(b_idx)
            dist[label] = positions[slot].get(b_idx, 0)

        result[str(slot)] = {
            "position": slot + 1,
            "optimal_bucket": optimal_idx,
            "optimal_label": _bucket_label(optimal_idx),
            "confidence": round(confidence, 4),
            "bucket_distribution": dist,
        }

    return result


def validate_positional_ranges(
    ticket: list[int],
    block_ranges: dict[str, dict[str, Any]],
    min_positions: int = 4,
) -> bool:
    """Check whether a ticket satisfies positional block expectations.

    A position "matches" if the sorted number at that slot falls into the
    optimal bucket identified by `compute_block_ranges`.

    Parameters
    ----------
    ticket : list[int]
        6 sorted main numbers.
    block_ranges : dict
        Output from `compute_block_ranges`.
    min_positions : int
        Minimum number of positions that must match (default 4).

    Returns
    -------
    bool
        True if at least min_positions slots match their optimal bucket.
    """
    if not block_ranges or len(ticket) != 6:
        return False

    matches = 0
    for slot in range(min(6, len(ticket))):
        key = str(slot)
        if key not in block_ranges:
            continue
        val = ticket[slot]
        optimal_bucket = block_ranges[key]["optimal_bucket"]
        if _bucket_index(val) == optimal_bucket:
            matches += 1

    return matches >= min_positions


def build_position_heatmap_data(
    draws: list[tuple[list[int], int, int, str]], window_draws: int = 30
) -> tuple[list[Any], list[Any], list[Any]]:
    """Build data for a positional block heatmap.

    Returns (z_data, x_labels, y_labels) suitable for plotly heatmap.
    z_data[i][j] = fraction of draws where position i's number falls in bucket j.
    """
    if not draws:
        return [], [], []

    recent = draws[-window_draws:] if len(draws) > window_draws else draws
    n = len(recent)

    positions = [[0] * 4 for _ in range(6)]
    for nums, _, _, _ in recent:
        sorted_nums = sorted(nums)
        for slot in range(6):
            b_idx = _bucket_index(sorted_nums[slot])
            if b_idx >= 0:
                positions[slot][b_idx] += 1

    z_data = [[positions[s][b] / n for b in range(4)] for s in range(6)]
    x_labels = [f"{lo}-{hi}" for lo, hi in BUCKETS]
    y_labels = [f"Pos {i+1}" for i in range(6)]
    return z_data, x_labels, y_labels
