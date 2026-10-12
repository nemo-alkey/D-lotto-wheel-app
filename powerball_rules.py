#!/usr/bin/env python3
"""
powerball_rules.py — Single source of truth for NZ Powerball game-rule eras.

The NZ Powerball game changed in September 2026. The final draw under the old
rules was Saturday 12 September 2026; the first draw under the new rules was
Wednesday 16 September 2026:

    - Powerball pool grew from 1-10 to 1-14 (four new balls: 11-14)
    - New Powerball Division 8 (fixed $12 prize)
    - Division 1 odds changed from 1 in 38,383,800 to 1 in 53,737,320
    - Jackpot range changed from $4M-$50M to $5M-$60M

Draws before POWERBALL_CHANGE_DATE are valid only with Powerball 1-10;
draws on or after it are valid with Powerball 1-14.

Everything that validates, generates, or models Powerball values should take
its era boundaries from here instead of hardcoding 10 or 14.
"""

from __future__ import annotations

from datetime import date, datetime

#: First draw under the new (1-14 Powerball) rules.
POWERBALL_CHANGE_DATE = date(2026, 9, 16)

#: Maximum Powerball value in each era.
POWERBALL_MAX_OLD = 10
POWERBALL_MAX_NEW = 14

# --- Prize structure by era (Lotto Rules 2025 rule 30, as amended by the
# --- Lotto Amendment Rules 2026, SL 2026/51) ---
#: Fixed prize per Powerball Division 7 winner before the change (was $15).
PB_DIV7_FIXED_PRE = 15.0
#: Fixed prize per Powerball Division 7 winner from the change ($20, plus the
#: winner also receives a Lotto bonus ticket — cash component modelled here).
PB_DIV7_FIXED_POST = 20.0
#: Fixed prize per Powerball Division 8 winner (new division, $12).
#: Division 8 = Powerball + 2 main numbers + the bonus number.
PB_DIV8_FIXED_POST = 12.0

#: Division 1 odds per line: C(40,6) x pool size.
DIV1_ODDS_PRE = 38_383_800  # C(40,6) x 10
DIV1_ODDS_POST = 53_737_320  # C(40,6) x 14


def powerball_era(draw_date: date | datetime | str) -> str:
    """Return the rule-era tag for a draw date.

    ``'pre_2026_09_16'`` for draws before the first new-rules draw,
    ``'post_2026_09_16'`` for draws on/after it.
    """
    d = parse_draw_date(draw_date)
    if d >= POWERBALL_CHANGE_DATE:
        return "post_2026_09_16"
    return "pre_2026_09_16"


def pb_fixed_prizes(draw_date: date | datetime | str) -> dict[int, float]:
    """Return the fixed (non-parimutuel) Powerball prizes for a draw date.

    Pre-change: only Division 7 exists ($15). Post-change: Division 7 pays
    $20 and the new Division 8 pays $12. Division 8 did not exist before
    2026-09-16, so it is absent (not zero) in the pre-change mapping.
    """
    if powerball_era(draw_date) == "post_2026_09_16":
        return {7: PB_DIV7_FIXED_POST, 8: PB_DIV8_FIXED_POST}
    return {7: PB_DIV7_FIXED_PRE}

#: Accepted draw-date string formats (ISO plus MyLotto page formats).
_DATE_FORMATS = ("%Y-%m-%d", "%A, %d %B %Y", "%d %B %Y")


def parse_draw_date(value: date | datetime | str) -> date:
    """Parse a draw date from a date/datetime or a string.

    Accepts ISO ``YYYY-MM-DD`` and MyLotto page formats
    (``"Wednesday, 16 September 2026"``, ``"16 September 2026"``).

    Raises
    ------
    ValueError
        If the value cannot be parsed. Never guess at an era.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"Unparseable draw date: {value!r}")


def powerball_max_for_date(draw_date: date | datetime | str) -> int:
    """Return the maximum valid Powerball number for a draw date."""
    d = parse_draw_date(draw_date)
    if d >= POWERBALL_CHANGE_DATE:
        return POWERBALL_MAX_NEW
    return POWERBALL_MAX_OLD


def validate_powerball(powerball: int, draw_date: date | datetime | str) -> int:
    """Validate a Powerball value against the rules in force on ``draw_date``.

    Returns
    -------
    int
        The validated Powerball value.

    Raises
    ------
    ValueError
        If the value is not an integer in ``1..max`` for the draw's era.
        The message states the valid range for that date — never clamp.
    """
    if not isinstance(powerball, int) or isinstance(powerball, bool):
        raise ValueError(f"Powerball must be an integer, got {powerball!r}")
    d = parse_draw_date(draw_date)
    max_pb = POWERBALL_MAX_NEW if d >= POWERBALL_CHANGE_DATE else POWERBALL_MAX_OLD
    if not 1 <= powerball <= max_pb:
        raise ValueError(
            f"Powerball {powerball} out of range for draw {d} "
            f"(valid 1-{max_pb} on that date; 1-{POWERBALL_MAX_OLD} before "
            f"{POWERBALL_CHANGE_DATE}, 1-{POWERBALL_MAX_NEW} on/after)"
        )
    return powerball
