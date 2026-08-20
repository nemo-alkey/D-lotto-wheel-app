#!/usr/bin/env python3
"""
arbitrage.py — find expected-value-positive lottery situations.

The idea
--------
A lottery ticket's expected value (EV) is::

    EV = SUM( probability_of_division * prize ) - ticket_price

For almost every game EV is deeply negative (the operator keeps 40-60%).
But the jackpot division's prize grows with rollovers while its odds stay
fixed, so EV rises with the jackpot. Each game therefore has a *rollover
threshold* — the jackpot at which EV crosses zero:

    J* = (ticket_price - fixed_prize_EV) / p_jackpot

For US Powerball the raw (annuity, pre-tax) threshold works out to
~$490M. Accounting for the lump-sum discount (~61% of annuity) and US
federal tax (~24%) pushes the realistic break-even above $1B — the
tax-adjusted option in this module makes that explicit.

Data sources
------------
Game definitions and fallback jackpots live in
``config/jackpot_thresholds.json``. ``scan_opportunities()`` first tries
to fetch live jackpots from APIVerve (same API as api_fetcher.py,
``APIVERVE_API_KEY`` env var); when the API is unavailable or returns no
jackpot field, it falls back to the manually-maintained ``current_jackpot``
in the JSON config.

Usage:
    from arbitrage import (
        calculate_ev, find_rollover_threshold, scan_opportunities,
    )
"""

from __future__ import annotations

import json
import logging
import os
from math import comb
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "jackpot_thresholds.json"
APIVERVE_BASE = "https://api.apiverve.com/v1/lottery"

#: Division id that pays the jackpot in every supported config.
JACKPOT_DIVISION = 1


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_game_configs(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load game definitions from jackpot_thresholds.json."""
    path = Path(config_path) if config_path else CONFIG_PATH
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


# ---------------------------------------------------------------------------
# Odds (combinatorics)
# ---------------------------------------------------------------------------


def division_probability(
    pool_main: int,
    pick_main: int,
    pool_bonus: int,
    pick_bonus: int,
    main_matches: int,
    bonus_matches: int,
) -> float:
    """Hypergeometric probability of a (main, bonus) match combination.

    When the bonus is drawn from the SAME pool as the mains (e.g. NZ Lotto,
    where ``pool_bonus == pool_main``), the bonus ball is drawn from the
    remaining ``pool_main - pick_main`` numbers and the probability is
    conditional on how many ticket numbers are still live:

        P(bonus hit | m main matches) = (pick_main - m) / (pool_main - pick_main)
    """
    p_main = (
        comb(pick_main, main_matches)
        * comb(pool_main - pick_main, pick_main - main_matches)
        / comb(pool_main, pick_main)
    )

    if pool_bonus == pool_main:
        # Shared pool: bonus drawn from the leftover numbers, no replacement
        live_ticket_nums = pick_main - main_matches
        remaining = pool_main - pick_main
        if bonus_matches == 1:
            p_bonus = live_ticket_nums / remaining
        elif bonus_matches == 0:
            p_bonus = 1.0 - live_ticket_nums / remaining
        else:
            return 0.0  # can't match 2+ bonus balls when only 1 is drawn
    else:
        p_bonus = (
            comb(pick_bonus, bonus_matches)
            * comb(pool_bonus - pick_bonus, pick_bonus - bonus_matches)
            / comb(pool_bonus, pick_bonus)
        )

    return p_main * p_bonus


def build_odds_and_prizes(
    game_cfg: dict[str, Any], jackpot: float
) -> tuple[dict[int, float], dict[int, float]]:
    """Build (odds_by_division, prizes_by_division) from a game config.

    odds values are probabilities (0-1); the "jackpot" prize spec is
    replaced by the supplied jackpot amount.
    """
    odds: dict[int, float] = {}
    prizes: dict[int, float] = {}
    for d in game_cfg["divisions"]:
        div = int(d["division"])
        odds[div] = division_probability(
            game_cfg["pool_main"],
            game_cfg["pick_main"],
            game_cfg["pool_bonus"],
            game_cfg["pick_bonus"],
            int(d["main"]),
            int(d["bonus"]),
        )
        prize = d["prize"]
        prizes[div] = float(jackpot) if prize == "jackpot" else float(prize)
    return odds, prizes


# ---------------------------------------------------------------------------
# Expected value
# ---------------------------------------------------------------------------


def calculate_ev(
    game: str,
    ticket_price: float,
    jackpot: float,
    odds_by_division: dict[int, float],
    prizes_by_division: dict[int, float],
    tax_rate: float = 0.0,
    lump_sum_ratio: float = 1.0,
) -> float:
    """Expected value of one ticket, in the game's currency.

        EV = SUM( p_division * prize_division ) - ticket_price

    Returns the raw EV; EV per dollar spent is simply
    ``calculate_ev(...) / ticket_price``.

    Args:
        game: Game code (used for logging only).
        ticket_price: Cost of one ticket.
        jackpot: Current jackpot (must match the value baked into
            prizes_by_division for the jackpot division).
        odds_by_division: {division: probability} from build_odds_and_prizes().
        prizes_by_division: {division: prize} from build_odds_and_prizes().
        tax_rate: Combined tax on winnings (e.g. 0.24 US federal).
        lump_sum_ratio: Cash-option fraction of the annuity jackpot
            (e.g. 0.61 for Powerball US). Applied to the jackpot division
            only.
    """
    ev = -float(ticket_price)
    for div, p in odds_by_division.items():
        prize = prizes_by_division[div]
        if div == JACKPOT_DIVISION:
            prize *= lump_sum_ratio
        ev += p * prize * (1.0 - tax_rate)
    logger.debug("%s: EV %.4f at jackpot %.0f", game, ev, jackpot)
    return ev


# ---------------------------------------------------------------------------
# Rollover threshold
# ---------------------------------------------------------------------------


def find_rollover_threshold(
    game: str,
    ticket_price: float,
    odds: dict[int, float],
    prizes: dict[int, float],
    tax_rate: float = 0.0,
    lump_sum_ratio: float = 1.0,
) -> float:
    """Jackpot amount at which EV becomes positive (break-even).

    Solves  p_jp * (lump * (1-tax)) * J  =  ticket_price - fixed_prize_EV
    for J, where fixed_prize_EV sums every non-jackpot contribution
    (tax-adjusted). Division 1 is treated as the jackpot division.

    For Powerball US with no adjustments this returns ~$490M.
    """
    p_jp = odds.get(JACKPOT_DIVISION, 0.0)
    if p_jp <= 0:
        raise ValueError(f"{game}: no jackpot-division odds supplied.")

    fixed_ev = sum(
        p * prizes[div] * (1.0 - tax_rate)
        for div, p in odds.items()
        if div != JACKPOT_DIVISION
    )
    jackpot_weight = p_jp * lump_sum_ratio * (1.0 - tax_rate)
    return max(0.0, (float(ticket_price) - fixed_ev) / jackpot_weight)


# ---------------------------------------------------------------------------
# Live jackpots (APIVerve, optional)
# ---------------------------------------------------------------------------


def fetch_current_jackpots(
    games: dict[str, Any], api_key: str | None = None, timeout: int = 10
) -> dict[str, float]:
    """Try to fetch live jackpots from APIVerve for each configured game.

    Returns {game_code: jackpot} for games where the API supplied a
    jackpot figure; empty dict when the API key is missing or every
    request fails (callers then fall back to the config's manual values).
    """
    api_key = api_key or os.environ.get("APIVERVE_API_KEY", "")
    if not api_key:
        logger.info("APIVERVE_API_KEY not set — using config jackpots.")
        return {}

    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — using config jackpots.")
        return {}

    jackpots: dict[str, float] = {}
    for code, cfg in games.items():
        slug = cfg.get("api_slug")
        if not slug:
            continue
        try:
            resp = requests.get(
                APIVERVE_BASE,
                params={"lottery": slug},
                headers={"x-api-key": api_key},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            # APIVerve payload shapes vary; probe common jackpot fields
            raw = (
                data.get("jackpot")
                or data.get("nextJackpot")
                or data.get("estimatedJackpot")
                or data.get("jackpotAmount")
            )
            if raw:
                jackpots[code] = float(str(raw).replace(",", "").replace("$", ""))
        except Exception as exc:
            logger.info("Jackpot fetch failed for %s: %s", code, exc)
    return jackpots


# ---------------------------------------------------------------------------
# Opportunity scan
# ---------------------------------------------------------------------------


def scan_opportunities(
    tax_adjusted: bool = False,
    api_key: str | None = None,
    config_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Check every configured game for EV-positive jackpots.

    For each game: current jackpot (APIVerve when available, else the
    config's manual value), rollover threshold, EV and EV per dollar.

    Returns:
        List of dicts sorted by ev_per_dollar descending:
        game_code, game_name, current_jackpot, jackpot_source
        ("api"|"config"), rollover_threshold, above_threshold,
        ticket_price_usd, ev, ev_per_dollar, recommendation
        ("PLAY" if EV > 0 else "SKIP").
    """
    games = load_game_configs(config_path)
    if not games:
        return []

    live = fetch_current_jackpots(games, api_key=api_key)

    results: list[dict[str, Any]] = []
    for code, cfg in games.items():
        ticket_price = float(cfg["ticket_price_usd"])
        if code in live:
            jackpot, source = live[code], "api"
        else:
            jackpot, source = float(cfg["current_jackpot"]), "config"

        odds, prizes = build_odds_and_prizes(cfg, jackpot)

        tax_rate = 0.0
        lump = 1.0
        if tax_adjusted:
            tax_rate = float(cfg.get("federal_tax", 0.0)) + float(
                cfg.get("state_tax", 0.0)
            )
            lump = float(cfg.get("lump_sum_ratio", 1.0))

        ev = calculate_ev(
            code,
            ticket_price,
            jackpot,
            odds,
            prizes,
            tax_rate=tax_rate,
            lump_sum_ratio=lump,
        )
        threshold = find_rollover_threshold(
            code,
            ticket_price,
            odds,
            prizes,
            tax_rate=tax_rate,
            lump_sum_ratio=lump,
        )
        ev_per_dollar = ev / ticket_price if ticket_price else 0.0

        results.append(
            {
                "game_code": code,
                "game_name": cfg["name"],
                "current_jackpot": jackpot,
                "jackpot_source": source,
                "rollover_threshold": round(threshold),
                "above_threshold": jackpot > threshold,
                "ticket_price_usd": ticket_price,
                "ev": round(ev, 4),
                "ev_per_dollar": round(ev_per_dollar, 4),
                "recommendation": "PLAY" if ev > 0 else "SKIP",
            }
        )

    results.sort(key=lambda r: -r["ev_per_dollar"])
    return results


# ---------------------------------------------------------------------------
# Probability tree (detailed math for one game)
# ---------------------------------------------------------------------------


def probability_tree(
    game_cfg: dict[str, Any],
    jackpot: float,
    tax_rate: float = 0.0,
    lump_sum_ratio: float = 1.0,
) -> list[dict[str, Any]]:
    """Per-division breakdown of the EV math for one game.

    Returns one dict per division: division, match (e.g. "5 + 1"),
    probability, one_in (odds as 1-in-N), prize, ev_contribution
    (after tax/lump-sum adjustments).
    """
    rows: list[dict[str, Any]] = []
    for d in game_cfg["divisions"]:
        div = int(d["division"])
        p = division_probability(
            game_cfg["pool_main"],
            game_cfg["pick_main"],
            game_cfg["pool_bonus"],
            game_cfg["pick_bonus"],
            int(d["main"]),
            int(d["bonus"]),
        )
        prize = float(jackpot) if d["prize"] == "jackpot" else float(d["prize"])
        effective = prize * (lump_sum_ratio if div == JACKPOT_DIVISION else 1.0)
        rows.append(
            {
                "division": div,
                "match": f"{d['main']} + {d['bonus']}",
                "probability": p,
                "one_in": round(1.0 / p) if p > 0 else None,
                "prize": prize,
                "ev_contribution": round(p * effective * (1.0 - tax_rate), 6),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Self-test — verify math against known Powerball / Mega Millions thresholds
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    games = load_game_configs()
    pb = games["POWERBALL_US"]
    mm = games["MEGA_MILLIONS"]

    # --- Known jackpot odds ---
    pb_odds, pb_prizes = build_odds_and_prizes(pb, 0)
    mm_odds, mm_prizes = build_odds_and_prizes(mm, 0)
    assert abs(pb_odds[1] - 1 / 292_201_338) < 1e-12, "Powerball jackpot odds"
    assert abs(mm_odds[1] - 1 / 302_575_350) < 1e-12, "Mega Millions jackpot odds"
    print(f"Powerball JP odds: 1 in {1/pb_odds[1]:,.0f}")
    print(f"Mega Millions JP odds: 1 in {1/mm_odds[1]:,.0f}")

    # --- Raw (annuity, pre-tax) break-even thresholds ---
    pb_threshold = find_rollover_threshold("POWERBALL_US", 2.0, pb_odds, pb_prizes)
    mm_threshold = find_rollover_threshold("MEGA_MILLIONS", 2.0, mm_odds, mm_prizes)
    print(f"\nPowerball raw threshold:    ${pb_threshold:,.0f}")
    print(f"Mega Millions raw threshold: ${mm_threshold:,.0f}")
    # Known figures: PB ~$490M, MM ~$530M
    assert (
        abs(pb_threshold - 490_000_000) < 25_000_000
    ), f"Powerball threshold {pb_threshold:,.0f} outside expected range"
    assert (
        abs(mm_threshold - 535_000_000) < 30_000_000
    ), f"Mega Millions threshold {mm_threshold:,.0f} outside expected range"

    # --- EV sign flips around the threshold ---
    below = calculate_ev(
        "PB", 2.0, pb_threshold * 0.9, *build_odds_and_prizes(pb, pb_threshold * 0.9)
    )
    above = calculate_ev(
        "PB", 2.0, pb_threshold * 1.1, *build_odds_and_prizes(pb, pb_threshold * 1.1)
    )
    assert below < 0 < above, "EV must cross zero at the threshold"
    print(f"EV at 90% of threshold: {below:+.3f}  |  at 110%: {above:+.3f}")

    # --- Tax-adjusted threshold is much higher (~$1.1B for PB) ---
    pb_tax_threshold = find_rollover_threshold(
        "POWERBALL_US",
        2.0,
        pb_odds,
        pb_prizes,
        tax_rate=pb["federal_tax"] + pb["state_tax"],
        lump_sum_ratio=pb["lump_sum_ratio"],
    )
    print(f"\nPowerball tax-adjusted threshold: ${pb_tax_threshold:,.0f}")
    assert pb_tax_threshold > 1_000_000_000, "lump sum + tax should push past $1B"

    # --- A $600M jackpot is raw-EV-positive for PB ---
    ev_600 = calculate_ev(
        "PB", 2.0, 600_000_000, *build_odds_and_prizes(pb, 600_000_000)
    )
    print(
        f"Powerball EV at $600M jackpot: {ev_600:+.3f} "
        f"(${ev_600/2:+.3f} per dollar)"
    )
    assert ev_600 > 0

    # --- NZ Lotto shared-pool odds sanity ---
    nz = games["NZ_LOTTO"]
    nz_odds, _ = build_odds_and_prizes(nz, 0)
    assert abs(nz_odds[1] - 1 / comb(40, 6)) < 1e-12, "NZ div1 = 6/40 exact"
    # div2 (5 + bonus): 6 winning combos of 5 mains, bonus must hit the 6th
    assert abs(nz_odds[2] - 6 / comb(40, 6)) < 1e-12, "NZ div2 shared-pool odds"
    print(
        f"\nNZ Lotto div1 odds: 1 in {1/nz_odds[1]:,.0f}  "
        f"div2: 1 in {1/nz_odds[2]:,.0f}"
    )

    # --- Scan (config fallback, no API key) ---
    results = scan_opportunities()
    print("\nscan_opportunities():")
    for r in results:
        print(
            f"  {r['game_name']:<22} jackpot ${r['current_jackpot']:>14,.0f} "
            f"({r['jackpot_source']})  EV ${r['ev']:+.3f}  "
            f"{r['ev_per_dollar']:+.3f}/$  -> {r['recommendation']}"
        )
    assert results and results[0]["ev_per_dollar"] >= results[-1]["ev_per_dollar"]
    assert all(r["recommendation"] in ("PLAY", "SKIP") for r in results)
    assert all(
        r["jackpot_source"] == "config" for r in results
    ), "without an API key every game must fall back to config"

    print("\nAll arbitrage self-tests passed.")
