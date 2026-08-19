#!/usr/bin/env python3
"""
backtest.py - Backtest a wheel against historical draws with live prize data.

Evaluates how a wheel would have performed over the last N draws:
  - Winning tickets per division
  - Guarantee hit rate
  - Total cost, prize, net profit/loss, ROI
  - Prize histogram per division

Fetches the latest division payouts from the MyLotto API once and reuses
them across all draws. Falls back to static estimates if the API is down.

Usage:
    python3 backtest.py --wheel double --draws 500
    python3 backtest.py --wheel jackpot7 --draws 1000
    python3 backtest.py --wheel single1            # default: all draws
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lotto_wheels import WHEELS, load_draws


# ---------------------------------------------------------------------------
# Progress callback -- used by Streamlit for progress bars
# ---------------------------------------------------------------------------
class ProgressCallback:
    """Simple callback for long-running computations to report progress."""

    def __init__(self, progress_bar: Any = None, total_steps: int = 100) -> None:
        self.progress_bar = progress_bar
        self.total_steps = total_steps

    def update(self, step: int, text: str = "") -> None:
        """Update progress to step/total_steps with an optional message."""
        if self.progress_bar is not None:
            self.progress_bar.progress(min(step / self.total_steps, 1.0), text=text)


# --- Load settings (centralised configuration) ---
try:
    from settings import settings as _st

    _TICKET_COST = _st.ticket_cost
    _FALLBACK_LOTTO = _st.fallback_lotto
    _FALLBACK_PB = _st.fallback_pb
    _DEFAULT_PB_TURNOVER = _st.default_powerball_turnover
except ImportError:
    _TICKET_COST = 1.50
    _FALLBACK_LOTTO = dict(_FALLBACK_LOTTO)
    _FALLBACK_PB = dict(_FALLBACK_PB)
    _DEFAULT_PB_TURNOVER = _DEFAULT_PB_TURNOVER

# ---------------------------------------------------------------------------
# Guarantee definitions per wheel
# ---------------------------------------------------------------------------
GUARANTEES: dict[str, tuple[str, Any, Any]] = {}


def _register_guarantees() -> None:
    """Populate GUARANTEES from wheel pool + ticket analysis."""
    for name, (tickets, _pb) in WHEELS.items():
        pool: set[int] = set()
        for t in tickets:
            pool.update(t)

        if name == "jackpot7":

            def cond(ov: int) -> bool:
                return ov >= 6

            def guar(matches: list[int], ov: int) -> bool:
                return any(m >= 6 for m in matches)

            desc = "6-win when all 6 draw numbers are in the pool"
        elif name == "five-if-six":

            def cond(ov: int) -> bool:
                return ov >= 6

            def guar(matches: list[int], ov: int) -> bool:
                return any(m >= 5 for m in matches)

            desc = "5-win when all 6 draw numbers are in the pool"
        elif name == "double":

            def cond(ov: int) -> bool:
                return ov >= 4

            def guar(matches: list[int], ov: int) -> bool:
                return sum(1 for m in matches if m >= 4) >= 2

            desc = "Two 4-wins when 4+ draw numbers are in the pool"
        else:  # single wheels

            def cond(ov: int) -> bool:
                return ov >= 4

            def guar(matches: list[int], ov: int) -> bool:
                return any(m >= 4 for m in matches)

            desc = "4-win when 4+ draw numbers are in the pool"

        GUARANTEES[name] = (desc, cond, guar)


# ---------------------------------------------------------------------------
# Bonus-aware division labels (matches prize_calculator numbering)
# ---------------------------------------------------------------------------

DIVISION_LABELS = {
    1: "Div 1 (6)",
    2: "Div 2 (5+bonus)",
    3: "Div 3 (5)",
    4: "Div 4 (4+bonus)",
    5: "Div 5 (4)",
    6: "Div 6 (3+bonus)",
    7: "Div 7 (3)",
}

PB_DIVISION_LABELS = {
    1: "PB Div 1",
    2: "PB Div 2",
    3: "PB Div 3",
    4: "PB Div 4",
    5: "PB Div 5",
    6: "PB Div 6",
    7: "PB Div 7",
}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_ticket(
    ticket_nums: tuple[int, ...], wheel_pb: int, draw_nums: list[int], draw_pb: int, draw_bonus: int
) -> tuple[int, bool, bool]:
    """Return (main_matches, bonus_match, pb_hit) tuple."""
    matches = len(set(ticket_nums) & set(draw_nums))
    bonus_match = draw_bonus > 0 and draw_bonus in set(ticket_nums)
    pb_hit = wheel_pb == draw_pb
    return matches, bonus_match, pb_hit


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def backtest(wheel_name: str, num_draws: int | None, draw_pb_override: int | None = None) -> None:
    if wheel_name not in WHEELS:
        print(f"Unknown wheel: '{wheel_name}'")
        print(f"Available: {', '.join(WHEELS)}")
        sys.exit(1)

    draws = load_draws()
    if not draws:
        print("No draws found.")
        sys.exit(1)

    if num_draws is None or num_draws > len(draws):
        num_draws = len(draws)

    recent = draws[-num_draws:]
    tickets, wheel_pb = WHEELS[wheel_name]
    n_tickets = len(tickets)
    cost_per_draw = n_tickets * _TICKET_COST
    total_cost = cost_per_draw * num_draws

    pool: set[int] = set()
    for t in tickets:
        pool.update(t)

    # --- Fetch payouts once and pre-build bonus-aware prize lookup ---
    from prize_calculator import fetch_payouts, resolve_divisions

    print("  Fetching latest prize data...", end=" ", flush=True)
    payouts = fetch_payouts()
    if payouts:
        lotto_prizes = payouts["lotto"]
        pb_prizes = payouts["powerball"]
        is_live = True
        print(f"live ({payouts['draw_date']})")
    else:
        lotto_prizes = dict(_FALLBACK_LOTTO)
        pb_prizes = dict(_FALLBACK_PB)
        is_live = False
        print("using static estimates")

    # Pre-build lookup: (matches, bonus_match, pb_hit) -> prize info
    prize_lookup: dict[tuple[int, bool, bool], dict[str, Any]] = {}
    for m in range(0, 7):
        for bm in [False, True]:
            for pb in [False, True]:
                lotto_div, pb_div = resolve_divisions(m, bm, pb)
                main_prize = lotto_prizes.get(lotto_div, 0.0) if lotto_div else 0.0
                pb_val = pb_prizes.get(pb_div, 0.0) if pb_div else 0.0
                prize_lookup[(m, bm, pb)] = {
                    "main_division": lotto_div,
                    "pb_division": pb_div,
                    "main_prize": main_prize,
                    "pb_prize": pb_val,
                    "total_prize": main_prize + pb_val,
                }
    print()

    # --- Accumulators ---
    lotto_counts = [0] * 7  # index = division - 1
    lotto_prizes_acc = [0.0] * 7
    pb_counts = [0] * 7
    bonus_upgrades = 0  # tickets upgraded by bonus ball
    bonus_added_value = 0.0  # extra prize $ from bonus upgrades
    upgrade_breakdown: dict[str, int] = {}  # "fromX_toY" -> count
    total_prize_without_bonus = 0.0
    guarantee_triggered = 0
    guarantee_met = 0
    draws_any_win = 0
    total_prize = 0.0
    draw_records: list[dict[str, Any]] = []

    desc, cond_fn, guar_fn = GUARANTEES[wheel_name]

    for draw_nums, draw_pb, draw_bonus, draw_date in recent:
        draw_set = set(draw_nums)
        pool_overlap = len(draw_set & pool)
        # Use override PB for scoring if provided
        score_pb = draw_pb_override if draw_pb_override is not None else draw_pb

        ticket_match_counts = []
        draw_had_win = False

        for ticket in tickets:
            matches, bonus_match, pb_hit = score_ticket(
                ticket,
                wheel_pb,
                draw_nums,
                score_pb,
                draw_bonus,
            )
            ticket_match_counts.append(matches)

            info = prize_lookup.get((matches, bonus_match, pb_hit), {})
            prize = info.get("total_prize", 0.0)
            lotto_div = info.get("main_division")
            pb_div = info.get("pb_division")

            # Track bonus upgrades: compare with bonus_match=False
            if bonus_match and pb_hit and matches in (5, 4, 3):
                without_info = prize_lookup.get((matches, False, pb_hit), {})
                without_prize = without_info.get("total_prize", 0.0)
                upgrade_value = prize - without_prize
                if upgrade_value > 0:
                    bonus_upgrades += 1
                    bonus_added_value += upgrade_value
                    from_div = without_info.get("main_division")
                    to_div = lotto_div
                    if from_div and to_div and from_div != to_div:
                        key = f"{from_div}->{to_div}"
                        upgrade_breakdown[key] = upgrade_breakdown.get(key, 0) + 1

            # Accumulate prize without bonus for comparison
            without_total = prize_lookup.get((matches, False, pb_hit), {}).get("total_prize", 0.0)
            total_prize_without_bonus += without_total

            if lotto_div:
                idx = lotto_div - 1
                lotto_counts[idx] += 1
                lotto_prizes_acc[idx] += info.get("main_prize", 0.0)
            if pb_div:
                pb_counts[pb_div - 1] += 1

            if prize > 0:
                total_prize += prize
                draw_had_win = True

        if draw_had_win:
            draws_any_win += 1

        if pool_overlap >= 3 and cond_fn(pool_overlap):
            guarantee_triggered += 1
            if guar_fn(ticket_match_counts, pool_overlap):
                guarantee_met += 1

        draw_records.append(
            {
                "date": draw_date,
                "nums": draw_nums,
                "pb": draw_pb,
                "overlap": pool_overlap,
                "won": draw_had_win,
            }
        )

    # --- Results ---
    net = total_prize - total_cost
    roi_pct = (net / total_cost * 100) if total_cost else 0.0
    date_range = f"{recent[0][3]} - {recent[-1][3]}"

    print(f"  {'=' * 56}")
    print(f"  Backtest: {wheel_name} wheel over {num_draws} draws")
    print(f"  {'=' * 56}")
    print(f"  Tickets/draw:    {n_tickets}")
    print(f"  Cost/draw:       ${cost_per_draw:.2f}")
    print(f"  PB fixed:        {wheel_pb}")
    if draw_pb_override is not None:
        print(f"  Draw PB (override): {draw_pb_override}  (actual varies)")
    print(f"  Pool size:       {len(pool)} numbers")
    print(f"  Date range:      {date_range}")
    print(f"  Prize source:    {'live (API)' if is_live else 'estimated (static)'}")
    print()

    print(f"  Guarantee:       {desc}")
    if guarantee_triggered > 0:
        hit_pct = guarantee_met / guarantee_triggered * 100
        print(
            f"  Guarantee hits:  {guarantee_met} / {guarantee_triggered} "
            f"({hit_pct:.1f}%) when condition triggered"
        )
    else:
        print("  Guarantee hits:  N/A (condition never triggered)")
    print()

    print(f"  {'Lotto Division':<20s}  {'Winners':>8s}  {'Avg Prize':>10s}  {'Total':>12s}")
    print(f"  {'-' * 52}")
    for div_num in sorted(DIVISION_LABELS):
        idx = div_num - 1
        if lotto_counts[idx] > 0:
            avg = lotto_prizes_acc[idx] / lotto_counts[idx]
            print(
                f"  {DIVISION_LABELS[div_num]:<20s}  {lotto_counts[idx]:>8d}  ${avg:>8,.0f}  ${lotto_prizes_acc[idx]:>10,.0f}"
            )
    has_pb = any(pb_counts)
    if has_pb:
        print()
        print(f"  {'PB Division':<20s}  {'Winners':>8s}")
        print(f"  {'-' * 30}")
        for div_num in sorted(PB_DIVISION_LABELS):
            idx = div_num - 1
            if pb_counts[idx] > 0:
                print(f"  {PB_DIVISION_LABELS[div_num]:<20s}  {pb_counts[idx]:>8d}")
    print()

    print("  Prize histogram (per draw average):")
    print(f"  {'Division':<20s}  {'Hits':>6s}  {'Avg/Draw':>10s}  {'Bar':<40s}")
    print(f"  {'-' * 78}")
    all_counts = lotto_counts[:]
    max_hits = max(all_counts) if max(all_counts) > 0 else 1
    for div_num in sorted(DIVISION_LABELS):
        idx = div_num - 1
        if lotto_counts[idx] == 0:
            continue
        avg = lotto_prizes_acc[idx] / num_draws
        bar_len = int(lotto_counts[idx] / max_hits * 30)
        bar = "#" * bar_len
        print(f"  {DIVISION_LABELS[div_num]:<20s}  {lotto_counts[idx]:>6d}  ${avg:>8,.2f}  {bar}")
    print()

    print(
        f"  Draws with any win: {draws_any_win} / {num_draws} "
        f"({draws_any_win / num_draws * 100:.1f}%)"
    )
    print()

    # --- Bonus Impact Report ---
    bonus_premium = (
        (total_prize - total_prize_without_bonus) / total_prize_without_bonus * 100
        if total_prize_without_bonus > 0
        else 0.0
    )
    print(f"  {'=' * 56}")
    print("  Bonus Impact Report")
    print(f"  {'=' * 56}")
    print(f"  Total prize with bonus:     ${total_prize:>10,.2f}")
    print(f"  Total prize without bonus:  ${total_prize_without_bonus:>10,.2f}")
    print(f"  Bonus premium:              {bonus_premium:>+10.2f}%")
    print(f"  Tickets upgraded by bonus:  {bonus_upgrades:>10d}")
    print(f"  Value added by bonus:       ${bonus_added_value:>10,.2f}")
    if upgrade_breakdown:
        print("  Upgrade breakdown:")
        for key in sorted(upgrade_breakdown):
            cnt = upgrade_breakdown[key]
            print(f"    Div {key:>6s}  ->  {cnt:>6d} tickets")
    else:
        print("  Upgrade breakdown:          none")
    print()
    print(f"  {'':>30s}  {'Per draw':>10s}  {'Total':>12s}")
    print(f"  {'-' * 56}")
    print(f"  {'Cost':>30s}  ${cost_per_draw:>8.2f}  ${total_cost:>10,.2f}")
    print(f"  {'Prize':>30s}  ${total_prize / num_draws:>8.2f}  ${total_prize:>10,.2f}")
    if net >= 0:
        print(f"  {'Net profit':>30s}  {'':>10s}  ${net:>10,.2f}")
    else:
        print(f"  {'Net loss':>30s}  {'':>10s}  ${net:>10,.2f}")
    print(f"  {'ROI':>30s}  {'':>10s}  {roi_pct:>+10.2f}%")
    print()

    # Top 5 best draws by overlap
    sorted_records = sorted(draw_records, key=lambda r: r["overlap"], reverse=True)
    best = [r for r in sorted_records if r["won"]][:5]
    if best:
        print("  Best draws (most overlap):")
        if draw_pb_override is not None:
            print(f"  {'Date':<14s}  {'Draw':>22s}  {'Actual':>4s}  {'Overlap':>7s}")
        else:
            print(f"  {'Date':<14s}  {'Draw':>22s}  {'PB':>3s}  {'Overlap':>7s}")
        print(f"  {'-' * 48}")
        for r in best:
            nums = ",".join(f"{n:02d}" for n in r["nums"])
            pb_field = f"  {r['pb']:>4d}" if draw_pb_override is not None else f"  {r['pb']:>3d}"
            print(f"  {r['date']:<14s}  {nums:>22s}{pb_field}  {r['overlap']:>4d}/6")
        print()


# ---------------------------------------------------------------------------


def backtest_bonus_impact(wheel_name: str, num_draws: int | None = None) -> dict[str, Any]:
    """Return structured bonus-impact data for a wheel (no console output).

    Runs a lightweight internal backtest and returns the bonus-related metrics
    as a dict suitable for API or dashboard consumption.
    """
    from prize_calculator import fetch_payouts, resolve_divisions

    draws = load_draws()
    if not draws:
        return {"error": "No draws found."}
    if wheel_name not in WHEELS:
        return {"error": f"Unknown wheel: '{wheel_name}'"}

    if num_draws is None or num_draws > len(draws):
        num_draws = len(draws)
    recent = draws[-num_draws:]
    tickets, wheel_pb = WHEELS[wheel_name]

    payouts = fetch_payouts()
    if payouts:
        lotto_p = payouts["lotto"]
        pb_p = payouts["powerball"]
    else:
        lotto_p = dict(_FALLBACK_LOTTO)
        pb_p = dict(_FALLBACK_PB)

    prize_lookup = {}
    for m in range(7):
        for bm in (False, True):
            for pb in (False, True):
                ld, pd = resolve_divisions(m, bm, pb)
                prize_lookup[(m, bm, pb)] = {
                    "total_prize": (lotto_p.get(ld, 0) if ld else 0)
                    + (pb_p.get(pd, 0) if pd else 0),
                    "main_division": ld,
                }

    total_prize = 0.0
    total_prize_wo = 0.0
    bonus_upgrades = 0
    bonus_added = 0.0
    upgrade_breakdown: dict[str, int] = {}

    for draw_nums, draw_pb, draw_bonus, _draw_date in recent:
        for ticket in tickets:
            matches = len(set(ticket) & set(draw_nums))
            bonus_match = draw_bonus > 0 and draw_bonus in set(ticket)
            pb_hit = wheel_pb == draw_pb

            info = prize_lookup.get((matches, bonus_match, pb_hit), {})
            prize = info.get("total_prize", 0)
            total_prize += prize

            wo_info = prize_lookup.get((matches, False, pb_hit), {})
            total_prize_wo += wo_info.get("total_prize", 0)

            if bonus_match and pb_hit and matches in (5, 4, 3):
                upgrade_val = prize - wo_info.get("total_prize", 0)
                if upgrade_val > 0:
                    bonus_upgrades += 1
                    bonus_added += upgrade_val
                    from_div = wo_info.get("main_division")
                    to_div = info.get("main_division")
                    if from_div and to_div and from_div != to_div:
                        key = f"{from_div}->{to_div}"
                        upgrade_breakdown[key] = upgrade_breakdown.get(key, 0) + 1

    premium = (total_prize - total_prize_wo) / total_prize_wo * 100 if total_prize_wo > 0 else 0.0

    return {
        "wheel": wheel_name,
        "draws_tested": num_draws,
        "total_prize_with_bonus": round(total_prize, 2),
        "total_prize_without_bonus": round(total_prize_wo, 2),
        "bonus_premium_percent": round(premium, 2),
        "upgraded_tickets": bonus_upgrades,
        "bonus_added_value": round(bonus_added, 2),
        "upgrade_breakdown": upgrade_breakdown,
    }


def build_prize_lookup() -> dict[tuple[int, bool, bool], float]:
    """Build an analytical prize lookup table for every match outcome.

    Uses prize_calculator.py division rules and fixed pool percentages.
    No simulation needed — returns the expected prize for each scenario.

    Returns
    -------
    dict
        Keys: (main_matches, bonus_matched, pb_matched) -> float prize.
    """
    from prize_calculator import (
        fetch_payouts,
        resolve_divisions,
    )

    payouts = fetch_payouts()
    if payouts:
        lotto_prizes = payouts["lotto"]
        pb_prizes = payouts["powerball"]
    else:
        lotto_prizes = dict(_FALLBACK_LOTTO)
        pb_prizes = dict(_FALLBACK_PB)

    lookup: dict[tuple[int, bool, bool], float] = {}
    for m in range(7):
        for bm in (False, True):
            for pb in (False, True):
                ld, pd = resolve_divisions(m, bm, pb)
                prize = (lotto_prizes.get(ld, 0) if ld else 0) + (pb_prizes.get(pd, 0) if pd else 0)
                lookup[(m, bm, pb)] = float(prize)
    return lookup


def compute_analytical_ev(
    wheel_tickets: list[Any], wheel_pb: int, prize_lookup: dict[Any, Any]
) -> float:
    """Compute expected value analytically using hypergeometric probabilities.

    Parameters
    ----------
    wheel_tickets : list[tuple[int,...]]
        List of 6-number ticket tuples.
    wheel_pb : int
        Powerball number.
    prize_lookup : dict
        From build_prize_lookup().

    Returns
    -------
    float
        Expected prize per draw (EV).
    """
    import math

    total_ev = 0.0
    pb_prob = 1.0 / 10.0  # probability wheel_pb matches draw PB
    bonus_prob = 1.0 / 40.0  # probability draw bonus is in ticket (per distinct number)

    for ticket in wheel_tickets:
        distinct = len(set(ticket))
        # Probabilities for each match count (hypergeometric: 6 drawn from 40, ticket has 6)
        # P(matches = k) = C(6,k)*C(34,6-k)/C(40,6)
        for k in range(7):
            p_match = (math.comb(6, k) * math.comb(34, 6 - k)) / math.comb(40, 6)
            for bm in (False, True):
                p_bonus = bonus_prob * distinct if bm else 1.0 - bonus_prob * distinct
                pb = False  # first compute without PB
                prize_wo = prize_lookup.get((k, bm, pb), 0.0)
                prize_w = prize_lookup.get((k, bm, True), 0.0)
                ev_ticket = p_match * p_bonus * ((1 - pb_prob) * prize_wo + pb_prob * prize_w)
                total_ev += ev_ticket

    return total_ev


# ---------------------------------------------------------------------------
def simulate_bonus_ev(
    wheel: Any,
    num_sims: int = 1_000_000,
    conn: Any = None,
    use_pool_allocation: bool = False,
    total_turnover: float | None = None,
) -> dict[str, Any]:
    """Monte Carlo simulation of bonus ball premium for a wheel.

    For each simulated draw, randomly generates 6 main numbers (1-40,
    without replacement), 1 bonus ball (1-40), and 1 Powerball (1-10).
    Computes the total prize across all tickets with and without the
    bonus ball matching.  Uses vectorised numpy operations for speed.

    When use_pool_allocation is True, uses allocate_pool() to model
    realistic prize splitting among multiple winners per division
    (including Div 1 $50M cap and Div 7 fixed prizes).  The prize pool
    is derived from total_turnover (default: $2,500,000 per draw).

    Parameters
    ----------
    wheel : str or list[tuple[int,...]]
        Wheel name (key in WHEELS) or explicit list of 6-number tickets.
    num_sims : int
        Number of Monte Carlo draws (default 1 000 000).
    conn : ignored (kept for API compatibility).
    use_pool_allocation : bool
        If True, use allocate_pool() for realistic multi-winner prizes.
    total_turnover : float or None
        Total ticket sales (NZD) per draw for pool allocation.
        Default: $2,500,000 for Powerball.

    Returns
    -------
    dict
        Keys: ev_with_bonus, ev_without_bonus, bonus_premium_percent,
        upgrade_count, avg_prize_with, avg_prize_without.
        When use_pool_allocation=True, also includes: div1_capped_draws,
        per_winner_breakdown.
    """
    import numpy as np

    from prize_calculator import fetch_payouts, resolve_divisions

    # --- Resolve wheel ---
    if isinstance(wheel, str):
        if wheel not in WHEELS:
            raise ValueError(f"Unknown wheel: '{wheel}'")
        tickets, wheel_pb = WHEELS[wheel]
    else:
        tickets = list(wheel)
        wheel_pb = 3

    n_tickets = len(tickets)
    if n_tickets == 0:
        return {
            "ev_with_bonus": 0.0,
            "ev_without_bonus": 0.0,
            "bonus_premium_percent": 0.0,
            "upgrade_count": 0,
            "avg_prize_with": 0.0,
            "avg_prize_without": 0.0,
        }

    # --- Fetch payouts ---
    payouts = fetch_payouts()
    if payouts:
        lotto_prizes = payouts["lotto"]
        pb_prizes = payouts["powerball"]
    else:
        lotto_prizes = dict(_FALLBACK_LOTTO)
        pb_prizes = dict(_FALLBACK_PB)

    # ==================================================================
    # Pool-allocation mode: realistic multi-winner prize modelling
    # ==================================================================
    if use_pool_allocation:
        from prize_calculator import allocate_pool

        if total_turnover is None:
            total_turnover = _DEFAULT_PB_TURNOVER

        rng = np.random.default_rng()
        total_with = 0.0
        total_without = 0.0
        upgrade_count = 0
        div1_capped_draws = 0
        per_winner_accum: dict[int, list[float]] = {d: [] for d in range(1, 8)}

        # Process simulations in batches for memory efficiency
        batch_size = 50_000
        n_batches = max(1, (num_sims + batch_size - 1) // batch_size)
        sims_done = 0

        for _batch_idx in range(n_batches):
            bs = min(batch_size, num_sims - sims_done)
            if bs <= 0:
                break

            all_mains_b = np.empty((bs, 6), dtype=np.int32)
            for i in range(bs):
                all_mains_b[i] = rng.choice(40, size=6, replace=False) + 1
            all_bonus_b = rng.integers(1, 41, size=bs, dtype=np.int32)
            all_pb_b = rng.integers(1, 11, size=bs, dtype=np.int32)
            pb_hit_b = all_pb_b == wheel_pb

            for sim_idx in range(bs):
                draw_nums = set(all_mains_b[sim_idx])
                draw_bonus = int(all_bonus_b[sim_idx])
                pb_hit = bool(pb_hit_b[sim_idx])

                # Count winners per division for this simulated draw
                winners_w: dict[int, int] = {}
                winners_wo: dict[int, int] = {}

                for ticket in tickets:
                    ticket_set = set(ticket)
                    m = len(ticket_set & draw_nums)
                    bm = draw_bonus > 0 and draw_bonus in ticket_set

                    ld_w, pd_w = resolve_divisions(m, bm, pb_hit)
                    ld_wo, pd_wo = resolve_divisions(m, False, pb_hit)

                    # Use lotto division as primary (pd_w mirrors ld_w when PB hits)
                    if ld_w is not None:
                        winners_w[ld_w] = winners_w.get(ld_w, 0) + 1
                    if ld_wo is not None:
                        winners_wo[ld_wo] = winners_wo.get(ld_wo, 0) + 1

                    # Track upgrades
                    if bm and pb_hit and m in (3, 4, 5) and ld_w != ld_wo:
                        upgrade_count += 1

                # Allocate pools for this draw
                alloc_w = allocate_pool(total_turnover, winners_w, game="powerball")
                alloc_wo = allocate_pool(total_turnover, winners_wo, game="powerball")

                # Sum prizes
                for div, n in winners_w.items():
                    pw = alloc_w["per_winner"].get(div, 0.0)
                    total_with += n * pw
                    per_winner_accum[div].append(pw)
                for div, n in winners_wo.items():
                    pw = alloc_wo["per_winner"].get(div, 0.0)
                    total_without += n * pw

                if alloc_w["div1_capped"]:
                    div1_capped_draws += 1

            sims_done += bs

        ev_with = total_with / num_sims
        ev_without = total_without / num_sims
        premium_pct = ((ev_with - ev_without) / ev_without * 100) if ev_without > 0 else 0.0

        result = {
            "ev_with_bonus": round(ev_with, 4),
            "ev_without_bonus": round(ev_without, 4),
            "bonus_premium_percent": round(premium_pct, 2),
            "upgrade_count": upgrade_count,
            "avg_prize_with": round(total_with / num_sims, 2),
            "avg_prize_without": round(total_without / num_sims, 2),
            "div1_capped_draws": div1_capped_draws,
            "per_winner_breakdown": {
                str(d): round(float(np.mean(v)), 2) if v else 0.0
                for d, v in per_winner_accum.items()
                if v
            },
            "allocation_mode": "pool",
        }
        return result

    # --- Precompute prize lookup: prize[m][bm][pb] ---
    prize_w = [[[0.0, 0.0] for _ in range(2)] for _ in range(7)]
    prize_wo = [[[0.0, 0.0] for _ in range(2)] for _ in range(7)]
    for m in range(7):
        for bmi in (0, 1):
            for pbi in (0, 1):
                ld_w, pd_w = resolve_divisions(m, bool(bmi), bool(pbi))
                pw = (lotto_prizes.get(ld_w, 0) if ld_w else 0) + (
                    pb_prizes.get(pd_w, 0) if pd_w else 0
                )
                prize_w[m][bmi][pbi] = pw
                ld_wo, pd_wo = resolve_divisions(m, False, bool(pbi))
                pwo = (lotto_prizes.get(ld_wo, 0) if ld_wo else 0) + (
                    pb_prizes.get(pd_wo, 0) if pd_wo else 0
                )
                prize_wo[m][bmi][pbi] = pwo

    # --- Generate random draws ---
    rng = np.random.default_rng()
    all_mains = np.empty((num_sims, 6), dtype=np.int32)
    for i in range(num_sims):
        all_mains[i] = rng.choice(40, size=6, replace=False) + 1
    all_bonus = rng.integers(1, 41, size=num_sims, dtype=np.int32)
    all_pb = rng.integers(1, 11, size=num_sims, dtype=np.int32)
    pb_hit_global = (all_pb == wheel_pb).astype(np.int32)

    total_with = 0.0
    total_without = 0.0
    upgrade_count = 0

    for ticket in tickets:
        ticket_set = set(ticket)
        ticket_arr = np.array(list(ticket), dtype=np.int32)
        matches = np.sum(np.isin(all_mains, ticket_arr), axis=1).astype(np.int32)
        bonus_match = np.array([b in ticket_set for b in all_bonus], dtype=np.int32)
        indices = matches * 4 + bonus_match * 2 + pb_hit_global
        hist = np.bincount(indices, minlength=28)

        for idx in range(28):
            count = int(hist[idx])
            if count == 0:
                continue
            m = idx // 4
            bmi = (idx % 4) // 2
            pbi = idx % 2
            total_with += count * prize_w[m][bmi][pbi]
            total_without += count * prize_wo[m][bmi][pbi]
            if prize_w[m][bmi][pbi] > prize_wo[m][bmi][pbi]:
                upgrade_count += count

    ev_with = total_with / num_sims
    ev_without = total_without / num_sims
    premium_pct = ((ev_with - ev_without) / ev_without * 100) if ev_without > 0 else 0.0

    return {
        "ev_with_bonus": round(ev_with, 4),
        "ev_without_bonus": round(ev_without, 4),
        "bonus_premium_percent": round(premium_pct, 2),
        "upgrade_count": upgrade_count,
        "avg_prize_with": round(total_with / upgrade_count, 2) if upgrade_count else 0.0,
        "avg_prize_without": round(total_without / num_sims, 2),
    }


# ===========================================================================
# Multi-Draw Backtest with Jackpot Rollover
# ===========================================================================


def run_multi_draw_backtest(
    wheel_name: str,
    start_draw_id: int = 0,
    num_draws: int = 10,
    base_turnover: float | None = None,
) -> dict[str, Any]:
    """Backtest a wheel over consecutive draws with jackpot rollover.

    Loops over draws sequentially starting from ``start_draw_id``.
    For each draw:
      1. Scores all tickets against the draw numbers.
      2. Counts winners per division.
      3. Allocates the prize pool via ``allocate_pool()``.
      4. Applies jackpot rollover via ``apply_jackpot()``.
      5. Carries the jackpot forward if Div 1 has no winner.

    The $50M Div 1 cap is respected.  After ``max_consecutive_jackpots``
    draws without a Div 1 winner, a must-win draw is forced and the
    jackpot cascades to lower divisions.

    Parameters
    ----------
    wheel_name : str
        Wheel name (key in WHEELS).
    start_draw_id : int
        Index into the draw list where the backtest starts (0 = earliest).
    num_draws : int
        Number of consecutive draws to simulate.
    base_turnover : float or None
        Ticket-sales turnover per draw.  Default from settings
        (``default_powerball_turnover``, ~$2.5M).

    Returns
    -------
    dict
        Keys: wheel, num_draws, total_cost, total_prize, net, roi_pct,
        jackpot_occurrences, forced_distributions, draw_records.
    """
    from prize_calculator import (
        allocate_pool,
        apply_jackpot,
        resolve_divisions,
    )

    if wheel_name not in WHEELS:
        return {"error": f"Unknown wheel: '{wheel_name}'"}

    draws = load_draws()
    if not draws:
        return {"error": "No draws found."}

    # Resolve the draw window
    total_draws = len(draws)
    if start_draw_id < 0 or start_draw_id >= total_draws:
        start_draw_id = max(0, total_draws - num_draws)
    end_idx = min(start_draw_id + num_draws, total_draws)
    window = draws[start_draw_id:end_idx]
    actual_nd = len(window)

    tickets, wheel_pb = WHEELS[wheel_name]
    n_tickets = len(tickets)

    # Load settings
    try:
        from settings import settings as _st

        if base_turnover is None:
            base_turnover = _st.default_powerball_turnover
        max_consecutive = _st.max_consecutive_jackpots
        div1_cap = _st.div1_cap
        ticket_cost = _st.ticket_cost
    except ImportError:
        if base_turnover is None:
            base_turnover = 2_500_000.0
        max_consecutive = 10
        div1_cap = 50_000_000.0
        ticket_cost = 1.50

    cost_per_draw = n_tickets * ticket_cost
    total_cost = round(cost_per_draw * actual_nd, 2)

    # State carried across draws
    carried_jackpot = 0.0
    consecutive_no_div1 = 0
    jackpot_occurrences = 0
    forced_distributions = 0

    total_prize = 0.0
    draw_records: list[dict[str, Any]] = []

    for i, (draw_nums, draw_pb, draw_bonus, draw_date) in enumerate(window):
        draw_set = set(draw_nums)

        # --- Count winners per division ---
        winners: dict[int, int] = {}
        for ticket in tickets:
            m = len(set(ticket) & draw_set)
            bm = draw_bonus > 0 and draw_bonus in set(ticket)
            pb_hit = wheel_pb == draw_pb
            ld, _pd = resolve_divisions(m, bm, pb_hit)
            if ld is not None:
                winners[ld] = winners.get(ld, 0) + 1

        # --- Allocate pool ---
        alloc = allocate_pool(base_turnover, winners, game="powerball")

        # --- Apply jackpot ---
        jp = apply_jackpot(
            alloc,
            carried_jackpot=carried_jackpot,
            consecutive_no_div1=consecutive_no_div1,
            max_consecutive=max_consecutive,
            div1_cap=div1_cap,
        )

        # Update state
        carried_jackpot = jp["carried_jackpot"]
        consecutive_no_div1 = jp["consecutive_no_div1"]
        if jp["jackpot_triggered"]:
            jackpot_occurrences += 1
        if jp["forced_distribution"]:
            forced_distributions += 1

        # --- Compute draw prize ---
        draw_prize = 0.0
        for div, count in winners.items():
            pw = jp["per_winner"].get(div, 0.0)
            draw_prize += count * pw
        total_prize += draw_prize

        # --- Record ---
        draw_records.append(
            {
                "draw_index": start_draw_id + i,
                "draw_date": str(draw_date),
                "draw_numbers": [int(n) for n in draw_nums],
                "draw_pb": int(draw_pb),
                "jackpot_carried": round(carried_jackpot, 2),
                "consecutive_no_div1": consecutive_no_div1,
                "forced_distribution": jp["forced_distribution"],
                "jackpot_triggered": jp["jackpot_triggered"],
                "div1_winners": winners.get(1, 0),
                "draw_prize": round(draw_prize, 2),
                "per_winner_div1": jp["per_winner"].get(1, 0.0),
            }
        )

    net = round(total_prize - total_cost, 2)
    roi_pct = round((net / total_cost * 100), 2) if total_cost > 0 else 0.0

    return {
        "wheel": wheel_name,
        "start_draw_id": start_draw_id,
        "num_draws": actual_nd,
        "tickets_per_draw": n_tickets,
        "cost_per_draw": round(cost_per_draw, 2),
        "total_cost": total_cost,
        "total_prize": round(total_prize, 2),
        "net": net,
        "roi_pct": roi_pct,
        "jackpot_occurrences": jackpot_occurrences,
        "forced_distributions": forced_distributions,
        "final_carried_jackpot": round(carried_jackpot, 2),
        "final_consecutive_no_div1": consecutive_no_div1,
        "draw_records": draw_records,
    }


# ===========================================================================
# Lotto Strike EV simulation
# ===========================================================================


def simulate_strike_ev(
    strike_numbers: list[int],
    num_sims: int = 100_000,
    pool_amount: float | None = None,
) -> dict[str, Any]:
    """Simulate Lotto Strike expected value for a fixed set of 4 numbers.

    Strike uses the first 4 numbers drawn (in exact order) from each
    Lotto draw.  This function samples random 6/40 draws and evaluates
    how often the player's 4-number Strike selection would win.

    Parameters
    ----------
    strike_numbers : list[int]
        4 numbers chosen by the player (in order, 1-40).
    num_sims : int
        Number of Monte Carlo draws (default 100 000).
    pool_amount : float or None
        Estimated Strike prize pool.  Default from settings.

    Returns
    -------
    dict
        Keys: ev_per_line, cost_per_line, roi_pct, division_counts,
        total_prize, exact_match_distribution.
    """
    import numpy as np

    from prize_calculator import calculate_strike_prize, count_exact_matches

    if pool_amount is None:
        try:
            from settings import settings as _st

            pool_amount = _st.default_strike_pool
        except ImportError:
            pool_amount = 350_000.0

    cost_per_line = 1.00

    rng = np.random.default_rng()
    total_prize = 0.0
    div_counts: dict[int, int] = {}
    match_dist: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

    for _ in range(num_sims):
        draw_6 = rng.choice(40, size=6, replace=False) + 1
        draw_first4 = list(draw_6[:4])

        exact = count_exact_matches(strike_numbers, draw_first4)
        match_dist[exact] = match_dist.get(exact, 0) + 1

        result = calculate_strike_prize(exact, pool_amount=pool_amount)
        prize = result["prize"]
        total_prize += prize

        div = result["division"]
        if div is not None:
            div_counts[div] = div_counts.get(div, 0) + 1

    ev = total_prize / num_sims
    total_cost = num_sims * cost_per_line
    roi = ((total_prize - total_cost) / total_cost * 100) if total_cost > 0 else 0.0

    return {
        "strike_numbers": strike_numbers,
        "num_sims": num_sims,
        "cost_per_line": cost_per_line,
        "total_cost": round(total_cost, 2),
        "total_prize": round(total_prize, 2),
        "ev_per_line": round(ev, 4),
        "roi_pct": round(roi, 2),
        "division_counts": {str(k): v for k, v in sorted(div_counts.items())},
        "exact_match_distribution": {str(k): v for k, v in sorted(match_dist.items())},
    }


# ===========================================================================
# Statistical helpers: bootstrap CI and paired t-tests
# ===========================================================================


def _bootstrap_ci(
    data: list[float], n_resamples: int = 1000, ci: float = 95.0
) -> tuple[float, float]:
    """Compute bootstrap confidence interval for the mean of `data`.

    Parameters
    ----------
    data : list[float]
        Observed values (e.g. per-draw prizes).
    n_resamples : int
        Number of bootstrap resamples (default 1000).
    ci : float
        Confidence level percentage (default 95).

    Returns
    -------
    tuple[float, float]
        (lower_bound, upper_bound).
    """
    if not data or len(data) < 2:
        return (0.0, 0.0)

    arr = np.array(data, dtype=float)
    n = len(arr)
    means = np.empty(n_resamples)
    rng = np.random.default_rng()
    for i in range(n_resamples):
        sample = rng.choice(arr, size=n, replace=True)
        means[i] = sample.mean()

    alpha = (100.0 - ci) / 2.0
    lo = np.percentile(means, alpha)
    hi = np.percentile(means, 100.0 - alpha)
    return (round(float(lo), 4), round(float(hi), 4))


def _paired_ttest(a: list[float], b: list[float]) -> float:
    """Compute two-sided p-value from paired t-test.

    Returns p-value.  If p < 0.05 the difference is significant.
    """
    if len(a) != len(b) or len(a) < 2:
        return 1.0

    a_arr = np.array(a, dtype=float)
    b_arr = np.array(b, dtype=float)
    diffs = a_arr - b_arr
    n = len(diffs)
    mean_diff = diffs.mean()
    # Standard error of the mean difference
    se = diffs.std(ddof=1) / np.sqrt(n) if n > 1 else 1.0
    if se == 0:
        return 1.0

    t_stat = mean_diff / se
    # Two-sided p-value from t-distribution with n-1 df
    # Use a simple approximation via scipy if available, else normal approx
    try:
        from scipy.stats import t as tdist

        p = 2.0 * tdist.sf(abs(t_stat), df=n - 1)
    except ImportError:
        # Normal approximation
        from math import erf, sqrt

        def norm_cdf(x: float) -> float:
            return 0.5 * (1.0 + erf(x / sqrt(2.0)))

        p = 2.0 * (1.0 - norm_cdf(abs(t_stat)))
    return round(float(p), 6)


# ===========================================================================
# Multi-wheel backtest summary with confidence intervals
# ===========================================================================


def run_single_wheel_per_draw(wheel_name: str, num_draws: int | None = None) -> list[float]:
    """Run backtest and return per-draw total prize list (for bootstrap)."""
    from prize_calculator import fetch_payouts, resolve_divisions

    draws = load_draws()
    if not draws or wheel_name not in WHEELS:
        return []

    if num_draws is None or num_draws > len(draws):
        num_draws = len(draws)
    recent = draws[-num_draws:]
    tickets, wheel_pb = WHEELS[wheel_name]

    payouts = fetch_payouts()
    if payouts:
        lp = payouts["lotto"]
        pp = payouts["powerball"]
    else:
        lp = dict(_FALLBACK_LOTTO)
        pp = dict(_FALLBACK_PB)

    lookup = {}
    for m in range(7):
        for bm in (False, True):
            for pb in (False, True):
                ld, pd = resolve_divisions(m, bm, pb)
                lookup[(m, bm, pb)] = (lp.get(ld, 0) if ld else 0) + (pp.get(pd, 0) if pd else 0)

    per_draw = []
    for draw_nums, draw_pb, draw_bonus, _date in recent:
        total = 0.0
        for ticket in tickets:
            matches = len(set(ticket) & set(draw_nums))
            bonus_match = draw_bonus > 0 and draw_bonus in set(ticket)
            pb_hit = wheel_pb == draw_pb
            total += lookup.get((matches, bonus_match, pb_hit), 0.0)
        per_draw.append(total)

    return per_draw


def generate_backtest_summary(
    wheel_names: list[str] | None = None,
    num_draws: int | None = None,
    n_bootstrap: int = 1000,
) -> list[dict[str, Any]]:
    """Generate backtest summary with bootstrap CIs and paired t-tests.

    Each wheel is backtested over the same draw window.  Per-draw prize
    lists are used for bootstrap confidence intervals.  Paired t-tests
    compare every wheel against the best-performing wheel.

    Parameters
    ----------
    wheel_names : list[str] or None
        Wheels to compare (default: all WHEELS keys).
    num_draws : int or None
        Number of draws (None = all).
    n_bootstrap : int
        Bootstrap resamples (default 1000).

    Returns
    -------
    list[dict]
        Each dict: method, mean_score, ci_lower, ci_upper, p_value, significant.
    """
    if wheel_names is None:
        wheel_names = list(WHEELS.keys())

    per_draw_data: dict[str, list[float]] = {}
    for name in wheel_names:
        data = run_single_wheel_per_draw(name, num_draws)
        if data:
            per_draw_data[name] = data

    if not per_draw_data:
        return []

    # Find best method by mean
    best_name = max(per_draw_data, key=lambda n: float(np.mean(per_draw_data[n])))
    best_data = per_draw_data[best_name]

    rows = []
    for name in wheel_names:
        wheel_data = per_draw_data.get(name)
        if wheel_data is None:
            continue
        mean_val = round(float(np.mean(wheel_data)), 4)
        ci_lo, ci_hi = _bootstrap_ci(wheel_data, n_resamples=n_bootstrap)

        # Paired t-test vs best
        p_val = 1.0 if name == best_name else _paired_ttest(wheel_data, best_data)

        rows.append(
            {
                "method": name,
                "mean_score": mean_val,
                "ci_lower": ci_lo,
                "ci_upper": ci_hi,
                "p_value": p_val,
                "significant": p_val < 0.05,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest a lotto wheel against historical draws.",
    )
    parser.add_argument(
        "--wheel",
        "-w",
        required=True,
        choices=list(WHEELS.keys()),
        help=f"Wheel name ({', '.join(WHEELS.keys())})",
    )
    parser.add_argument(
        "--draws",
        "-n",
        type=int,
        default=0,
        help="Number of draws to test (0 = all draws for single, 10 for multi)",
    )
    parser.add_argument(
        "--draw-pb",
        type=int,
        default=None,
        help="Override the draw Powerball for all draws (1-10).",
    )
    parser.add_argument(
        "--start-draw",
        type=int,
        default=0,
        help="Starting draw index for multi-draw backtest (0 = earliest).",
    )
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Run multi-draw backtest with jackpot rollover.",
    )
    parser.add_argument(
        "--turnover",
        type=float,
        default=None,
        help="Base turnover per draw for multi-draw backtest (default $2.5M).",
    )
    args = parser.parse_args()

    if args.draw_pb is not None and not (1 <= args.draw_pb <= 10):
        print("Error: --draw-pb must be between 1 and 10.")
        sys.exit(1)

    if args.multi:
        nd = args.draws if args.draws > 0 else 10
        start = args.start_draw if args.start_draw > 0 else max(0, len(load_draws()) - nd)
        result = run_multi_draw_backtest(
            args.wheel,
            start_draw_id=start,
            num_draws=nd,
            base_turnover=args.turnover,
        )
        if "error" in result:
            print(f"Error: {result['error']}")
            sys.exit(1)

        print(f"  {'=' * 60}")
        print(f"  Multi-Draw Backtest: {result['wheel']} wheel")
        print(f"  {'=' * 60}")
        print(
            f"  Draws:          {result['start_draw_id']} -> "
            f"{result['start_draw_id'] + result['num_draws'] - 1} "
            f"({result['num_draws']} draws)"
        )
        print(f"  Tickets/draw:   {result['tickets_per_draw']}")
        print(f"  Cost/draw:      ${result['cost_per_draw']:.2f}")
        print(f"  Total cost:     ${result['total_cost']:,.2f}")
        print(f"  Total prize:    ${result['total_prize']:,.2f}")
        print(f"  Net:            ${result['net']:,.2f}")
        print(f"  ROI:            {result['roi_pct']:+.2f}%")
        print(f"  Jackpot events: {result['jackpot_occurrences']}")
        print(f"  Forced dist:    {result['forced_distributions']}")
        print(f"  Final jackpot:  ${result['final_carried_jackpot']:,.2f}")
        print(f"  Final streak:   {result['final_consecutive_no_div1']}")
        print()
        print(
            f"  {'Draw':<6s} {'Date':<12s} {'Div1':>5s} {'Prize':>12s} "
            f"{'Jackpot':>14s} {'Strk':>4s} {'Forced':>6s}"
        )
        print(f"  {'-' * 65}")
        for rec in result["draw_records"]:
            forced = "YES" if rec["forced_distribution"] else ""
            print(
                f"  {rec['draw_index']:<6d} {rec['draw_date']:<12s} "
                f"{rec['div1_winners']:>5d} ${rec['draw_prize']:>10,.2f} "
                f"${rec['jackpot_carried']:>12,.0f} {rec['consecutive_no_div1']:>4d} "
                f"{forced:>6s}"
            )
        print()
    else:
        num = args.draws if args.draws > 0 else None
        backtest(args.wheel, num, draw_pb_override=args.draw_pb)


if __name__ == "__main__":
    _register_guarantees()
    main()
