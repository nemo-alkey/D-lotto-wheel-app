"""Compare three ML framings for predicting NZ Lotto draws.

Prompt pack: framing the problem. Read-only; no model training.

The three framings make different bets about what is learnable:
  a. multi-label classification (6-of-40)
  b. per-number binary classifier (40 independent)
  c. sequence prediction (LSTM-style next draw)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import section, subsection  # noqa: E402


def main() -> int:
    section("Framing the problem: three ways to model a draw")

    subsection("(a) Multi-label classification - predict the 6-of-40 set")
    print("""
Loss:          binary cross-entropy per number (or a set-based loss).
Output layer:  40 sigmoid units, one per number; take top-6 as the line.
Sample use:    every draw is one sample with 40 labels (6 positive).

Pros:
  - Models the draw as one object; can learn set-level structure.
  - Output is directly a "line" (top-6), matching what a player buys.
Cons:
  - 6 positives out of 40 -> heavy class imbalance (0.15 positive rate).
  - Top-6 is a threshold/ranking choice, not a calibrated probability.
  - If the game is fair, the Bayes-optimal output is uniform -> the
    model can only learn the null model (plus noise).
Bias:          tends to regress toward uniform over time, which is honest
               but useless for "picking" numbers.

Worked example (draw 2309, 2023-09-20):
  Model outputs p(n) for all 40 numbers; a calibrated model returns
  p(n) ~ 0.15 for every n (6/40). The top-6 are then arbitrary. A naive
  model that has memorised a hot number outputs p(38)=0.22 and the rest
  ~0.14; its top-6 will contain 38. If 38 is not drawn, that "edge" is
  pure variance.
""")

    subsection("(b) Per-number binary classifier - 40 independent models")
    print("""
Loss:          binary cross-entropy per number.
Output layer:  1 sigmoid per model (40 models), or a shared network with
               a 40-way head.
Sample use:    each (draw, number) is one sample -> 40x the data.

Pros:
  - Reuses the (draw, number) feature matrix directly (features.py).
  - 40x sample count relative to framing (a).
  - Each number gets its own bias correction; easy to rank by confidence.
Cons:
  - Treats numbers as independent, so it cannot express co-occurrence
    or "exactly 6" constraints.
  - The 40 models share the same label distribution (hit rate ~0.15),
    so a single shared model is equivalent and simpler.
Bias:          independence assumption; co-occurrence signals (pair
               affinity) are lost unless added as explicit features.

Worked example:
  For number 7 the training rows are (draw_1, hit=0), (draw_2, hit=1), ...
  With ~2628 draws there are ~2628 rows per number and ~394 hits each.
  The model learns p(hit | features). At inference you score all 40
  numbers for the next draw and sort descending.
""")

    subsection("(c) Sequence prediction - LSTM over recent draws")
    print("""
Loss:          cross-entropy over a 40-way (or 14-way PB) vocabulary, or
               a regression to the next draw's number multiset.
Output layer:  40-way softmax (main) or a 14-way softmax (Powerball),
               autoregressively emitting 6 numbers.
Sample use:    a window of the last N draws -> the next draw.

Pros:
  - Uses temporal order; can (in principle) model short-range structure.
  - Natural for the Powerball sequence across eras.
Cons:
  - Needs the most data and is the most prone to overfitting a fair game.
  - Autoregressive decoding needs a "no repeat" constraint (sample without
    replacement), otherwise it can emit duplicate numbers.
  - If draws are i.i.d., an LSTM reduces to the marginal distribution and
    learns nothing beyond the frequency baseline.
Bias:          recency bias; long training windows mix Powerball eras and
               must pass the era_features guard.

Worked example:
  Input: last 10 draws' 6-number sets. Target: draw 10's set.
  A trained LSTM would be expected to output a flat ~6/40 distribution if
  the data is fair; any deviation is memorisation. The autoregressive
  decoder samples 6 numbers without replacement from the softmax.
""")

    section("Recommendation")
    print("""
For a fair lottery the honest answer is that no framing beats uniform.
Framing (b) is the pragmatic choice for this repo: it reuses features.py,
handles the era split cleanly, and gives a confidence ranking that
candidate_sets.py can turn into lines. Framings (a) and (c) add model
complexity with no expected edge, but are listed so the trade-offs are
explicit.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
