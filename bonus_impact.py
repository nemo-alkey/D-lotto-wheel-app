"""
bonus_impact.py
===============
Quantifies the bonus ball's value in backtests.
Tracks division upgrades (e.g. Div 3 -> Div 2) and EV contribution.
Provides a "What-If" toggle for manual bonus override.

Integrates with: backtest.py, prize_calculator.py, dashboard.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# NZ Lotto division rules (6 main + 1 bonus, 40-number pool)
# Div 1: 6 main
# Div 2: 5 main + bonus
# Div 3: 5 main
# Div 4: 4 main + bonus
# Div 5: 4 main
# Div 6: 3 main + bonus
# Div 7: 3 main

DIVISION_RULES = {
    1: {"main": 6, "bonus": False},
    2: {"main": 5, "bonus": True},
    3: {"main": 5, "bonus": False},
    4: {"main": 4, "bonus": True},
    5: {"main": 4, "bonus": False},
    6: {"main": 3, "bonus": True},
    7: {"main": 3, "bonus": False},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TicketResult:
    """Result for a single ticket against one draw."""

    ticket_numbers: list[int]
    main_matches: int
    bonus_matched: bool
    division: int | None  # None if no win
    division_without_bonus: int | None  # What division if bonus was ignored
    upgraded_by_bonus: bool  # Did bonus improve the division?
    prize: float = 0.0
    prize_without_bonus: float = 0.0


@dataclass
class BonusImpactReport:
    """Aggregated report across many draws / tickets."""

    total_draws: int
    total_tickets_played: int
    total_wins: int
    wins_upgraded_by_bonus: int
    total_prize_with_bonus: float
    total_prize_without_bonus: float
    bonus_premium_value: float  # $ added by bonus
    bonus_premium_pct: float  # % of total EV from bonus
    upgrade_breakdown: dict[int, int] = field(default_factory=dict)  # div -> count
    division_distribution: dict[int, int] = field(default_factory=dict)
    per_draw_impact: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def check_division(main_matches: int, bonus_matched: bool) -> int | None:
    """Return division number (1-7) or None."""
    for div, rule in DIVISION_RULES.items():
        if main_matches == rule["main"] and bonus_matched == rule["bonus"]:
            return div
    return None


def check_division_without_bonus(main_matches: int) -> int | None:
    """Division if bonus ball is ignored entirely (Standard Lotto rules)."""
    # Without bonus: 6=Div1, 5=Div3, 4=Div5, 3=Div7
    mapping = {6: 1, 5: 3, 4: 5, 3: 7}
    return mapping.get(main_matches)


def evaluate_ticket(
    ticket: list[int],
    drawn_main: list[int],
    drawn_bonus: int,
    prize_lookup: dict[int, float] | None = None,
) -> TicketResult:
    """
    Evaluate one ticket against a draw.

    Args:
        ticket: 6 numbers on the ticket
        drawn_main: 6 main numbers drawn
        drawn_bonus: 1 bonus number drawn
        prize_lookup: Dict[division] -> prize amount. If None, prizes are 0.
    """
    main_matches = len(set(ticket) & set(drawn_main))
    bonus_matched = drawn_bonus in ticket

    div = check_division(main_matches, bonus_matched)
    div_no_bonus = check_division_without_bonus(main_matches)

    upgraded = False
    if div is not None and div_no_bonus is not None:
        upgraded = div < div_no_bonus  # lower div number = better prize
    elif div is not None and div_no_bonus is None:
        upgraded = True  # bonus turned a non-win into a win

    prize = prize_lookup.get(cast(int, div), 0.0) if prize_lookup else 0.0
    prize_no = prize_lookup.get(cast(int, div_no_bonus), 0.0) if prize_lookup else 0.0

    return TicketResult(
        ticket_numbers=ticket,
        main_matches=main_matches,
        bonus_matched=bonus_matched,
        division=div,
        division_without_bonus=div_no_bonus,
        upgraded_by_bonus=upgraded,
        prize=prize,
        prize_without_bonus=prize_no,
    )


def evaluate_draw(
    tickets: list[list[int]],
    drawn_main: list[int],
    drawn_bonus: int,
    prize_lookup: dict[int, float] | None = None,
) -> list[TicketResult]:
    """Evaluate all tickets for one draw."""
    return [evaluate_ticket(t, drawn_main, drawn_bonus, prize_lookup) for t in tickets]


# ---------------------------------------------------------------------------
# What-If toggle
# ---------------------------------------------------------------------------


def what_if_bonus_override(
    ticket: list[int],
    drawn_main: list[int],
    drawn_bonus: int,
    force_bonus_match: bool,
    prize_lookup: dict[int, float] | None = None,
) -> TicketResult:
    """
    Manually override whether the bonus ball was matched.
    Useful for exploring "If I had matched the bonus, what division?"
    """
    main_matches = len(set(ticket) & set(drawn_main))
    bonus_matched = force_bonus_match  # override

    # Recompute division with forced bonus status
    div = None
    for d, rule in DIVISION_RULES.items():
        if main_matches == rule["main"] and bonus_matched == rule["bonus"]:
            div = d
            break

    div_no_bonus = check_division_without_bonus(main_matches)
    prize = prize_lookup.get(cast(int, div), 0.0) if prize_lookup else 0.0
    prize_no = prize_lookup.get(cast(int, div_no_bonus), 0.0) if prize_lookup else 0.0

    upgraded = False
    if div is not None and div_no_bonus is not None:
        upgraded = div < div_no_bonus
    elif div is not None and div_no_bonus is None:
        upgraded = True

    return TicketResult(
        ticket_numbers=ticket,
        main_matches=main_matches,
        bonus_matched=bonus_matched,
        division=div,
        division_without_bonus=div_no_bonus,
        upgraded_by_bonus=upgraded,
        prize=prize,
        prize_without_bonus=prize_no,
    )


# ---------------------------------------------------------------------------
# Backtest aggregation
# ---------------------------------------------------------------------------


def run_bonus_impact_backtest(
    tickets_per_draw: list[list[list[int]]],  # [draw][ticket][number]
    draws_main: list[list[int]],
    draws_bonus: list[int],
    prize_lookup: dict[int, float] | None = None,
    historical_prizes: list[dict[int, float]] | None = None,
    force_bonus_match: bool = False,
) -> BonusImpactReport:
    """
    Run full backtest across many draws.

    Args:
        tickets_per_draw: List of ticket sets, one per draw.
        draws_main: Main numbers for each draw.
        draws_bonus: Bonus number for each draw.
        prize_lookup: Static prize amounts per division.
        historical_prizes: Optional list of dicts, one per draw, for variable prizes.
        force_bonus_match: If True, score every ticket as if it matched the
            bonus ball (What-If "maximum upside" mode). Tickets with 6 main
            matches still count as Division 1 — the bonus is irrelevant there.
    """
    report = BonusImpactReport(
        total_draws=len(draws_main),
        total_tickets_played=0,
        total_wins=0,
        wins_upgraded_by_bonus=0,
        total_prize_with_bonus=0.0,
        total_prize_without_bonus=0.0,
        bonus_premium_value=0.0,
        bonus_premium_pct=0.0,
    )

    for i, (tickets, main, bonus) in enumerate(
        zip(tickets_per_draw, draws_main, draws_bonus, strict=False)
    ):
        lookup = historical_prizes[i] if historical_prizes else prize_lookup
        if force_bonus_match:
            results = []
            for t in tickets:
                r = what_if_bonus_override(t, main, bonus, True, lookup)
                if r.main_matches == 6 and r.division is None:
                    # 6 main matches always win Div 1; bonus is irrelevant
                    r.division = 1
                    r.prize = lookup.get(1, 0.0) if lookup else 0.0
                results.append(r)
        else:
            results = evaluate_draw(tickets, main, bonus, lookup)

        draw_wins = 0
        draw_upgrades = 0
        draw_prize = 0.0
        draw_prize_no = 0.0

        for r in results:
            report.total_tickets_played += 1
            if r.division is not None:
                report.total_wins += 1
                draw_wins += 1
                report.division_distribution[r.division] = (
                    report.division_distribution.get(r.division, 0) + 1
                )
            if r.upgraded_by_bonus:
                report.wins_upgraded_by_bonus += 1
                draw_upgrades += 1
                report.upgrade_breakdown[cast(int, r.division)] = (
                    report.upgrade_breakdown.get(cast(int, r.division), 0) + 1
                )

            draw_prize += r.prize
            draw_prize_no += r.prize_without_bonus

        report.total_prize_with_bonus += draw_prize
        report.total_prize_without_bonus += draw_prize_no

        report.per_draw_impact.append(
            {
                "draw_index": i,
                "tickets": len(tickets),
                "wins": draw_wins,
                "upgrades": draw_upgrades,
                "prize_with_bonus": draw_prize,
                "prize_without_bonus": draw_prize_no,
                "bonus_premium": draw_prize - draw_prize_no,
            }
        )

    report.bonus_premium_value = report.total_prize_with_bonus - report.total_prize_without_bonus
    if report.total_prize_with_bonus > 0:
        report.bonus_premium_pct = report.bonus_premium_value / report.total_prize_with_bonus * 100

    return report


def report_to_markdown(report: BonusImpactReport) -> str:
    """Convert report to a readable markdown summary."""
    lines = [
        "# Bonus Impact Backtest Report",
        "",
        f"- **Total draws backtested:** {report.total_draws}",
        f"- **Total tickets played:** {report.total_tickets_played}",
        f"- **Total wins:** {report.total_wins}",
        f"- **Wins upgraded by bonus:** {report.wins_upgraded_by_bonus}",
        "",
        "## Financial Impact",
        f"- **Total prize (with bonus):** ${report.total_prize_with_bonus:,.2f}",
        f"- **Total prize (without bonus):** ${report.total_prize_without_bonus:,.2f}",
        f"- **Bonus premium value:** ${report.bonus_premium_value:,.2f}",
        f"- **Bonus premium % of EV:** {report.bonus_premium_pct:.2f}%",
        "",
        "## Division Distribution",
    ]
    for div in sorted(report.division_distribution.keys()):
        lines.append(f"- Division {div}: {report.division_distribution[div]} wins")

    if report.upgrade_breakdown:
        lines.extend(["", "## Upgrades Triggered by Bonus"])
        for div in sorted(report.upgrade_breakdown.keys()):
            lines.append(f"- Upgraded to Division {div}: {report.upgrade_breakdown[div]} times")

    lines.extend(["", "## Per-Draw Summary (last 5)"])
    for d in report.per_draw_impact[-5:]:
        lines.append(
            f"- Draw {d['draw_index']}: {d['wins']} wins, "
            f"{d['upgrades']} bonus upgrades, "
            f"premium=${d['bonus_premium']:.2f}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standard Lotto (no Powerball) helper
# ---------------------------------------------------------------------------


def standard_lotto_results(
    tickets: list[list[int]],
    drawn_main: list[int],
    prize_lookup: dict[int, float] | None = None,
) -> list[TicketResult]:
    """
    Evaluate tickets under Standard Lotto rules (no bonus ball required).
    Divisions: 6=Div1, 5=Div2, 4=Div3, 3=Div4.
    """
    results = []
    for ticket in tickets:
        main_matches = len(set(ticket) & set(drawn_main))
        # Standard Lotto divisions
        std_div = None
        if main_matches == 6:
            std_div = 1
        elif main_matches == 5:
            std_div = 2
        elif main_matches == 4:
            std_div = 3
        elif main_matches == 3:
            std_div = 4

        prize = prize_lookup.get(cast(int, std_div), 0.0) if prize_lookup else 0.0

        results.append(
            TicketResult(
                ticket_numbers=ticket,
                main_matches=main_matches,
                bonus_matched=False,
                division=std_div,
                division_without_bonus=std_div,
                upgraded_by_bonus=False,
                prize=prize,
                prize_without_bonus=prize,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Demo backtest
    tickets = [
        [[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]],
        [[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]],
    ]
    draws_main = [[1, 2, 3, 4, 5, 40], [1, 2, 3, 4, 5, 6]]
    draws_bonus = [6, 7]
    prizes: dict[int, float] = {1: 1_000_000, 2: 50_000, 3: 5_000, 4: 500, 5: 50, 6: 20, 7: 10}

    report = run_bonus_impact_backtest(tickets, draws_main, draws_bonus, prizes)
    print(report_to_markdown(report))
    print("\n--- What-If Demo ---")
    r = what_if_bonus_override([1, 2, 3, 4, 5, 40], [1, 2, 3, 4, 5, 6], 40, True, prizes)
    print(f"Forced bonus match: Div {r.division}, upgraded={r.upgraded_by_bonus}, prize=${r.prize}")
