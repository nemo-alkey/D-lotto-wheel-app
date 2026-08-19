#!/usr/bin/env python3
"""
pos_neg_tracker.py — Albert's Positive/Negative auto-tagger with shift alerts.

Albert's method (NZ Lotto 6/40)
-------------------------------
Over the last 30 draws, count how often each number 1-40 appeared, then
rank the numbers by frequency:

  - **Positive (hot)**:  top 33% of frequencies  (≈13 numbers in 6/40)
  - **Negative (cold)**: bottom 33% of frequencies (≈13 numbers)
  - **Neutral**:         the middle 34%           (≈14 numbers)

Albert's reasoning: a wheel weighted toward Positive numbers (roughly
60% positive / 40% negative) mirrors the profile of most winning draws.
But the hot/cold split is not static — after each new draw the ranking
rebalances, and occasionally several numbers swap polarity at once.
A swap of 3+ numbers between Positive and Negative is a *distribution
shift*: the historical profile has moved, and wheels built on the old
classification should be regenerated. This module detects and persists
those shifts.

Database
--------
Each rebalance is persisted to ``pos_neg_history``:

    id, draw_id, classification_json, shift_detected, alert_message, timestamp

``shift_detected`` stores the number of polarity crossings (Positive↔
Negative) vs the previously saved classification (0 = no shift).

Scheduler integration
---------------------
``run_rebalance_check()`` is called from update_draws.py after each new
draw fetch. It reads the last 30 draws, computes the classification,
compares it to the last saved one, logs any shift, and saves the result.

Usage:
    from pos_neg_tracker import (
        classify_pos_neg, detect_distribution_shift,
        save_classification, run_rebalance_check,
    )
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import Counter
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lotto.db")

DEFAULT_WINDOW = 30  # draws in the classification window
DEFAULT_POOL_SIZE = 40  # NZ Lotto 6/40
SHIFT_THRESHOLD = 3  # polarity crossings that constitute a shift


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_pos_neg(
    draws: list[list[int]],
    pool_size: int = DEFAULT_POOL_SIZE,
    window: int = DEFAULT_WINDOW,
) -> dict[str, list[int]]:
    """Tag each number as Positive (hot), Negative (cold), or Neutral.

    Counts each number's frequency over the last ``window`` draws, ranks
    all numbers, and assigns the top ~33% to Positive, the bottom ~33%
    to Negative, and the middle to Neutral.

    Args:
        draws: Draw history, each a list of 6 numbers (chronological).
        pool_size: Size of the number pool (default 40 → 13 pos / 13 neg /
            14 neutral).
        window: How many recent draws to count (default 30).

    Returns:
        {"positive": [...], "negative": [...], "neutral": [...]} —
        each sorted ascending.
    """
    recent = draws[-window:] if len(draws) > window else draws
    freq: Counter[int] = Counter()
    for draw in recent:
        freq.update(n for n in draw if 1 <= n <= pool_size)

    # Deterministic ranking: highest frequency first, ties by number
    ranked = sorted(range(1, pool_size + 1), key=lambda n: (-freq.get(n, 0), n))

    n_pos = round(pool_size / 3)
    n_neg = round(pool_size / 3)
    return {
        "positive": sorted(ranked[:n_pos]),
        "negative": sorted(ranked[pool_size - n_neg :]),
        "neutral": sorted(ranked[n_pos : pool_size - n_neg]),
    }


def count_polarity_crossings(
    current: dict[str, list[int]], previous: dict[str, list[int]] | None
) -> int:
    """Total numbers that crossed between Positive and Negative sets."""
    if not current or not previous:
        return 0
    p2n = set(previous.get("positive", [])) & set(current.get("negative", []))
    n2p = set(previous.get("negative", [])) & set(current.get("positive", []))
    return len(p2n) + len(n2p)


# ---------------------------------------------------------------------------
# Shift detection
# ---------------------------------------------------------------------------


def detect_distribution_shift(
    current: dict[str, list[int]],
    previous: dict[str, list[int]] | None,
    threshold: int = SHIFT_THRESHOLD,
) -> str | None:
    """Compare two classifications and alert on a polarity swing.

    A shift is declared when ``threshold`` or more numbers moved from
    Positive to Negative, or vice versa, between the two classifications.

    Args:
        current: Latest classification from classify_pos_neg().
        previous: The previously saved classification (may be None/empty).
        threshold: Minimum one-direction crossings to alert (default 3).

    Returns:
        An alert string describing the shift, or None when the
        distribution is stable.
    """
    if not current or not previous:
        return None

    p2n = sorted(set(previous["positive"]) & set(current["negative"]))
    n2p = sorted(set(previous["negative"]) & set(current["positive"]))

    if len(p2n) < threshold and len(n2p) < threshold:
        return None

    parts = []
    if p2n:
        parts.append(f"{len(p2n)} dropped Positive->Negative: {p2n}")
    if n2p:
        parts.append(f"{len(n2p)} rose Negative->Positive: {n2p}")
    return "DISTRIBUTION SHIFT — " + "; ".join(parts)


def shift_timeline(
    draws: list[list[int]],
    pool_size: int = DEFAULT_POOL_SIZE,
    window: int = DEFAULT_WINDOW,
) -> list[dict[str, int]]:
    """Replay history and compute the shift count at every draw.

    For each draw index from ``window + 1`` onward, classifies the window
    ending at that draw and counts polarity crossings vs the window ending
    one draw earlier.

    Returns:
        [{"draw_index": i, "shift_count": c}, ...] — draw_index is 1-based
        (i.e. the count after the i-th draw in the supplied history).
    """
    timeline: list[dict[str, int]] = []
    prev = None
    for i in range(window, len(draws) + 1):
        cls = classify_pos_neg(draws[:i], pool_size=pool_size, window=window)
        if prev is not None:
            timeline.append(
                {
                    "draw_index": i,
                    "shift_count": count_polarity_crossings(cls, prev),
                }
            )
        prev = cls
    return timeline


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _init_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pos_neg_history (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_id            INTEGER,
            classification_json TEXT NOT NULL,
            shift_detected     INTEGER NOT NULL DEFAULT 0,
            alert_message      TEXT,
            timestamp          TEXT NOT NULL
        )
    """)


def save_classification(
    draw_id: int,
    classification: dict[str, list[int]],
    db_path: str = DB_PATH,
    shift_detected: int = 0,
    alert_message: str | None = None,
) -> None:
    """Persist a classification snapshot to pos_neg_history.

    Args:
        draw_id: The latest draw this classification is based on.
        classification: Output of classify_pos_neg().
        db_path: Path to lotto.db.
        shift_detected: Number of polarity crossings vs the previous
            saved classification (0 = stable).
        alert_message: The shift alert text, if any.
    """
    conn = sqlite3.connect(db_path)
    try:
        _init_table(conn)
        conn.execute(
            "INSERT INTO pos_neg_history "
            "(draw_id, classification_json, shift_detected, alert_message, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                draw_id,
                json.dumps(classification),
                shift_detected,
                alert_message,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scheduler entry point
# ---------------------------------------------------------------------------


def run_rebalance_check(
    db_path: str = DB_PATH,
    window: int = DEFAULT_WINDOW,
    threshold: int = SHIFT_THRESHOLD,
) -> str | None:
    """Recompute the Pos/Neg classification after a new draw and log shifts.

    Reads the last ``window`` draws, classifies them, compares against the
    last saved classification, persists the new snapshot, and logs any
    distribution shift. Called from update_draws.py after each new draw
    fetch.

    Returns:
        The alert message if a shift was detected, else None.
    """
    conn = sqlite3.connect(db_path)
    try:
        _init_table(conn)
        rows = conn.execute(
            "SELECT draw_id, numbers FROM draws ORDER BY draw_date DESC LIMIT ?",
            (window,),
        ).fetchall()
        if not rows:
            logger.info("Pos/Neg rebalance: no draws in database, skipping.")
            return None
        latest_draw_id = rows[0][0]
        draws = [
            [int(x) for x in str(numbers).replace(",", " ").split()] for _draw_id, numbers in rows
        ]
        prev_row = conn.execute(
            "SELECT classification_json FROM pos_neg_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    classification = classify_pos_neg(draws, window=window)
    previous = json.loads(prev_row[0]) if prev_row else None

    alert = detect_distribution_shift(classification, previous, threshold=threshold)
    crossings = count_polarity_crossings(classification, previous) if previous else 0

    save_classification(
        latest_draw_id,
        classification,
        db_path,
        shift_detected=crossings,
        alert_message=alert,
    )

    if alert:
        logger.warning("Pos/Neg %s", alert)
    else:
        logger.info(
            "Pos/Neg rebalance: stable (%d crossings, threshold %d).",
            crossings,
            threshold,
        )
    return alert


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random
    import tempfile

    random.seed(11)

    # --- Phase 1: 30 draws where 1-13 are hot, 28-40 are cold ---
    phase1: list[list[int]] = []
    for _ in range(30):
        draw = set(random.sample(range(1, 14), 3))  # hot zone
        while len(draw) < 6:
            draw.add(random.randint(14, 27))  # neutral fill
        phase1.append(sorted(draw))

    cls_prev = classify_pos_neg(phase1)
    print("Phase 1 (1-13 hot):")
    print(f"  positive: {cls_prev['positive']}")
    print(f"  negative: {cls_prev['negative']}")
    assert set(range(1, 14)).issubset(set(cls_prev["positive"]) | set(cls_prev["neutral"]))
    assert not set(range(28, 41)) & set(cls_prev["positive"]), "cold numbers should not be Positive"

    # --- Phase 2: polarity reverses — 28-40 become hot, 1-13 cold ---
    phase2: list[list[int]] = []
    for _ in range(30):
        draw = set(random.sample(range(28, 41), 3))  # new hot zone
        while len(draw) < 6:
            draw.add(random.randint(14, 27))
        phase2.append(sorted(draw))

    cls_cur = classify_pos_neg(phase2)  # full polarity reversal
    print("\nPhase 2 (28-40 hot):")
    print(f"  positive: {cls_cur['positive']}")
    print(f"  negative: {cls_cur['negative']}")

    alert = detect_distribution_shift(cls_cur, cls_prev, threshold=3)
    print(f"\nShift alert: {alert}")
    assert alert is not None, "a 13-number polarity reversal must trigger an alert"
    assert "DISTRIBUTION SHIFT" in alert

    # Stable comparison should NOT alert
    assert detect_distribution_shift(cls_prev, cls_prev) is None
    assert detect_distribution_shift(cls_cur, None) is None
    print("Stable and empty-history comparisons correctly return None.")

    # --- Persistence round-trip on a temp database ---
    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = os.path.join(tmp, "test_lotto.db")
        conn = sqlite3.connect(tmp_db)
        conn.execute("""
            CREATE TABLE draws (
                draw_id INTEGER PRIMARY KEY, draw_date TEXT UNIQUE,
                numbers TEXT, bonus INTEGER, powerball INTEGER
            )
        """)
        for i, draw_row in enumerate(phase1 + phase2, start=1):
            conn.execute(
                "INSERT INTO draws VALUES (?, ?, ?, 1, 1)",
                (i, f"2024-01-{i:02d}", ",".join(map(str, draw_row))),
            )
        conn.commit()
        conn.close()

        # First rebalance: no previous classification -> stable
        assert run_rebalance_check(tmp_db) is None
        # Rewind: clear history, save the phase-1 classification as
        # "previous", then delete phase-1 draws so the next check compares
        # a phase-2 window against it.
        conn = sqlite3.connect(tmp_db)
        conn.execute("DELETE FROM pos_neg_history")
        conn.execute("DELETE FROM draws WHERE draw_id <= 45")
        conn.commit()
        conn.close()
        save_classification(30, classify_pos_neg(phase1), tmp_db)
        alert2 = run_rebalance_check(tmp_db)
        print(f"\nrun_rebalance_check after reversal: {alert2}")
        assert alert2 is not None and "DISTRIBUTION SHIFT" in alert2

        conn = sqlite3.connect(tmp_db)
        n_rows = conn.execute("SELECT COUNT(*) FROM pos_neg_history").fetchone()[0]
        last = conn.execute(
            "SELECT shift_detected, alert_message FROM pos_neg_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert n_rows >= 2 and last[0] >= 3 and last[1]
        print(f"pos_neg_history persisted {n_rows} snapshots; latest shift count {last[0]}.")

    # --- Timeline ---
    # Per-draw steps are gradual (a sliding window swaps one draw at a
    # time), so to demonstrate visible crossings we replay a sharp flip:
    # every phase-A draw takes 3 numbers from 1-13, every phase-B draw
    # 3 from 28-40, classified with a short window.
    random.seed(5)
    flip: list[list[int]] = []
    for _ in range(10):
        flip.append(sorted(random.sample(range(1, 14), 3) + random.sample(range(14, 28), 3)))
    for _ in range(10):
        flip.append(sorted(random.sample(range(28, 41), 3) + random.sample(range(14, 28), 3)))

    timeline = shift_timeline(flip, window=5)
    peak = max(t["shift_count"] for t in timeline)
    print(
        f"\nTimeline: {len(timeline)} points, peak shift count {peak} " f"around the polarity flip."
    )
    assert peak >= 3, "a sharp polarity flip must show up in the timeline"

    print("\nAll pos_neg_tracker self-tests passed.")
