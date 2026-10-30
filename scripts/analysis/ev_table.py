"""Expected value per line at various jackpot levels.

Prompts #24 and #17. Uses prize_calculator's division table.

Note: uses published average prizes. Actual amounts vary with sales
and winner counts.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import section  # noqa: E402

# ---- Official post-2026-09-16 NZ Powerball division table ----
# Odds per single $0.80 Powerball line (base Lotto line assumed).
DIVISIONS = [
    # (div, label, odds_per_line, avg_prize_nzd)
    (1, "6 mains + PB", 1 / 53_737_320, 17_200_000),
    (2, "5 + bonus + PB", 1 / 8_956_220, 45_056),
    (3, "5 + PB", 1 / 271_401, 1_406),
    (4, "4 + bonus + PB", 1 / 108_560, 131),
    (5, "4 + PB", 1 / 6_785, 70),
    (6, "3 + bonus + PB", 1 / 5_089, 50),
    (7, "3 + PB", 1 / 493, 20),
    (8, "2 + bonus + PB", 1 / 657, 12),
]
LINE_COST = 0.80  # NZD


def ev_per_line(jackpot: float | None = None) -> tuple[float, list]:
    total = 0.0
    rows = []
    for div, label, odds, prize in DIVISIONS:
        if div == 1 and jackpot is not None:
            prize = jackpot
        ev = odds * prize
        total += ev
        rows.append((div, label, odds, prize, ev))
    return total, rows


def main() -> int:
    section("NZ Powerball expected value per line")
    print(f"Line cost:         ${LINE_COST:.2f}")
    print(f"Division 1 odds:   1 in {1 / DIVISIONS[0][2]:,.0f}")
    print(f"Divisions:         {len(DIVISIONS)} (post-2026-09-16)")
    print()

    print("Baseline (minimum jackpot $5M):")
    print(f"{'Div':>4}  {'Match':>16}  {'Odds':>16}  {'Prize':>14}  {'EV':>10}")
    print("-" * 68)
    total, rows = ev_per_line(jackpot=5_000_000)
    for div, label, odds, prize, ev in rows:
        print(f"{div:>4}  {label:>16}  1 in {1 / odds:>10,.0f}  " f"${prize:>13,.0f}  ${ev:>9.4f}")
    print("-" * 68)
    print(f"{'':>4}  {'':>16}  {'':>16}  {'Total EV':>14}  ${total:>9.4f}")
    print(f"{'':>4}  {'':>16}  {'':>16}  {'Cost':>14}  ${LINE_COST:>9.2f}")
    print(f"{'':>4}  {'':>16}  {'':>16}  {'Net EV':>14}  " f"${total - LINE_COST:>+9.4f}")

    section("EV at different jackpot levels")
    print(f"{'Jackpot':>14}  {'Div1 EV':>12}  {'Total EV':>12}  {'Net EV':>12}")
    print("-" * 56)
    for jp in [5_000_000, 10_000_000, 20_000_000, 40_000_000, 60_000_000]:
        total, _ = ev_per_line(jackpot=jp)
        div1_ev = jp / 53_737_320
        net = total - LINE_COST
        print(f"${jp:>13,}  ${div1_ev:>11.4f}  ${total:>11.4f}  " f"${net:>+11.4f}")

    section("Break-even jackpot")
    other_ev, _ = ev_per_line(jackpot=0)  # Div 1 contributes 0
    div1_odds = DIVISIONS[0][2]
    breakeven = (LINE_COST - other_ev) / div1_odds
    print(f"Non-Div-1 EV:           ${other_ev:.4f}")
    print(f"Div 1 EV needed:        ${LINE_COST - other_ev:.4f}")
    print(f"Break-even jackpot:     ${breakeven:,.0f}")
    print()
    if breakeven > 60_000_000:
        print("Result: no jackpot within the $5M-$60M cap produces")
        print("        positive EV per line. The game has negative")
        print("        expected value at every legal jackpot level.")

    section("Caveats")
    print("""
1. Ignores prize-splitting. If Div 1 is shared, your share is smaller.
   A realistic EV would account for expected co-winners at each jackpot.

2. Does not model the Must Be Won mechanic at the $60M cap (jackpot
   rolls down to lower divisions rather than carrying forward).

3. Average prizes for Divisions 2-7 fluctuate with sales and winner
   counts. The figures here are published averages.

4. Odds are per single line. A Basic Lucky Dip is 8 lines; multiply by 8
   for the whole ticket. Div 1 odds for 8 lines: 1 in ~6.7M.

5. NZ lottery winnings are tax-free.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
