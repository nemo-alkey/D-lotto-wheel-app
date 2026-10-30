"""Regression tests for ML Powerball feature construction."""

from __future__ import annotations

from predict_ml import MIN_HISTORY, build_features_for_draw
from powerball_rules import POWERBALL_MAX_NEW


def test_powerball_feature_block_supports_fourteen_numbers() -> None:
    """The 1-14 pool is detected as Powerball history, not main numbers."""
    draws = [
        (
            [((index + offset) % 40) + 1 for offset in range(6)],
            (index % POWERBALL_MAX_NEW) + 1,
            (index % 40) + 1,
            f"2026-09-{index + 1:02d}",
        )
        for index in range(MIN_HISTORY)
    ]

    rows = build_features_for_draw(draws, len(draws), range(1, POWERBALL_MAX_NEW + 1))

    assert len(rows) == POWERBALL_MAX_NEW
    assert [row["num"] for row in rows] == list(range(1, POWERBALL_MAX_NEW + 1))
    assert all(row["is_powerball"] for row in rows)
