#!/usr/bin/env python3
"""
albert_analysis.py — Emil Albert's Positive/Negative classification for NZ Lotto 6/40.

Classifies numbers 1-40 based on their draw frequency over a sliding window
and produces a recommended pool prioritising positive numbers.

All functions accept a sqlite3.Connection to a database with a 'draws' table
that has columns: draw_id, draw_date, numbers (comma-separated).
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any


def classify_numbers(conn: sqlite3.Connection, window_draws: int = 20) -> dict[str, Any]:
    """Classify numbers 1-40 into positive, negative, and never-drawn sets.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to lotto.db.
    window_draws : int
        Number of most-recent draws to analyse (default 20).

    Returns
    -------
    dict
        Keys: positive, negative, never, threshold, frequencies.
    """
    cursor = conn.execute(
        "SELECT numbers FROM draws ORDER BY draw_date DESC LIMIT ?",
        (window_draws,),
    )
    rows = cursor.fetchall()
    cursor.close()

    freq: Counter[int] = Counter()
    for (numbers_str,) in rows:
        try:
            nums = [int(x.strip()) for x in numbers_str.split(",")]
        except (ValueError, AttributeError):
            continue
        for n in nums:
            if 1 <= n <= 40:
                freq[n] += 1

    max_freq = max(freq.values()) if freq else 0
    threshold = max_freq / 2.0 if max_freq > 0 else 0.0

    positive: list[int] = []
    negative: list[int] = []
    never: list[int] = []

    for n in range(1, 41):
        count = freq.get(n, 0)
        if count == 0:
            never.append(n)
        elif count >= threshold:
            positive.append(n)
        else:
            negative.append(n)

    return {
        "positive": positive,
        "negative": negative,
        "never": never,
        "threshold": threshold,
        "frequencies": dict(freq),
    }


def get_recommended_pool(
    conn: sqlite3.Connection,
    window_draws: int = 20,
    target_pool_size: int = 10,
    exclude_numbers: list[int] | None = None,
) -> list[int]:
    """Select a recommended number pool using Albert's classification rules.

    Rules:
      - 60% from positive set, 40% from negative set (as close as possible).
      - Never include never-drawn numbers.
      - Prioritise by frequency within each set.

    Parameters
    ----------
    conn : sqlite3.Connection
    window_draws : int
        Number of most-recent draws to analyse (default 20).
    target_pool_size : int
        Desired pool size (default 10).
    exclude_numbers : list[int] or None
        Numbers to exclude from the recommended pool.

    Returns
    -------
    list[int]
        Sorted list of recommended numbers.
    """
    result = classify_numbers(conn, window_draws)
    positive = result["positive"]
    negative = result["negative"]
    freq = result["frequencies"]

    # Filter out excluded numbers
    if exclude_numbers:
        exc = set(exclude_numbers)
        positive = [n for n in positive if n not in exc]
        negative = [n for n in negative if n not in exc]

    # Target counts
    pos_target = round(target_pool_size * 0.6)
    neg_target = target_pool_size - pos_target

    # Clamp to what's available
    pos_count = min(pos_target, len(positive))
    neg_count = min(neg_target, len(negative))

    # If we can't fill from one set, borrow from the other
    if pos_count < pos_target and len(negative) > neg_count:
        extra = min(pos_target - pos_count, len(negative) - neg_count)
        neg_count += extra
    if neg_count < neg_target and len(positive) > pos_count:
        extra = min(neg_target - neg_count, len(positive) - pos_count)
        pos_count += extra

    # Sort by frequency descending within each set
    pos_sorted = sorted(positive, key=lambda n: -freq.get(n, 0))
    neg_sorted = sorted(negative, key=lambda n: -freq.get(n, 0))

    pool = pos_sorted[:pos_count] + neg_sorted[:neg_count]
    return sorted(pool)
