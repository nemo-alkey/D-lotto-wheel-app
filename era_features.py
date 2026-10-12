#!/usr/bin/env python3
"""
era_features.py — Era-aware Powerball features and the mixed-era training guard.

The NZ Powerball pool changed from 1-10 to 1-14 with the 2026-09-16 draw.
Powerball *statistics* (frequencies, transitions, model training data) must
never silently mix the two distributions. Main Lotto numbers (1-40) are
unaffected and may use all history.

Rules enforced here:
  - Powerball features are computed only from draws of the CURRENT era
    ('post_2026_09_16' now), unless a caller is explicitly era-aware.
  - Training on draws from both eras without the era flag raises
    MixedEraTrainingError.
  - The era flag ('rule_era') is derived from draw_date and is also stored
    as a column on the draws table (see ensure_rule_era_column).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any, Optional, Sequence

from powerball_rules import POWERBALL_CHANGE_DATE, parse_draw_date

#: Stable string labels for the two rule eras.
RULE_ERA_PRE = "pre_2026_09_16"
RULE_ERA_POST = "post_2026_09_16"

#: Powerball pool size in each era.
POWERBALL_POOL_SIZES = {RULE_ERA_PRE: 10, RULE_ERA_POST: 14}


class MixedEraTrainingError(ValueError):
    """Raised when Powerball training data spans both rule eras without an
    explicit era-aware flag."""


def rule_era_for_date(draw_date: date | datetime | str) -> str:
    """Return the rule-era label for a draw date."""
    return RULE_ERA_POST if parse_draw_date(draw_date) >= POWERBALL_CHANGE_DATE else RULE_ERA_PRE


def current_rule_era(today: date | None = None) -> str:
    """The era new models should target: today's era by default."""
    d = today or date.today()
    return rule_era_for_date(d)


def powerball_pool_size(era: Optional[str] = None) -> int:
    """Powerball pool size for an era (default: the current era)."""
    era = era or current_rule_era()
    if era not in POWERBALL_POOL_SIZES:
        raise ValueError(f"Unknown rule era: {era!r}")
    return POWERBALL_POOL_SIZES[era]


def _draw_date(draw: Any, date_key: str = "draw_date", date_index: Optional[int] = None) -> date:
    """Extract a draw date from a dict or a sequence (e.g. Colab tuples)."""
    if isinstance(draw, dict):
        value = draw.get(date_key) or draw.get("date")
        if value is None:
            raise ValueError(f"Draw dict has no {date_key!r} key: {draw!r}")
        return parse_draw_date(value)
    if date_index is not None and isinstance(draw, (tuple, list)):
        return parse_draw_date(draw[date_index])
    raise ValueError(f"Cannot extract draw date from {type(draw).__name__}: {draw!r}")


def filter_draws_by_era(
    draws: Sequence[Any],
    era: str,
    date_key: str = "draw_date",
    date_index: Optional[int] = None,
) -> list[Any]:
    """Return only draws belonging to ``era``. Never mixes distributions."""
    return [d for d in draws if rule_era_for_date(_draw_date(d, date_key, date_index)) == era]


def check_single_era(
    draws: Sequence[Any],
    context: str = "",
    era_aware: bool = False,
    date_key: str = "draw_date",
    date_index: Optional[int] = None,
) -> Optional[str]:
    """Guard: ensure ``draws`` spans at most one rule era.

    Returns the era label, or None for an empty sequence. Raises
    MixedEraTrainingError when both eras are present and the caller has not
    opted in via ``era_aware=True``.
    """
    eras = {rule_era_for_date(_draw_date(d, date_key, date_index)) for d in draws}
    if len(eras) <= 1:
        return next(iter(eras)) if eras else None
    if era_aware:
        return None  # caller takes responsibility; eras are mixed by design
    where = f" ({context})" if context else ""
    raise MixedEraTrainingError(
        f"Powerball training data{where} mixes rule eras {sorted(eras)}. "
        "Train on a single era, or pass era_aware=True and include the era "
        "flag as an explicit model feature."
    )


def powerball_training_draws(
    draws: Sequence[Any],
    context: str = "",
    era_aware: bool = False,
    date_key: str = "draw_date",
    date_index: Optional[int] = None,
) -> list[Any]:
    """Draws that may be used for Powerball *training*.

    Default (not era-aware): only the current era's draws — never a mix.
    With era_aware=True: all draws, after verifying the caller knows they
    span eras (check_single_era opt-in).
    """
    if era_aware:
        check_single_era(draws, context=context, era_aware=True, date_key=date_key, date_index=date_index)
        return list(draws)
    era = current_rule_era()
    return filter_draws_by_era(draws, era, date_key=date_key, date_index=date_index)


def era_flags(
    draws: Sequence[Any],
    date_key: str = "draw_date",
    date_index: Optional[int] = None,
) -> list[int]:
    """Explicit era feature (0 = pre, 1 = post) for era-aware models."""
    return [
        1 if rule_era_for_date(_draw_date(d, date_key, date_index)) == RULE_ERA_POST else 0
        for d in draws
    ]


# ---------------------------------------------------------------------------
# draws-table rule_era column
# ---------------------------------------------------------------------------


def ensure_rule_era_column(conn: sqlite3.Connection) -> bool:
    """Add the rule_era column to draws if missing; backfill NULL values.

    Idempotent. Returns True if the column was created, False if it already
    existed (values are still backfilled either way).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(draws)")}
    created = False
    if "rule_era" not in cols:
        conn.execute("ALTER TABLE draws ADD COLUMN rule_era TEXT")
        created = True
    conn.execute(
        "UPDATE draws SET rule_era = ? WHERE draw_date < ? AND (rule_era IS NULL OR rule_era = '')",
        (RULE_ERA_PRE, POWERBALL_CHANGE_DATE.isoformat()),
    )
    conn.execute(
        "UPDATE draws SET rule_era = ? WHERE draw_date >= ? AND (rule_era IS NULL OR rule_era = '')",
        (RULE_ERA_POST, POWERBALL_CHANGE_DATE.isoformat()),
    )
    conn.commit()
    return created
