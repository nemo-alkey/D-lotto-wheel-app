#!/usr/bin/env python3
"""
compliance_scorer.py — Rate a wheel on adherence to Albert's Lotto Code principles.

Scores every ticket in a wheel across four dimensions and returns a weighted
composite score (0–100).  Higher = better compliance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# Buckets for block analysis
BUCKETS: list[tuple[int, int]] = [(1, 10), (11, 20), (21, 30), (31, 40)]


def _bucket_index(value: int) -> int:
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= value <= hi:
            return i
    return -1


def _has_adjacent(nums: Sequence[int]) -> bool:
    """Return True if any two numbers differ by 1 or 2."""
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if abs(nums[i] - nums[j]) <= 2:
                return True
    return False


def score_wheel(
    wheel_combinations: Sequence[Sequence[int]],
    albert_state: dict[str, Any],
) -> float:
    """Compute a 0-100 compliance score for a wheel.

    Parameters
    ----------
    wheel_combinations : list[list[int]]
        Each element is a 6-number ticket.
    albert_state : dict
        Output from albert_analysis.classify_numbers() or a dict with keys:
        - 'positive' (list[int])
        - 'negative' (list[int])
        - 'block_ranges' (dict from block_analysis.compute_block_ranges)
        - 'sum_range' (tuple[float, float] from sum_analysis.dynamic_sum_range)

    Returns
    -------
    float
        Weighted score 0–100.
    """
    if not wheel_combinations:
        return 0.0

    positive_set = set(albert_state.get("positive", []))
    negative_set = set(albert_state.get("negative", []))
    block_ranges = albert_state.get("block_ranges", {})
    sum_range = albert_state.get("sum_range")
    n = len(wheel_combinations)

    # --- 1. Positive/Negative Balance (40%) ---
    pos_neg_score = 0.0
    for ticket in wheel_combinations:
        pos_count = sum(1 for x in ticket if x in positive_set)
        neg_count = sum(1 for x in ticket if x in negative_set)
        # Ideal: 2-4 positive, 2-4 negative (at least 2 of each)
        if pos_count >= 2 and neg_count >= 2:
            pos_neg_score += 100.0
        elif pos_count >= 1 and neg_count >= 1:
            pos_neg_score += 50.0
        else:
            pos_neg_score += 0.0
    pos_neg_score /= n

    # --- 2. Block Compliance (30%) ---
    block_score = 0.0
    if block_ranges:
        for ticket in wheel_combinations:
            sorted_t = sorted(ticket)
            matches = 0
            for slot in range(min(6, len(sorted_t))):
                key = str(slot)
                if key in block_ranges:
                    opt_bucket = block_ranges[key]["optimal_bucket"]
                    if _bucket_index(sorted_t[slot]) == opt_bucket:
                        matches += 1
            block_score += (matches / 6.0) * 100.0
        block_score /= n
    else:
        block_score = 50.0  # neutral if no block data

    # --- 3. Sum Validity (20%) ---
    sum_score = 0.0
    if sum_range:
        lo, hi = sum_range
        for ticket in wheel_combinations:
            s = sum(ticket)
            if lo <= s <= hi:
                sum_score += 100.0
        sum_score /= n
    else:
        sum_score = 50.0  # neutral

    # --- 4. Numerical Attraction (10%) ---
    attract_score = 0.0
    for ticket in wheel_combinations:
        if _has_adjacent(ticket):
            attract_score += 100.0
    attract_score /= n

    # Weighted total
    total = (
        pos_neg_score * 0.40
        + block_score * 0.30
        + sum_score * 0.20
        + attract_score * 0.10
    )
    return round(total, 1)


def get_score_breakdown(
    wheel_combinations: Sequence[Sequence[int]],
    albert_state: dict[str, Any],
) -> dict[str, Any]:
    """Return a detailed breakdown of each scoring dimension.

    Parameters
    ----------
    wheel_combinations : list[list[int]]
    albert_state : dict
        Same as score_wheel.

    Returns
    -------
    dict
        Keys: total_score, pos_neg, block_compliance, sum_validity,
        numerical_attraction, color.
    """
    if not wheel_combinations:
        return {
            "total_score": 0.0,
            "pos_neg": 0.0,
            "block_compliance": 0.0,
            "sum_validity": 0.0,
            "numerical_attraction": 0.0,
            "color": "red",
        }

    positive_set = set(albert_state.get("positive", []))
    negative_set = set(albert_state.get("negative", []))
    block_ranges = albert_state.get("block_ranges", {})
    sum_range = albert_state.get("sum_range")
    n = len(wheel_combinations)

    # Per-ticket scores
    pos_neg = block_comp = sum_valid = attract = 0.0

    for ticket in wheel_combinations:
        sorted_t = sorted(ticket)

        # Pos/Neg
        pc = sum(1 for x in ticket if x in positive_set)
        nc = sum(1 for x in ticket if x in negative_set)
        if pc >= 2 and nc >= 2:
            pos_neg += 100.0
        elif pc >= 1 and nc >= 1:
            pos_neg += 50.0

        # Block
        if block_ranges:
            matches = 0
            for slot in range(min(6, len(sorted_t))):
                key = str(slot)
                if (
                    key in block_ranges
                    and _bucket_index(sorted_t[slot])
                    == block_ranges[key]["optimal_bucket"]
                ):
                    matches += 1
            block_comp += (matches / 6.0) * 100.0

        # Sum
        if sum_range:
            s = sum(ticket)
            if sum_range[0] <= s <= sum_range[1]:
                sum_valid += 100.0

        # Attraction
        if _has_adjacent(ticket):
            attract += 100.0

    pos_neg /= n
    block_comp = (block_comp / n) if block_ranges else 50.0
    sum_valid = (sum_valid / n) if sum_range else 50.0
    attract /= n

    total = pos_neg * 0.40 + block_comp * 0.30 + sum_valid * 0.20 + attract * 0.10

    color = "green" if total >= 80 else ("yellow" if total >= 60 else "red")

    return {
        "total_score": round(total, 1),
        "pos_neg": round(pos_neg, 1),
        "block_compliance": round(block_comp, 1),
        "sum_validity": round(sum_valid, 1),
        "numerical_attraction": round(attract, 1),
        "color": color,
    }
