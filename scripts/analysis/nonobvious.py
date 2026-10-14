"""Non-obvious AI strategies for a fair lottery, and their honest limits.

Prompt #28. Read-only. The genuinely non-obvious finding is that the best
"AI strategy" on a fair draw is mostly about what NOT to do, and about
exploiting the only two real, non-random edges: split-risk and bankroll.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import section, subsection  # noqa: E402


def main() -> int:
    section("Non-obvious AI strategies (and their honest limits)")

    subsection("1. The model's best output is uniform")
    print("""
Any honest model trained on a fair 6-of-40 draw converges to a flat
6/40 probability per number. A model that confidently outputs a "hot"
number is overfitting. The non-obvious strategy: use the model as a
sanity check, not a predictor - if it does NOT converge to uniform,
treat that as a bug or a data leak.
""")

    subsection("2. Split-risk minimization is the only real edge")
    print("""
Winning odds are fixed, but the PRIZE you share is not. Popular numbers
(1-31 birthdays, 7, lucky numbers) split the jackpot more often. The one
genuine, non-random lever is to pick an UNPOPULAR line so that, on the
rare win, you share with fewer people. This is not "more likely to win" -
it is "win more if you do".
""")

    subsection("3. Progressions and 'due' numbers are traps")
    print("""
Martingale/progressive staking cannot turn a negative-EV game positive;
it only raises variance until a loss wipes the bankroll. "Overdue"
numbers are the gambler's fallacy: the balls have no memory. A strategy
must be measured against EV, which is negative at every legal jackpot.
""")

    subsection("4. Syndicates trade EV for variance")
    print("""
A syndicate does not raise EV - it buys more tickets, so it raises the
probability of a (shared) win while lowering the per-person payoff. The
only non-obvious value is risk pooling: smaller, more frequent wins at
lower variance.
""")

    subsection("5. Sequence models add nothing on fair data")
    print("""
LSTMs/transformers on i.i.d. draws reduce to the marginal distribution.
If a sequence model ever "beats" the frequency baseline on a fair game,
suspect leakage through a feature that peeks at the current draw (see
features.py cooccur_score history). The non-obvious deliverable of a
sequence experiment is the leak audit, not the model.
""")

    section("Bottom line")
    print("""
The honest conclusion of the whole pack: no AI strategy makes a fair
lottery +EV. The useful engineering outcomes are (a) correct era-aware
data handling, (b) a leak-free feature pipeline, and (c) a clear,
disclaimed report - all of which the other scripts in this directory
provide.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
