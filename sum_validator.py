#!/usr/bin/env python3
"""
sum_validator.py — Emil Albert's dynamic sum range validation.

Albert's reasoning
------------------
Every 6/40 draw sums to somewhere between 21 (1+2+3+4+5+6) and 225
(35+36+37+38+39+40), but winning draws are NOT spread evenly across that
span — they cluster tightly around the mean (~123 for 6/40). Albert's
observation: the vast majority of winning draws fall within the **central
~90% of historical sums**. Extreme draws (all-low or all-high numbers) do
occur, but they are rare outliers that should not widen a wheel's
acceptable range.

So instead of using the theoretical min/max, we compute the range from
recent history and DISCARD the top and bottom ``outlier_pct`` of draw sums
(default 5% each tail, keeping the central 90%). For NZ Lotto 6/40 the
resulting range is typically ~90–180. Tickets whose sum falls outside the
range are statistically unlikely to match a future draw's profile and can
be filtered out of generated wheels.

Unlike sum_analysis.py (DB-based, volatility-adjusted), this module works
directly on in-memory draw lists — no database connection needed.

Usage:
    from sum_validator import (
        calculate_dynamic_sum_range, validate_wheel_sum, get_sum_statistics,
    )
"""

from __future__ import annotations

import statistics

DEFAULT_WINDOW = 30
DEFAULT_OUTLIER_PCT = 0.05  # discard 5% per tail -> keep the central 90%


# ---------------------------------------------------------------------------
# Dynamic range
# ---------------------------------------------------------------------------


def calculate_dynamic_sum_range(
    draws: list[list[int]],
    window: int = DEFAULT_WINDOW,
    outlier_pct: float = DEFAULT_OUTLIER_PCT,
) -> tuple[int, int]:
    """Compute the acceptable sum range from recent draw history.

    Sums each draw in the last ``window`` draws, sorts the sums, and
    discards the bottom ``outlier_pct`` and top ``outlier_pct`` as
    outliers. Returns the min/max of what remains.

    Args:
        draws: Draw history, each a list of 6 numbers (chronological).
        window: How many recent draws to use (default 30).
        outlier_pct: Fraction to trim from EACH tail (default 0.05 → the
            central 90% of sums is kept).

    Returns:
        (min_remaining_sum, max_remaining_sum). Falls back to the raw
        min/max when the window is too small to trim.
    """
    if not draws:
        return (0, 0)

    recent = draws[-window:] if len(draws) > window else draws
    sums = sorted(sum(d) for d in recent if d)
    if not sums:
        return (0, 0)

    trim = int(len(sums) * outlier_pct)
    trimmed = sums[trim : len(sums) - trim] if len(sums) > 2 * trim else sums
    if not trimmed:  # extremely small windows
        trimmed = sums
    return (trimmed[0], trimmed[-1])


# ---------------------------------------------------------------------------
# Wheel/ticket validation
# ---------------------------------------------------------------------------


def validate_wheel_sum(wheel: list[int], min_sum: int, max_sum: int) -> tuple[bool, int, str]:
    """Check a ticket's (or pool's) sum against the acceptable range.

    Args:
        wheel: The numbers to check (typically one 6-number ticket).
        min_sum: Lower bound from calculate_dynamic_sum_range().
        max_sum: Upper bound.

    Returns:
        (is_valid, actual_sum, message) — the message states whether the
        sum is too low, too high, or within range.
    """
    actual = sum(wheel)
    if actual < min_sum:
        return (
            False,
            actual,
            f"Sum {actual} is TOO LOW (< {min_sum}) — outside the central "
            f"90% of recent draw sums.",
        )
    if actual > max_sum:
        return (
            False,
            actual,
            f"Sum {actual} is TOO HIGH (> {max_sum}) — outside the central "
            f"90% of recent draw sums.",
        )
    return (
        True,
        actual,
        f"Sum {actual} is within range ({min_sum}–{max_sum}).",
    )


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def get_sum_statistics(draws: list[list[int]]) -> dict[str, float | int]:
    """Summary statistics over all draw sums.

    Returns:
        Dict with mean, median, std_dev (population), min, max, and the
        10th/90th percentiles of draw sums. Empty input yields zeros.
    """
    sums = [sum(d) for d in draws if d]
    if not sums:
        return {
            "mean": 0.0,
            "median": 0.0,
            "std_dev": 0.0,
            "min": 0,
            "max": 0,
            "percentile_10": 0.0,
            "percentile_90": 0.0,
            "count": 0,
        }

    if len(sums) >= 10:
        quantiles = statistics.quantiles(sums, n=10)  # 9 cut points
        p10, p90 = quantiles[0], quantiles[-1]
    else:
        p10, p90 = float(min(sums)), float(max(sums))

    return {
        "mean": round(statistics.fmean(sums), 2),
        "median": round(statistics.median(sums), 2),
        "std_dev": round(statistics.pstdev(sums), 2),
        "min": min(sums),
        "max": max(sums),
        "percentile_10": round(p10, 2),
        "percentile_90": round(p90, 2),
        "count": len(sums),
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    random.seed(42)

    # 30 synthetic 6/40 draws clustered around the expected mean (~123),
    # with two deliberate outliers: one all-low draw and one all-high draw.
    synthetic: list[list[int]] = []
    for _ in range(28):
        draw = sorted(random.sample(range(15, 36), 6))  # sums ~153 ± spread
        synthetic.append(draw)
    synthetic.insert(10, [1, 2, 3, 4, 5, 6])  # sum 21  (extreme low)
    synthetic.insert(20, [35, 36, 37, 38, 39, 40])  # sum 225 (extreme high)

    raw_sums = [sum(d) for d in synthetic]
    print(f"30 synthetic draws: raw min={min(raw_sums)}, max={max(raw_sums)}")

    lo, hi = calculate_dynamic_sum_range(synthetic, window=30, outlier_pct=0.05)
    print(f"Dynamic range (5% trim): {lo}–{hi}")
    assert lo > 21, "the all-low outlier should have been trimmed"
    assert hi < 225, "the all-high outlier should have been trimmed"
    print("Outlier rejection confirmed: 21 and 225 discarded.")

    # Untrimmed range would include the outliers
    lo0, hi0 = calculate_dynamic_sum_range(synthetic, window=30, outlier_pct=0.0)
    assert (lo0, hi0) == (21, 225)
    print(f"Untrimmed range for comparison: {lo0}–{hi0}")

    # Validation
    ok, s, msg = validate_wheel_sum([15, 18, 22, 25, 30, 33], lo, hi)
    print(f"\nValid ticket:   {msg} (valid={ok})")
    assert ok
    ok, s, msg = validate_wheel_sum([1, 2, 3, 4, 5, 6], lo, hi)
    print(f"All-low ticket: {msg} (valid={ok})")
    assert not ok and s == 21

    # Statistics
    stats = get_sum_statistics(synthetic)
    print("\nSum statistics:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    assert stats["min"] == 21 and stats["max"] == 225 and stats["count"] == 30
    assert stats["percentile_10"] < stats["mean"] < stats["percentile_90"]

    print("\nAll sum_validator self-tests passed.")
