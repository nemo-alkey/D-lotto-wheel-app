"""Game-specific pipeline deltas: Lotto vs Powerball vs Strike.

Prompt #23. Read-only report describing where the analysis pipeline diverges
per game, and why a one-size-fits-all pipeline is wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import section, subsection  # noqa: E402


def main() -> int:
    section("Game-specific pipeline deltas")

    subsection("Lotto main numbers (1-40)")
    print("""
- Pool: 40 balls, 6 drawn, no order. Bonus ball is a 7th draw.
- Era: NONE for main numbers - all history (1987+) is one distribution.
- Pipeline: uniform tests (chi_square), frequency, co-occurrence, ML
  features all apply directly to the 1-40 pool.
- Validation: 1..40; a value outside is an error, never clamped.
""")

    subsection("Powerball (era-aware)")
    print("""
- Pool: 1-10 before 2026-09-16, then 1-14 (four new balls).
- Era: MUST split. Mixing pre/post 2026-09-16 Powerball distributions is
  a silent corruption (chi-square p crashes to 0.0001).
- Pipeline: every Powerball statistic/feature/model goes through
  era_features (check_single_era, powerball_pool_size, era_flags). The
  post-change era has only ~8 draws, so a PB model must REFUSE to train
  rather than fit noise.
- Validation: era-aware max (10 or 14) via powerball_rules.
""")

    subsection("Strike (order-dependent 1-40)")
    print("""
- Pool: 40 balls, 4 drawn IN ORDER (exact-order payouts).
- Delta: order matters, so permutations are the sample space, not
  combinations. Frequency models on the unordered set are wrong; Strike
  needs positional/sequence features.
- Pipeline: none of the existing main-number scripts apply unchanged;
  Strike would need its own positional pipeline (out of scope here).
""")

    subsection("Why the pipeline must branch")
    print("""
A single draw row carries all three games, but they are three different
sample spaces:
  - Lotto:    C(40,6) unordered
  - Powerball: C(40,6) x pool (era-dependent pool size)
  - Strike:   P(40,4) ordered
Treating them as one distribution (or ignoring the Powerball era) is the
most common way these analyses silently produce garbage. The shared
scripts therefore branch on game and, for Powerball, on era.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
