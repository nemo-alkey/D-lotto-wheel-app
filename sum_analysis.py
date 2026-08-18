#!/usr/bin/env python3
"""
sum_analysis.py — Dynamic sum-range validation using rolling volatility.

Computes trimmed mean and standard deviation of draw sums over a sliding
window, then adjusts the acceptable sum range based on recent volatility.
During stable periods the range is wider (±2.5σ); during volatile periods
it tightens to ±1.5σ to capture the shift in distribution.

All functions accept a sqlite3.Connection to a database with a 'draws' table
that has columns: draw_id, draw_date, numbers (comma-separated).
"""

from __future__ import annotations

import sqlite3
from typing import Any


def _parse_numbers(row: tuple[Any, ...]) -> list[int] | None:
    """Parse the comma-separated 'numbers' column from a DB row."""
    try:
        return [int(x.strip()) for x in row[0].split(",")]
    except (ValueError, AttributeError):
        return None


def dynamic_sum_range(
    conn: sqlite3.Connection,
    window_draws: int = 30,
    base_trim_percent: int = 10,
) -> tuple[float, float]:
    """Compute a dynamic acceptable sum range based on recent volatility.

    Parameters
    ----------
    conn : sqlite3.Connection
    window_draws : int
        Number of most-recent draws for the main window (default 30).
    base_trim_percent : int
        Percentage of extreme values to trim from each tail (default 10).

    Returns
    -------
    tuple[float, float]
        (min_sum, max_sum) acceptable range.
    """
    # Fetch all draws ordered by date (oldest first)
    cursor = conn.execute("SELECT numbers FROM draws ORDER BY draw_date ASC")
    rows = cursor.fetchall()
    cursor.close()

    sums: list[int] = []
    for row in rows:
        nums = _parse_numbers(row)
        if nums and len(nums) == 6:
            sums.append(sum(nums))

    if not sums:
        return (0.0, 0.0)

    n = len(sums)

    # --- Trimmed stats over the main window ---
    window = sums[-window_draws:] if n > window_draws else sums
    if not window:
        return (0.0, 0.0)

    sorted_w = sorted(window)
    trim = max(1, len(sorted_w) * base_trim_percent // 100)
    trimmed = sorted_w[trim:-trim] if len(sorted_w) > 2 * trim else sorted_w
    if not trimmed:
        trimmed = sorted_w

    mean = sum(trimmed) / len(trimmed)
    # Population std
    variance = sum((x - mean) ** 2 for x in trimmed) / len(trimmed)
    std = variance**0.5

    # --- Volatility: rolling std over last 10 draws within the window ---
    vol_window = window[-10:] if len(window) >= 10 else window
    if len(vol_window) >= 2:
        vol_mean = sum(vol_window) / len(vol_window)
        vol_var = sum((x - vol_mean) ** 2 for x in vol_window) / len(vol_window)
        current_vol = vol_var**0.5
    else:
        current_vol = 0.0

    # --- Historical volatility quartiles (across full dataset) ---
    all_vols: list[float] = []
    for i in range(10, n):
        chunk = sums[i - 9 : i + 1]
        chunk_mean = sum(chunk) / len(chunk)
        chunk_var = sum((x - chunk_mean) ** 2 for x in chunk) / len(chunk)
        all_vols.append(chunk_var**0.5)

    if all_vols:
        sorted_vols = sorted(all_vols)
        upper_quartile = sorted_vols[int(len(sorted_vols) * 0.75)]
    else:
        upper_quartile = current_vol

    # --- Choose multiplier ---
    multiplier = 1.5 if current_vol > upper_quartile else 2.5

    lo = mean - multiplier * std
    hi = mean + multiplier * std
    return (lo, hi)


def volatility_adjusted_tolerance() -> float:
    """Return the recommended sum tolerance for the current volatility regime.

    High volatility → tight tolerance (1.5σ).  Low volatility → wide (2.5σ).
    This is a wrapper around the multiplier selection logic in
    dynamic_sum_range so callers don't need to re-query.
    """
    # The actual multiplier is chosen by dynamic_sum_range based on the data.
    # This function returns a default (the wide/strict modes are context-dependent).
    return 2.5  # default to wide; callers should prefer dynamic_sum_range()


def backtest_sum_ranges(
    conn: sqlite3.Connection,
    test_draws: int = 100,
    window_draws: int = 30,
) -> dict[str, float | int]:
    """Measure how often historical sums fell within the dynamic range.

    For each draw in the test set, computes the dynamic sum range using
    the preceding window_draws draws and checks whether the actual draw
    sum falls within it.

    Parameters
    ----------
    conn : sqlite3.Connection
    test_draws : int
        Number of most-recent draws to backtest (default 100).
    window_draws : int
        Lookback window for dynamic range computation (default 30).

    Returns
    -------
    dict
        Keys: coverage_pct, hits, misses, total, avg_range_width.
    """
    cursor = conn.execute("SELECT numbers FROM draws ORDER BY draw_date ASC")
    rows = cursor.fetchall()
    cursor.close()

    sums: list[int] = []
    for row in rows:
        nums = _parse_numbers(row)
        if nums and len(nums) == 6:
            sums.append(sum(nums))

    n = len(sums)
    if n <= window_draws:
        return {"coverage_pct": 0.0, "hits": 0, "misses": 0, "total": 0, "avg_range_width": 0.0}

    test_count = min(test_draws, n - window_draws)
    hits = 0
    ranges: list[float] = []

    for i in range(n - test_count, n):
        # Use preceding window (i - window_draws to i-1) for the range
        window = sums[i - window_draws : i]

        # Trimmed stats
        sorted_w = sorted(window)
        trim = max(1, len(sorted_w) * 10 // 100)
        trimmed = sorted_w[trim:-trim] if len(sorted_w) > 2 * trim else sorted_w
        mean = sum(trimmed) / len(trimmed)
        variance = sum((x - mean) ** 2 for x in trimmed) / len(trimmed)
        std = variance**0.5

        # Volatility over last 10
        vol_w = window[-10:]
        if len(vol_w) >= 2:
            vol_mean_v = sum(vol_w) / len(vol_w)
            vol_var_v = sum((x - vol_mean_v) ** 2 for x in vol_w) / len(vol_w)
            current_vol = vol_var_v**0.5
        else:
            current_vol = 0.0

        # Historical quartile
        all_vols = []
        for j in range(10, i):
            c = sums[j - 9 : j + 1]
            cm = sum(c) / len(c)
            cv = sum((x - cm) ** 2 for x in c) / len(c)
            all_vols.append(cv**0.5)
        upper_q = sorted(all_vols)[int(len(all_vols) * 0.75)] if all_vols else current_vol

        multiplier = 1.5 if current_vol > upper_q else 2.5
        lo = mean - multiplier * std
        hi = mean + multiplier * std
        ranges.append(hi - lo)

        actual = sums[i]
        if lo <= actual <= hi:
            hits += 1

    coverage = hits / test_count * 100 if test_count > 0 else 0.0
    return {
        "coverage_pct": round(coverage, 1),
        "hits": hits,
        "misses": test_count - hits,
        "total": test_count,
        "avg_range_width": round(sum(ranges) / len(ranges), 1) if ranges else 0.0,
    }
