#!/usr/bin/env python3
"""
analysis_bonus_pairs.py — Co-occurrence analysis between bonus balls and main numbers.

Analyses historical draws to find which main numbers most frequently appear
alongside each bonus ball, plus the most common bonus+main+main triplets.

All functions accept a sqlite3.Connection to a database with a 'draws' table
that has columns: draw_id, draw_date, numbers (comma-separated), bonus.
"""

from __future__ import annotations

import sqlite3
from collections import Counter

import pandas as pd


def compute_cooccurrence_matrix(
    conn: sqlite3.Connection, min_support: int = 5
) -> pd.DataFrame:
    """Return a 40×40 DataFrame of bonus–main co-occurrence counts.

    Cell [bonus_i][main_j] = number of draws where bonus == i and main
    number j was among the 6 drawn main numbers.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to lotto.db.
    min_support : int
        Minimum count threshold; cells below this are set to 0 in the
        returned DataFrame (default 5).

    Returns
    -------
    pd.DataFrame
        Index: bonus ball number (1-40), Columns: main number (1-40).
    """
    rows = conn.execute(
        "SELECT bonus, numbers FROM draws ORDER BY draw_date ASC"
    ).fetchall()

    # Initialise a 41×41 matrix (1-indexed) for convenience
    matrix = [[0] * 41 for _ in range(41)]

    for bonus, numbers_str in rows:
        if bonus is None or not (1 <= bonus <= 40):
            continue
        try:
            nums = [int(x.strip()) for x in numbers_str.split(",")]
        except (ValueError, AttributeError):
            continue
        for n in nums:
            if 1 <= n <= 40:
                matrix[bonus][n] += 1

    # Convert to DataFrame, drop index 0
    df = pd.DataFrame(
        [[matrix[b][m] for m in range(1, 41)] for b in range(1, 41)],
        index=pd.Index(range(1, 41), name="bonus"),
        columns=pd.Index(range(1, 41), name="main"),
    )

    # Apply minimum support filter
    if min_support > 0:
        df = df.where(df >= min_support, 0)

    return df


def get_top_pairs_for_bonus(
    conn: sqlite3.Connection, bonus_num: int, top_k: int = 3
) -> list[tuple[int, int]]:
    """Return the top-k main numbers that co-occur with a specific bonus ball.

    Parameters
    ----------
    conn : sqlite3.Connection
    bonus_num : int
        Bonus ball to analyse (1-40).
    top_k : int
        Number of top pairs to return (default 3).

    Returns
    -------
    list[tuple[int, int]]
        Sorted descending: [(main_number, co_occurrence_count), ...]
    """
    rows = conn.execute(
        "SELECT numbers FROM draws WHERE bonus = ? ORDER BY draw_date ASC",
        (bonus_num,),
    ).fetchall()

    counter: Counter[int] = Counter()
    for (numbers_str,) in rows:
        try:
            nums = [int(x.strip()) for x in numbers_str.split(",")]
        except (ValueError, AttributeError):
            continue
        for n in nums:
            if 1 <= n <= 40:
                counter[n] += 1

    return counter.most_common(top_k)


def get_top_triplets(
    conn: sqlite3.Connection, top_n: int = 10
) -> list[tuple[int, int, int, int]]:
    """Return the top-N most common (bonus, main1, main2) triplets.

    A triplet is counted whenever a draw's bonus ball is *b* and two
    specific main numbers *a* and *b* both appear in that draw.

    Parameters
    ----------
    conn : sqlite3.Connection
    top_n : int
        Number of top triplets to return (default 10).

    Returns
    -------
    list[tuple[int, int, int, int]]
        Sorted descending: [(bonus, main1, main2, count), ...]
    """
    rows = conn.execute(
        "SELECT bonus, numbers FROM draws ORDER BY draw_date ASC"
    ).fetchall()

    triplet_counts: Counter[tuple[int, int, int]] = Counter()

    for bonus, numbers_str in rows:
        if bonus is None or not (1 <= bonus <= 40):
            continue
        try:
            nums = [int(x.strip()) for x in numbers_str.split(",")]
        except (ValueError, AttributeError):
            continue
        nums = sorted(n for n in nums if 1 <= n <= 40)
        # Enumerate all C(len(nums), 2) pairs of main numbers
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                triplet_counts[(bonus, nums[i], nums[j])] += 1

    top = triplet_counts.most_common(top_n)
    return [(b, a, c, cnt) for (b, a, c), cnt in top]
