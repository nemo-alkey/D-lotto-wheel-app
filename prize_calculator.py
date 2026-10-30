#!/usr/bin/env python3
"""
prize_calculator.py — Fetch real NZ Lotto Powerball division payouts from the
official MyLotto API and calculate exact prizes for a given ticket.

Supports the official NZ Lotto Powerball division rules including the bonus ball.

Pre-2026-09-16 divisions (Powerball pool 1-10):

  Div 1: 6 main + PB                    (bonus irrelevant)
  Div 2: 5 main + bonus + PB
  Div 3: 5 main + PB                    (bonus irrelevant — no upgrade)
  Div 4: 4 main + bonus + PB
  Div 5: 4 main + PB                    (bonus irrelevant)
  Div 6: 3 main + bonus + PB
  Div 7: 3 main + PB                    (bonus irrelevant)

From the first new-rules draw on 2026-09-16 (Powerball pool 1-14) an eighth
division was added (Lotto Amendment Rules 2026, SL 2026/51, rule 30(1)(h)):

  Div 8: 2 main + bonus + PB            fixed prize $12
  Div 7 fixed prize increased $15 -> $20 (plus a Lotto bonus ticket).

Division resolution is era-aware: pass ``draw_date`` so that Division 8 is
only awarded for draws on/after 2026-09-16. A ``draw_date`` of None means
"the rules currently in force" (post-change).

API: https://pathway.mylotto.co.nz/api/results/v1/results/lotto

Usage:
    from prize_calculator import get_prize_for_draw

    info = get_prize_for_draw([11,12,17,22,28,32], 3, bonus_matched=True)
    # Returns: {"total_prize": 47445.0, "main_prize": 21736.0, ...}

    info = get_prize_for_draw([11,12,17,22,28,32], 3, draw_date="2026-05-06")
    # Same, but scoped to a specific draw's payouts.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any, cast

# --- Load settings (centralised configuration) ---
try:
    from settings import settings as _st

    CACHE_FILE = _st.prize_cache_file
    CACHE_TTL = timedelta(days=_st.cache_ttl_days)
    API_BASE = _st.api_base
    API_LATEST = f"{API_BASE}/api/results/v1/results/lotto"
    API_SPECIFIC = f"{API_BASE}/api/results/v1/results/lotto/{{draw_number}}"
    REQUEST_TIMEOUT = _st.api_timeout
    FALLBACK_LOTTO = _st.fallback_lotto
    FALLBACK_PB = _st.fallback_pb
except ImportError:
    CACHE_FILE = "prize_cache.json"
    CACHE_TTL = timedelta(days=7)
    API_BASE = "https://pathway.mylotto.co.nz"
    API_LATEST = f"{API_BASE}/api/results/v1/results/lotto"
    API_SPECIFIC = f"{API_BASE}/api/results/v1/results/lotto/{{draw_number}}"
    REQUEST_TIMEOUT = 15
    FALLBACK_LOTTO = {
        1: 1_000_000.0,
        2: 30_000.0,
        3: 1_000.0,
        4: 100.0,
        5: 60.0,
        6: 40.0,
        7: 20.0,
    }
    FALLBACK_PB = {
        1: 0.0,
        2: 0.0,
        3: 0.0,
        4: 0.0,
        5: 0.0,
        6: 0.0,
        7: 0.0,
    }


def _fallback_pb_prizes(draw_date: str | None) -> dict[int, float]:
    """Static Powerball fallback prizes (API unavailable), era-aware.

    Parimutuel divisions (1-6) are unknown in fallback mode and stay 0.0;
    the fixed divisions (7 and, post-change, 8) are known exactly from the
    rules. ``draw_date=None`` means the rules currently in force.
    """
    from typing import Any as _Any
    from typing import cast as _cast

    from powerball_rules import POWERBALL_CHANGE_DATE, pb_fixed_prizes

    prizes = dict(FALLBACK_PB)
    effective = draw_date if draw_date is not None else POWERBALL_CHANGE_DATE
    prizes.update(pb_fixed_prizes(_cast(_Any, effective)))
    return prizes


# ---------------------------------------------------------------------------
# Division resolver — official NZ Lotto Powerball rules
# ---------------------------------------------------------------------------


def resolve_divisions(
    main_matches: int,
    bonus_match: bool,
    pb_hit: bool,
    draw_date: str | None = None,
) -> tuple[int | None, int | None]:
    """Map match counts to API division numbers.

    Official NZ Lotto Powerball division rules:

        main  bonus  PB   Lotto Div   PB Div   Label
         6     any   yes       1          1     Div 1 (6+PB)
         6     any   no        1         --     Div 1 (6)
         5     yes   yes       2          2     Div 2 (5+bonus+PB)
         5     any   yes       3          3     Div 3 (5+PB)
         5     yes   no        2         --     Div 2 (5+bonus)
         5     any   no        3         --     Div 3 (5)
         4     yes   yes       4          4     Div 4 (4+bonus+PB)
         4     any   yes       5          5     Div 5 (4+PB)
         4     yes   no        4         --     Div 4 (4+bonus)
         4     any   no        5         --     Div 5 (4)
         3     yes   yes       6          6     Div 6 (3+bonus+PB)
         3     any   yes       7          7     Div 7 (3+PB)
         3     yes   no        6         --     Div 6 (3+bonus)
         3     any   no        7         --     Div 7 (3)

    Era rule (Lotto Amendment Rules 2026, SL 2026/51, rule 30(1)(h)): for
    draws on/after 2026-09-16, a ticket with 2 main numbers + the bonus
    number + the Powerball wins Powerball Division 8 (Lotto division: none):

         2     yes   yes      --          8     Div 8 (2+bonus+PB), $12 fixed

    ``draw_date`` (YYYY-MM-DD) selects the era. ``None`` means the rules
    currently in force (post-change). Division 8 never applies to
    pre-change draws, and a 2-main ticket without the bonus never wins
    Division 8 in any era.

    Returns (lotto_division, pb_division) where None means no win for that
    component.
    """
    from powerball_rules import POWERBALL_CHANGE_DATE, parse_draw_date

    post_change = (
        parse_draw_date(draw_date) >= POWERBALL_CHANGE_DATE
        if draw_date is not None
        else True  # None = rules currently in force
    )

    # --- Division 8 (new rules only): 2 main + bonus + PB ---
    # Must be checked before the < 3 main early return — a 2-main ticket is
    # no longer automatically a loss when it matches the Div 8 pattern.
    if main_matches == 2 and pb_hit and bonus_match and post_change:
        return (None, 8)

    if main_matches < 3:
        return (None, None)

    # --- 6 main numbers ---
    if main_matches >= 6:
        return (1, 1 if pb_hit else None)

    # --- 5 main numbers ---
    if main_matches == 5:
        if bonus_match:
            return (2, 2 if pb_hit else None)  # Div 2
        else:
            return (3, 3 if pb_hit else None)  # Div 3

    # --- 4 main numbers ---
    if main_matches == 4:
        if bonus_match:
            return (4, 4 if pb_hit else None)  # Div 4
        else:
            return (5, 5 if pb_hit else None)  # Div 5

    # --- 3 main numbers ---
    if main_matches == 3:
        if bonus_match:
            return (6, 6 if pb_hit else None)  # Div 6
        else:
            return (7, 7 if pb_hit else None)  # Div 7

    return (None, None)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def _fetch_raw() -> dict[str, Any] | None:
    """Fetch the latest draw's full payload from the MyLotto API.

    Returns the parsed JSON dict, or None on failure.
    """
    import requests

    try:
        resp = requests.get(API_LATEST, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return cast(dict[str, Any], resp.json())
    except Exception as exc:
        print(f"  [prize_calculator] API fetch failed: {exc}", file=sys.stderr)
        return None


def _fetch_raw_by_draw_number(draw_number: int) -> dict[str, Any] | None:
    """Fetch a specific draw by its draw number."""
    import requests

    try:
        url = API_SPECIFIC.format(draw_number=draw_number)
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
        return cast(dict[str, Any], resp.json())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _money_to_float(value: Any) -> float:
    """Parse a prize value that may combine cash and a bonus ticket.

    The MyLotto API returns combined prize strings such as ``"12.00"``,
    ``"Bonus Ticket"``, ``"Bonus Ticket + 20.00"`` (post-change Powerball
    Div 7), or ``"POWERBALL ROLLOVER"``. Returns the cash component as a
    float, or 0.0 when there is no cash amount. Never guesses: unparseable
    non-empty strings return 0.0 and are indistinguishable from a genuine
    zero, so callers treat API data as authoritative.
    """
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text or text in ("Bonus Ticket", "POWERBALL ROLLOVER", "ROLLOVER"):
        return 0.0
    # Take the last numeric token: "Bonus Ticket + 20.00" -> 20.00
    token = text.split("+")[-1].strip().replace(",", "")
    try:
        return float(token)
    except ValueError:
        return 0.0


def _parse_payouts(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract lotto and powerball division payouts from an API response.

    Returns dict with keys:
      - lotto: dict mapping division (1-7) -> prize_value (float)
      - powerball: dict mapping division (1-8) -> combined_prize_value (float)
      - draw_date: str
      - draw_number: int
    """
    lotto = raw.get("lotto", {})
    pb = raw.get("powerBall", {})

    lotto_winners = lotto.get("lottoWinners", [])
    pb_winners = pb.get("powerballWinners", [])

    lotto_payouts: dict[int, float] = {}
    for div in lotto_winners:
        d = div["division"]
        lotto_payouts[d] = _money_to_float(div.get("prizeValue", "0"))

    pb_payouts: dict[int, float] = {}
    for div in pb_winners:
        d = div["division"]
        combined = div.get("combinedPrizeValue", "0")
        if combined in ("POWERBALL ROLLOVER", "ROLLOVER", None, ""):
            pb_payouts[d] = 0.0  # undefined until drawn
        else:
            pb_payouts[d] = _money_to_float(combined)

    return {
        "lotto": lotto_payouts,
        "powerball": pb_payouts,
        "draw_date": lotto.get("drawDate", ""),
        "draw_number": lotto.get("drawNumber", 0),
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _load_cache() -> dict[str, Any]:
    """Load cached payout data. Returns empty dict if missing or stale."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE) as f:
            cached = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    cached_at_str = cached.get("cached_at", "")
    if not cached_at_str:
        return {}

    try:
        cached_at = datetime.fromisoformat(cached_at_str)
    except (ValueError, TypeError):
        return {}

    if datetime.now() - cached_at > CACHE_TTL:
        return {}  # stale

    return cast(dict[str, Any], cached)


def _save_cache(payouts: dict[str, Any]) -> None:
    """Save payout data to cache file."""
    cache = _load_cache()
    draws = cache.get("draws", {})
    draws[payouts["draw_date"]] = {
        "lotto": payouts["lotto"],
        "powerball": payouts["powerball"],
        "draw_number": payouts["draw_number"],
    }
    cache["draws"] = draws
    cache["cached_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_payouts(draw_date: str | None = None) -> dict[str, Any] | None:
    """Fetch division payouts for a specific draw date (or latest if None).

    1. Check cache for the requested draw_date.
    2. If not cached, fetch from API.
    3. Save to cache for future use.

    Returns dict with 'lotto', 'powerball', 'draw_date', 'draw_number'
    keys, or None on failure.
    """
    # Check cache first
    cache = _load_cache()
    if draw_date and cache:
        cached = cache.get("draws", {}).get(draw_date)
        if cached:
            return {
                "lotto": {int(k): v for k, v in cached["lotto"].items()},
                "powerball": {int(k): v for k, v in cached["powerball"].items()},
                "draw_date": draw_date,
                "draw_number": cached.get("draw_number", 0),
            }

    # Fetch from API
    if draw_date:
        raw = _fetch_raw()
        if not raw:
            return None
        parsed = _parse_payouts(raw)
        _save_cache(parsed)
        if parsed["draw_date"] == draw_date:
            return parsed

        dn = parsed["draw_number"] - 1
        while dn > 0:
            raw = _fetch_raw_by_draw_number(dn)
            if not raw:
                dn -= 1
                continue
            parsed = _parse_payouts(raw)
            _save_cache(parsed)
            if parsed["draw_date"] == draw_date:
                return parsed
            dn -= 1

        return None

    raw = _fetch_raw()
    if not raw:
        return None
    parsed = _parse_payouts(raw)
    _save_cache(parsed)
    return parsed


def get_prize_for_draw(
    draw_numbers: list[int],
    pb: int,
    bonus_matched: bool = False,
    draw_date: str | None = None,
) -> dict[str, Any]:
    """Calculate the exact prize for a ticket against a specific draw.

    Args:
        draw_numbers: List of 6 main numbers drawn.
        pb: Powerball number. Valid range is era-dependent: 1-10 before
            2026-09-16, 1-14 on/after (1-14 when draw_date is None).
        bonus_matched: Whether the bonus ball was matched.
        draw_date: Draw date string (YYYY-MM-DD). If None, uses latest draw.

    Returns:
        Dict with:
          - total_prize: float
          - main_prize: float — lotto component
          - pb_prize: float — Powerball component (0 if PB missed)
          - main_division: int — lotto division (1-7)
          - pb_division: int or None — powerball division
          - main_label: str — human-readable division label
          - pb_label: str or None
          - is_estimated: bool — True if using static fallback
          - draw_date: str
          - details: list of (label, amount) for display
    """
    if len(draw_numbers) != 6 or len(set(draw_numbers)) != 6:
        raise ValueError("draw_numbers must be a list of 6 unique integers.")
    # Era-aware Powerball range: 1-10 before 2026-09-16, 1-14 on/after.
    from powerball_rules import powerball_max_for_date

    max_pb = powerball_max_for_date(draw_date) if draw_date else 14
    if not 1 <= pb <= max_pb:
        raise ValueError(
            f"pb {pb} out of range for draw {draw_date or 'current rules'} " f"(valid 1-{max_pb})."
        )

    payouts = fetch_payouts(draw_date)
    is_estimated = payouts is None

    if payouts is None:
        lotto_payouts = FALLBACK_LOTTO
        pb_payouts = _fallback_pb_prizes(draw_date)
        draw_date_str = draw_date or "unknown"
    else:
        lotto_payouts = payouts["lotto"]
        pb_payouts = payouts["powerball"]
        draw_date_str = payouts["draw_date"]

    # Resolve divisions based on 6 main matches (era-irrelevant at 6 mains)
    lotto_div, pb_div = resolve_divisions(6, bonus_matched, True, draw_date=draw_date)

    main_prize = lotto_payouts.get(lotto_div, 0.0) if lotto_div else 0.0

    pb_division = None
    pb_prize = 0.0
    pb_label = None
    if pb_div is not None:
        pb_division = pb_div
        pb_prize = pb_payouts.get(pb_div, 0.0)
        pb_label = f"PB Div {pb_div}"

    total = main_prize + pb_prize
    main_labels = {
        1: "Div 1 (6)",
        2: "Div 2 (5+bonus)",
        3: "Div 3 (5)",
        4: "Div 4 (4+bonus)",
        5: "Div 5 (4)",
        6: "Div 6 (3+bonus)",
        7: "Div 7 (3)",
    }

    details = [
        (
            f"Lotto {main_labels.get(cast(int, lotto_div), f'Div {lotto_div}')}",
            main_prize,
        ),
    ]
    if pb_prize > 0:
        details.append((f"Powerball {pb_label}", pb_prize))

    return {
        "total_prize": total,
        "main_prize": main_prize,
        "pb_prize": pb_prize,
        "main_division": lotto_div,
        "pb_division": pb_division,
        "main_label": main_labels.get(cast(int, lotto_div), f"Div {lotto_div} (no win)"),
        "pb_label": pb_label,
        "is_estimated": is_estimated,
        "draw_date": draw_date_str,
        "details": details,
    }


def get_prize_for_matches(
    main_matches: int,
    bonus_match: bool,
    pb_hit: bool,
    draw_date: str | None = None,
) -> dict[str, Any]:
    """Calculate prize for a ticket given match counts (not actual numbers).

    Official NZ Lotto Powerball division rules:

      Div 1: 6 main + PB                    (bonus irrelevant)
      Div 2: 5 main + bonus + PB
      Div 3: 5 main + PB                    (bonus irrelevant — no upgrade)
      Div 4: 4 main + bonus + PB
      Div 5: 4 main + PB                    (bonus irrelevant)
      Div 6: 3 main + bonus + PB
      Div 7: 3 main + PB                    (bonus irrelevant)
      Div 8: 2 main + bonus + PB   (draws on/after 2026-09-16 only, $12 fixed)

    Args:
        main_matches: Number of main numbers matched (0-6).
        bonus_match: Whether the bonus ball was matched.
        pb_hit: Whether the powerball matched.
        draw_date: Specific draw date (or None for latest). The era of this
            date decides whether Division 8 can apply; None means the rules
            currently in force.

    Returns:
        Same structure as get_prize_for_draw().  The 'is_estimated' flag
        indicates whether static fallback values were used.
    """
    payouts = fetch_payouts(draw_date)
    is_estimated = payouts is None

    if payouts is None:
        lotto_payouts = FALLBACK_LOTTO
        pb_payouts = _fallback_pb_prizes(draw_date)
        draw_date_str = draw_date or "unknown"
    else:
        lotto_payouts = payouts["lotto"]
        pb_payouts = payouts["powerball"]
        draw_date_str = payouts["draw_date"]

    # Resolve divisions using official rules (era-aware via draw_date; the
    # fetched draw's date when the caller did not specify one)
    era_date = draw_date or (draw_date_str if draw_date_str != "unknown" else None)
    lotto_div, pb_div = resolve_divisions(main_matches, bonus_match, pb_hit, draw_date=era_date)

    main_prize = lotto_payouts.get(lotto_div, 0.0) if lotto_div else 0.0

    main_labels = {
        1: "Div 1 (6)",
        2: "Div 2 (5+bonus)",
        3: "Div 3 (5)",
        4: "Div 4 (4+bonus)",
        5: "Div 5 (4)",
        6: "Div 6 (3+bonus)",
        7: "Div 7 (3)",
    }

    pb_division: int | None = None
    pb_prize = 0.0
    pb_label: str | None = None
    if pb_hit and pb_div is not None:
        pb_division = pb_div
        pb_prize = pb_payouts.get(pb_div, 0.0)
        pb_label = f"PB Div {pb_div}"

    total = main_prize + pb_prize

    details = [
        (
            f"Lotto {main_labels.get(cast(int, lotto_div), f'Div {lotto_div}')}",
            main_prize,
        )
    ]
    if pb_prize > 0:
        details.append((f"Powerball {pb_label}", pb_prize))

    # Human-readable combined label
    if lotto_div is None and pb_div is None:
        combined_label = "No win"
    elif lotto_div is not None and pb_div is not None:
        combined_label = f"Div {lotto_div}+PB"
    elif pb_div is not None:
        combined_label = f"PB Div {pb_div}"
    else:
        combined_label = f"Div {lotto_div}"

    return {
        "total_prize": total,
        "main_prize": main_prize,
        "pb_prize": pb_prize,
        "main_division": lotto_div,
        "pb_division": pb_division,
        "main_label": main_labels.get(lotto_div, f"Div {lotto_div}") if lotto_div else "No win",
        "pb_label": pb_label,
        "combined_label": combined_label,
        "is_estimated": is_estimated,
        "draw_date": draw_date_str,
        "details": details,
        "main_matches": main_matches,
        "bonus_match": bonus_match,
        "pb_hit": pb_hit,
    }


# ===========================================================================
# Lotto-Only Prize Calculation (no Powerball)
# ===========================================================================

# Pool share percentages from settings (or fallback)
try:
    LOTTO_POOL_PERCENTAGES = _st.lotto_pool_percentages
    DEFAULT_LOTTO_POOL = _st.default_lotto_pool
except NameError:
    LOTTO_POOL_PERCENTAGES: dict[int, float] = {  # type: ignore[no-redef]  # settings fallback
        1: 34.6,
        2: 10.1,
        3: 10.5,
        4: 2.5,
        5: 21.5,
        6: 20.8,
        7: 0.0,
    }
    DEFAULT_LOTTO_POOL = 215_000.0


def calculate_lotto_only_prize(
    main_matches: int,
    bonus_matched: bool,
    pool_amount: float = DEFAULT_LOTTO_POOL,
) -> dict[str, Any]:
    """Calculate Lotto-only prize ignoring Powerball entirely.

    Uses the Standard Lotto division rules where the bonus ball still
    upgrades: 5→Div2, 4→Div4, 3→Div6.  Powerball is never matched.

    Parameters
    ----------
    main_matches : int
        Number of main numbers matched (0-6).
    bonus_matched : bool
        Whether the bonus ball was matched.
    pool_amount : float
        Estimated Lotto prize pool in NZD (default $215,000).

    Returns
    -------
    dict
        Keys: division, division_label, prize, main_matches, bonus_matched.
    """
    # Resolve the Lotto division (same rules as resolve_divisions but PB never hits)
    lotto_div, _ = resolve_divisions(main_matches, bonus_matched, False)

    if lotto_div is None:
        return {
            "division": None,
            "division_label": "No win",
            "prize": 0.0,
            "main_matches": main_matches,
            "bonus_matched": bonus_matched,
        }

    pct = LOTTO_POOL_PERCENTAGES.get(lotto_div, 0.0)
    prize = round(pool_amount * pct / 100.0, 2)

    labels = {
        1: "Div 1 (6)",
        2: "Div 2 (5+bonus)",
        3: "Div 3 (5)",
        4: "Div 4 (4+bonus)",
        5: "Div 5 (4)",
        6: "Div 6 (3+bonus)",
        7: "Div 7 (3)",
    }

    return {
        "division": lotto_div,
        "division_label": labels.get(lotto_div, f"Div {lotto_div}"),
        "prize": prize,
        "main_matches": main_matches,
        "bonus_matched": bonus_matched,
    }


# ===========================================================================
# Pool allocation — realistic multi-winner prize modelling
# ===========================================================================

# Powerball pool percentages (from settings or fallback)
try:
    PB_POOL_PERCENTAGES = _st.pb_pool_percentages
    LOTTO_ALLOC_PERCENTAGES = _st.lotto_pool_percentages
    DIV7_PB_PRIZE = _st.div7_pb_prize  # pre-change fixed prize ($15)
    DIV7_LOTTO_PRIZE = _st.div7_lotto_prize
    DIV1_CAP = _st.div1_cap
    DEFAULT_RESERVE_RATE = _st.reserve_powerball
except NameError:
    PB_POOL_PERCENTAGES: dict[int, float] = {  # type: ignore[no-redef]  # settings fallback
        1: 85.74,
        2: 2.23,
        3: 2.23,
        4: 0.60,
        5: 4.64,
        6: 4.56,
        7: 0.0,
    }
    LOTTO_ALLOC_PERCENTAGES: dict[int, float] = {  # type: ignore[no-redef]  # settings fallback
        1: 34.6,
        2: 10.1,
        3: 10.5,
        4: 2.5,
        5: 21.5,
        6: 20.8,
        7: 0.0,
    }
    DIV7_PB_PRIZE = 15.0
    DIV7_LOTTO_PRIZE = 2.80
    DIV1_CAP = 50_000_000.0
    DEFAULT_RESERVE_RATE = 0.25

# Post-change fixed prizes (Lotto Amendment Rules 2026): Div 7 -> $20 and the
# new Div 8 -> $12. Kept in sync with powerball_rules.pb_fixed_prizes().
from powerball_rules import POWERBALL_CHANGE_DATE, pb_fixed_prizes

DIV7_PB_PRIZE_POST = pb_fixed_prizes(POWERBALL_CHANGE_DATE)[7]  # $20
DIV8_PB_PRIZE_POST = pb_fixed_prizes(POWERBALL_CHANGE_DATE)[8]  # $12


def _pb_fixed_prizes_for(draw_date: str | None) -> dict[int, float]:
    """Fixed Powerball prizes for ``allocate_pool``.

    ``draw_date=None`` means the rules currently in force (post-change) —
    ``allocate_pool`` models a game played under a known rule set, so the
    current rules are the correct default for forward simulations.
    """
    from typing import Any as _Any
    from typing import cast as _cast

    effective = draw_date if draw_date is not None else POWERBALL_CHANGE_DATE
    return pb_fixed_prizes(_cast(_Any, effective))


def allocate_pool(
    total_turnover: float,
    winners_per_division: dict[int, int] | None = None,
    game: str = "powerball",
    reserve_rate: float | None = None,
    div1_cap: float | None = None,
    draw_date: str | None = None,
) -> dict[str, Any]:
    """Allocate prize pool across divisions with realistic NZ Lotto rules.

    Models the official prize allocation mechanics:
    1. Deducts reserve / operating costs from turnover.
    2. Pays the fixed Powerball prizes first (Div 7, plus Div 8 post-change).
    3. Splits the remaining pool among Div 1–6 by official percentages.
    4. Caps Div 1 at $50M; excess goes to the reserve fund.
    5. If a division has 0 winners, its allocation rolls down to the
       next lower division(s).

    Parameters
    ----------
    total_turnover : float
        Total ticket sales revenue for the draw (NZD).
    winners_per_division : dict[int, int] or None
        Number of winners per division {1: n1, 2: n2, ..., 7: n7}
        (Powerball may also include 8 for post-change draws).
        Divisions with no entry are treated as 0 winners.
        If None, defaults to 0 winners for every division.
    game : str
        Either "powerball" (default) or "lotto".
    reserve_rate : float or None
        Fraction of turnover reserved for operating costs and grants.
        Default: 0.25 (25%).
    div1_cap : float or None
        Maximum Div 1 payout in NZD.  Default: $50,000,000 for Powerball,
        None for Lotto (no cap).
    draw_date : str or None
        Draw date (YYYY-MM-DD) selecting the Powerball rule era for the
        fixed prizes: Div 7 = $15 pre-change, $20 + Div 8 = $12 post-change.
        None means the rules currently in force (post-change).

    Returns
    -------
    dict
        Keys:
          - total_turnover: float
          - reserve_deduction: float
          - prize_pool: float — after reserve
          - fixed_total: float — total paid to fixed-prize winners
          - div7_fixed_total: float — total paid to Div 7 winners
            (kept for backward compatibility; 0 for lotto game)
          - remaining_pool: float — pool split among Div 1–6
          - per_winner: dict[int, float] — prize per winner per division
          - total_per_division: dict[int, float] — total prize per division
          - div1_capped: bool — whether Div 1 hit the cap
          - excess_to_reserve: float — Div 1 overflow (if capped)
          - game: str
    """
    if winners_per_division is None:
        winners_per_division = {}

    # Default parameters by game type
    if reserve_rate is None:
        reserve_rate = DEFAULT_RESERVE_RATE
    if div1_cap is None:
        div1_cap = DIV1_CAP if game == "powerball" else None

    if game == "powerball":
        pool_pcts = PB_POOL_PERCENTAGES
        fixed_prizes = _pb_fixed_prizes_for(draw_date)
    else:
        pool_pcts = LOTTO_ALLOC_PERCENTAGES
        fixed_prizes = {7: DIV7_LOTTO_PRIZE}
        pool_pcts = LOTTO_ALLOC_PERCENTAGES

    # --- Step 1: Deduct reserve ---
    reserve_deduction = round(total_turnover * reserve_rate, 2)
    prize_pool = round(total_turnover - reserve_deduction, 2)

    # --- Step 2: Pay fixed prizes first (Powerball Div 7, plus Div 8
    # --- post-change; Lotto Div 7 bonus ticket) ---
    fixed_payouts: dict[int, float] = {}
    fixed_total = 0.0
    for div, fixed_prize in fixed_prizes.items():
        n = winners_per_division.get(div, 0)
        if n > 0:
            fixed_payouts[div] = round(n * fixed_prize, 2)
            fixed_total += fixed_payouts[div]
    # Backward-compat alias: Div 7 fixed total (0 for lotto game).
    div7_fixed_total = fixed_payouts.get(7, 0.0)

    if prize_pool < fixed_total:
        # Edge case: pool too small to cover fixed prizes; pay what we can
        fixed_total = prize_pool
        remaining_pool = 0.0
    else:
        remaining_pool = round(prize_pool - fixed_total, 2)

    # --- Step 3: Split remaining pool by percentage (with roll-down) ---
    # Divisions 1–6 get percentage allocations; if a division has 0 winners,
    # its share rolls down to the next lower division.

    per_winner: dict[int, float] = {}
    total_per_division: dict[int, float] = {}

    div1_was_capped = False
    excess_from_cap = 0.0

    if remaining_pool > 0:
        # Start with unallocated = remaining_pool
        unallocated = remaining_pool

        # Roll-down: go through divisions 1→6; allocate each division's
        # percentage of the *original* remaining pool, but if that division
        # has 0 winners, the money stays in the pool for lower divisions.
        for div in range(1, 7):
            pct = pool_pcts.get(div, 0.0)
            raw_share = round(remaining_pool * pct / 100.0, 2)

            n_winners = winners_per_division.get(div, 0)

            if n_winners > 0 and raw_share > 0:
                # --- Div 1 cap check ---
                if div == 1 and div1_cap is not None:
                    per_winner_raw = raw_share / n_winners
                    if per_winner_raw > div1_cap:
                        # Cap each winner; excess goes to reserve, NOT unallocated
                        div1_was_capped = True
                        capped_total = div1_cap * n_winners
                        excess_from_cap = round(raw_share - capped_total, 2)
                        total_per_division[div] = round(capped_total, 2)
                        per_winner[div] = round(div1_cap, 2)
                        unallocated -= capped_total
                        # excess_from_cap stays out of unallocated (goes to reserve)
                        continue

                # Normal allocation
                per_winner[div] = round(raw_share / n_winners, 2)
                total_per_division[div] = raw_share
                unallocated -= raw_share

            elif n_winners == 0 and raw_share > 0:
                # No winners in this division → roll down
                # (money stays in unallocated and is effectively added to
                #  the pool for lower divisions)
                pass  # keeps raw_share in unallocated

        # If any money remains unallocated after Div 6, distribute it
        # proportionally among divisions that have winners.
        # Exclude Div 1 from redistribution if it was capped.
        if unallocated > 0:
            winning_divs = [
                d
                for d in range(1, 7)
                if winners_per_division.get(d, 0) > 0 and not (d == 1 and div1_was_capped)
            ]
            if winning_divs:
                total_winners = sum(winners_per_division.get(d, 0) for d in winning_divs)
                for d in winning_divs:
                    n = winners_per_division.get(d, 0)
                    extra = round(unallocated * n / total_winners, 2)
                    per_winner[d] = round(per_winner.get(d, 0.0) + extra / n, 2)
                    total_per_division[d] = round(total_per_division.get(d, 0.0) + extra, 2)
                    unallocated -= extra

        # Any final leftover pennies go to Div 1 if uncapped and has winners
        if unallocated > 0.005 and not div1_was_capped:
            d1_winners = winners_per_division.get(1, 0)
            if d1_winners > 0:
                per_winner[1] = round(per_winner.get(1, 0.0) + unallocated / d1_winners, 2)
                total_per_division[1] = round(total_per_division.get(1, 0.0) + unallocated, 2)
                unallocated = 0.0

    # --- Step 4: Fixed-prize divisions per-winner and total ---
    for div, fixed_prize in fixed_prizes.items():
        if winners_per_division.get(div, 0) > 0 and fixed_total > 0:
            per_winner[div] = round(fixed_prize, 2)
            total_per_division[div] = round(fixed_payouts.get(div, 0.0), 2)

    # --- Determine Div 1 capped status (use tracked values from allocation) ---
    div1_capped = div1_was_capped
    excess_to_reserve = excess_from_cap

    return {
        "total_turnover": total_turnover,
        "reserve_deduction": reserve_deduction,
        "prize_pool": prize_pool,
        "fixed_total": fixed_total,
        "div7_fixed_total": div7_fixed_total,
        "remaining_pool": remaining_pool,
        "per_winner": per_winner,
        "total_per_division": total_per_division,
        "div1_capped": div1_capped,
        "excess_to_reserve": excess_to_reserve,
        "game": game,
    }


# ===========================================================================
# Jackpot rollover — carry Div 1 prize forward across draws
# ===========================================================================


def apply_jackpot(
    allocation_result: dict[str, Any],
    carried_jackpot: float = 0.0,
    consecutive_no_div1: int = 0,
    max_consecutive: int | None = None,
    div1_cap: float | None = None,
) -> dict[str, Any]:
    """Apply jackpot rollover rules to a prize allocation.

    Simulates the official NZ Powerball jackpot mechanics:
    - If Div 1 has no winner, the Div 1 share rolls over as a "jackpot"
      into the next draw's Div 1 pool.
    - The jackpot accumulates across consecutive draws with no Div 1 winner.
    - Div 1 is capped at $50M per winner; excess goes to reserve.
    - After ``max_consecutive`` draws without a Div 1 winner, a "must-win"
      draw is forced: the jackpot cascades to the next lower division(s)
      with winners.

    Parameters
    ----------
    allocation_result : dict
        Output from ``allocate_pool()`` — must contain ``per_winner``,
        ``total_per_division``, ``remaining_pool``, and ``game``.
    carried_jackpot : float
        Jackpot amount carried forward from previous draws (NZD).
    consecutive_no_div1 : int
        Number of consecutive draws so far without a Div 1 winner.
    max_consecutive : int or None
        Maximum consecutive draws before a must-win draw.  Default from
        settings (``max_consecutive_jackpots``, typically 10).
    div1_cap : float or None
        Maximum Div 1 payout per winner.  Default from settings.

    Returns
    -------
    dict
        Keys:
          - per_winner: dict[int, float] — updated per-winner prizes
          - total_per_division: dict[int, float] — updated totals
          - carried_jackpot: float — jackpot carried to next draw
          - consecutive_no_div1: int — updated consecutive count
          - forced_distribution: bool — must-win draw triggered
          - jackpot_triggered: bool — jackpot was actually paid out
          - jackpot_amount: float — jackpot added to this draw's pool
    """
    # Load defaults
    if max_consecutive is None or div1_cap is None:
        try:
            from settings import settings as _st

            if max_consecutive is None:
                max_consecutive = _st.max_consecutive_jackpots
            if div1_cap is None:
                div1_cap = _st.div1_cap
        except ImportError:
            if max_consecutive is None:
                max_consecutive = 10
            if div1_cap is None:
                div1_cap = 50_000_000.0

    per_winner = dict(allocation_result.get("per_winner", {}))
    total_per_division = dict(allocation_result.get("total_per_division", {}))
    remaining_pool = float(allocation_result.get("remaining_pool", 0.0))

    # Count actual Div 1 winners from per_winner
    has_div1_winner = 1 in per_winner and per_winner[1] > 0

    forced_distribution = False
    jackpot_triggered = False
    jackpot_amount = carried_jackpot

    if has_div1_winner:
        # --- Div 1 hit: add carried jackpot to Div 1 pool ---
        jackpot_triggered = True
        # Actually get the count from allocation
        div1_winners_count = 0
        # The per_winner stores prize per winner; we can infer count from total
        d1_total = total_per_division.get(1, 0.0)
        if d1_total > 0 and per_winner.get(1, 0) > 0:
            div1_winners_count = max(1, round(d1_total / per_winner[1]))

        if div1_winners_count == 0:
            div1_winners_count = 1

        # Add jackpot to Div 1 pool
        boosted_d1 = d1_total + carried_jackpot
        per_winner_raw = boosted_d1 / div1_winners_count

        if per_winner_raw > div1_cap:
            # Cap each winner
            per_winner[1] = round(div1_cap, 2)
            total_per_division[1] = round(div1_cap * div1_winners_count, 2)
            # Excess to reserve  (not carried forward)
        else:
            per_winner[1] = round(per_winner_raw, 2)
            total_per_division[1] = round(boosted_d1, 2)

        # Reset consecutive count
        new_consecutive = 0
        new_carried_jackpot = 0.0

    else:
        # --- No Div 1 winner: roll over ---
        new_consecutive = consecutive_no_div1 + 1

        if new_consecutive >= max_consecutive:
            # Must-win draw: cascade jackpot to lower divisions
            forced_distribution = True
            jackpot_triggered = True

            # Find divisions with winners (2–8; Div 8 exists post-change)
            cascade_divs = [d for d in range(2, 9) if per_winner.get(d, 0) > 0]
            if cascade_divs:
                # We need actual winner counts — estimate from totals
                cascade_winner_counts: dict[int, int] = {}
                for d in cascade_divs:
                    td = total_per_division.get(d, 0.0)
                    pw = per_winner.get(d, 0.0)
                    if pw > 0:
                        cascade_winner_counts[d] = max(1, round(td / pw))
                    else:
                        cascade_winner_counts[d] = 1

                total_w = sum(cascade_winner_counts.values())
                distributed = 0.0
                for d in cascade_divs:
                    n = cascade_winner_counts[d]
                    share = round(carried_jackpot * n / total_w, 2)
                    per_winner[d] = round(per_winner.get(d, 0.0) + share / n, 2)
                    total_per_division[d] = round(total_per_division.get(d, 0.0) + share, 2)
                    distributed += share

                new_carried_jackpot = round(carried_jackpot - distributed, 2)
                new_consecutive = 0  # reset after forced distribution
            else:
                # No winners in any lower division either — carry forward
                new_carried_jackpot = carried_jackpot
                new_consecutive = 0  # reset even if no lower winners (jackpot was distributed)
        else:
            # Normal rollover: add Div 1 share from this draw to carried jackpot
            d1_share = total_per_division.get(1, 0.0)
            if d1_share == 0:
                # Compute from percentages
                try:
                    d1_share = round(remaining_pool * 0.8574, 2)
                except Exception:
                    d1_share = 0.0
            new_carried_jackpot = round(carried_jackpot + d1_share, 2)
            # Remove Div 1 from this draw's per_winner (no winners)
            per_winner.pop(1, None)
            total_per_division.pop(1, None)

    return {
        "per_winner": per_winner,
        "total_per_division": total_per_division,
        "carried_jackpot": new_carried_jackpot,
        "consecutive_no_div1": new_consecutive,
        "forced_distribution": forced_distribution,
        "jackpot_triggered": jackpot_triggered,
        "jackpot_amount": jackpot_amount,
    }


# ===========================================================================
# Lotto Strike — first 4 winning numbers in exact order
# ===========================================================================
#
# Strike divisions (Lotto Rules 2025, Part 4):
#   Div 1 (Strike Four):   all 4 numbers in exact order     → pool share
#   Div 2 (Strike Three):  first 3 numbers in exact order   → pool share
#   Div 3 (Strike Two):    first 2 numbers in exact order   → pool share
#   Div 4 (Strike One):    first number only in exact order → fixed prize
#
# The Strike pool is split 65% / 20% / 15% among Divs 1–3;
# Div 4 is a fixed prize (bonus selection).

STRIKE_LABELS: dict[int, str] = {
    1: "Strike Four  (4 exact)",
    2: "Strike Three (3 exact)",
    3: "Strike Two   (2 exact)",
    4: "Strike One   (1 exact)",
}


def get_strike_division(exact_matches: int) -> int | None:
    """Map the number of exact-position matches to a Strike division (1–4).

    Parameters
    ----------
    exact_matches : int
        Number of balls matched in exact position (0–4).

    Returns
    -------
    int or None
        Strike division number (1–4), or None if no win (< 1 match).
    """
    if exact_matches < 1 or exact_matches > 4:
        return None
    return {4: 1, 3: 2, 2: 3, 1: 4}[exact_matches]


def calculate_strike_prize(
    exact_matches: int,
    pool_amount: float | None = None,
) -> dict[str, Any]:
    """Calculate the Strike prize for a given number of exact matches.

    Parameters
    ----------
    exact_matches : int
        Number of balls matched in exact position (0–4).
        E.g. 3 means the first 3 numbers matched in order.
    pool_amount : float or None
        Estimated Strike prize pool in NZD.  If None, uses the default
        from settings (default_strike_pool ≈ $350,000).

    Returns
    -------
    dict
        Keys: division, division_label, exact_matches, prize, is_estimated.
    """
    # Load pool percentages and default pool from settings
    try:
        from settings import settings as _st

        strike_pcts = _st.strike_pool_percentages
        div4_fixed = _st.strike_div4_fixed
        if pool_amount is None:
            pool_amount = _st.default_strike_pool
    except ImportError:
        strike_pcts = {1: 65.0, 2: 20.0, 3: 15.0, 4: 0.0}
        div4_fixed = 1.00
        if pool_amount is None:
            pool_amount = 350_000.0

    division = get_strike_division(exact_matches)

    if division is None:
        return {
            "division": None,
            "division_label": "No win",
            "exact_matches": exact_matches,
            "prize": 0.0,
            "is_estimated": True,
        }

    # Div 4 is a fixed prize
    if division == 4:
        prize = div4_fixed
    else:
        pct = strike_pcts.get(division, 0.0)
        prize = round(pool_amount * pct / 100.0, 2)

    return {
        "division": division,
        "division_label": STRIKE_LABELS.get(division, f"Strike Div {division}"),
        "exact_matches": exact_matches,
        "prize": prize,
        "is_estimated": True,  # always estimated unless live API provides strike payouts
    }


def count_exact_matches(
    player_numbers: list[int],
    draw_numbers: list[int],
) -> int:
    """Count how many of the player's numbers match the draw in exact positions.

    Compares position-by-position from the start; stops at the first mismatch.

    Parameters
    ----------
    player_numbers : list[int]
        4 numbers chosen by the player (in order).
    draw_numbers : list[int]
        First 4 numbers drawn in the Lotto draw (in order).

    Returns
    -------
    int
        Number of consecutive exact-position matches (0–4).
    """
    count = 0
    for p, d in zip(player_numbers, draw_numbers, strict=False):
        if p == d:
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="NZ Lotto Powerball prize calculator.",
    )
    parser.add_argument(
        "--draw",
        required=True,
        help="6 comma-separated draw numbers",
    )
    parser.add_argument(
        "--pb",
        type=int,
        required=True,
        help="Powerball (1-10 before 2026-09-16, 1-14 on/after)",
    )
    parser.add_argument("--date", help="Draw date (YYYY-MM-DD) — defaults to latest")
    parser.add_argument(
        "--flush-cache",
        action="store_true",
        help="Delete cached payouts before fetching",
    )
    parser.add_argument(
        "--matches",
        type=int,
        help="(Alternative) Use main match count instead of draw numbers "
        "(for testing get_prize_for_matches)",
    )
    parser.add_argument(
        "--bonus",
        action="store_true",
        help="(With --matches) Bonus ball was matched",
    )
    parser.add_argument(
        "--no-pb",
        action="store_true",
        help="(With --matches) PB did NOT hit",
    )
    args = parser.parse_args()

    if args.flush_cache and os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
        print("Cache flushed.")

    if args.matches is not None:
        info = get_prize_for_matches(
            args.matches,
            bonus_match=args.bonus,
            pb_hit=not args.no_pb,
            draw_date=args.date,
        )
    else:
        try:
            nums = [int(x.strip()) for x in args.draw.split(",")]
        except ValueError:
            print("Error: --draw must be comma-separated integers.")
            sys.exit(1)
        if len(nums) != 6:
            print("Error: --draw must have exactly 6 numbers.")
            sys.exit(1)
        if not (1 <= args.pb <= 14):
            print("Error: --pb must be 1-14 (1-10 for draws before 2026-09-16).")
            sys.exit(1)

        info = get_prize_for_draw(nums, args.pb, draw_date=args.date)

    print()
    print("  === Prize Calculation ===")
    print(f"  Draw date:  {info['draw_date']}")
    print(f"  Source:     {'API (live)' if not info['is_estimated'] else 'Static estimate'}")
    print()
    for label, amount in info["details"]:
        if amount > 0:
            print(f"  {label:<20s}  ${amount:>8,.2f}")
        else:
            print(f"  {label:<20s}  No win")
    print(f"  {'─' * 32}")
    print(f"  {'Total':<20s}  ${info['total_prize']:>8,.2f}")
    print()


if __name__ == "__main__":
    main()
