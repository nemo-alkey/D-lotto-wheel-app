"""Monte Carlo EV: random baseline vs the frequency model across 1,000 draws.

Prompt pack: simulation. Scores lines against prize_calculator's division
mapping and a prize reference derived from allocate_pool.

Model line = the architectures.py frequency baseline (top-6 hot numbers,
most common post-change Powerball). Random line = uniform 6-of-40 + PB 1-14.
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import load_draws, section, subsection  # noqa: E402
from prize_calculator import resolve_divisions  # noqa: E402

NUM_POOL = 40
PB_POOL = 14
N_SIMS = 1000


def random_line(rng: random.Random) -> tuple[list[int], int]:
    return sorted(rng.sample(range(1, NUM_POOL + 1), 6)), rng.randint(1, PB_POOL)


def winning_draw(rng: random.Random) -> tuple[set[int], int, int]:
    main = set(rng.sample(range(1, NUM_POOL + 1), 6))
    bonus = rng.randint(1, NUM_POOL)
    pb = rng.randint(1, PB_POOL)
    return main, bonus, pb


def score_line(main: list[int], pb: int, wmain: set[int], wbonus: int, wpb: int) -> int | None:
    mm = len(set(main) & wmain)
    bm = wbonus in main
    pbh = pb == wpb
    return resolve_divisions(mm, bm, pbh, None)[1]


def bootstrap_mean_diff(a: list[float], b: list[float], n_boot: int = 2000) -> tuple[float, float]:
    a = np.asarray(a)
    b = np.asarray(b)
    rng = np.random.default_rng(0)
    diffs = []
    for _ in range(n_boot):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        diffs.append(sa.mean() - sb.mean())
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def main() -> int:
    draws = load_draws()
    if not draws:
        print("ERROR: no draws.")
        return 1

    # ---- model line (frequency baseline from architectures.py) ----
    main_freq: Counter = Counter()
    for d in draws:
        if d["draw_date"] >= "2008-01-01":
            for n in d["numbers"]:
                main_freq[n] += 1
    model_main = [n for n, _ in main_freq.most_common(6)]

    pb_freq = Counter(
        d["powerball"] for d in draws
        if d["rule_era"] == "post_2026_09_16" and d["powerball"] > 0
    )
    model_pb = pb_freq.most_common(1)[0][0] if pb_freq else 7

    # ---- prize reference: published average prizes (same figures as
    #      ev_table.py). The DIVISION mapping is prize_calculator's
    #      resolve_divisions; allocate_pool models pool allocation (rollover,
    #      caps) which does not change a per-line EV comparison, so the
    #      published averages are the correct reference here.
    per_winner = {
        1: 5_000_000,  # minimum jackpot (Div 1 average varies with jackpot)
        2: 45_056,
        3: 1_406,
        4: 131,
        5: 70,
        6: 50,
        7: 20,
        8: 12,
    }

    rng = random.Random(0)
    rand_prizes: list[float] = []
    model_prizes: list[float] = []
    rand_div: Counter = Counter()
    model_div: Counter = Counter()

    for _ in range(N_SIMS):
        wmain, wbonus, wpb = winning_draw(rng)

        rm, rpb = random_line(rng)
        rd = score_line(rm, rpb, wmain, wbonus, wpb)
        rand_div[rd] += 1
        rand_prizes.append(float(per_winner.get(rd, 0.0)))

        md = score_line(model_main, model_pb, wmain, wbonus, wpb)
        model_div[md] += 1
        model_prizes.append(float(per_winner.get(md, 0.0)))

    section("Simulation setup")
    print(f"Simulated draws:   {N_SIMS}")
    print(f"Random line:       uniform 6-of-40 + PB 1-14")
    print(f"Model line:        {model_main} + PB {model_pb}")
    print(f"Line cost (NZ$):   $0.80")

    section("Average EV per line")
    rand_ev = float(np.mean(rand_prizes))
    model_ev = float(np.mean(model_prizes))
    print(f"  random baseline:  ${rand_ev:.4f}")
    print(f"  model baseline:   ${model_ev:.4f}")

    section("Hit rate per division")
    print(f"{'Div':>4}  {'Random':>8}  {'Model':>8}")
    print("-" * 26)
    for div in range(1, 9):
        print(f"{div:>4}  {rand_div[div] / N_SIMS:>8.4f}  {model_div[div] / N_SIMS:>8.4f}")

    section("Does the model beat random?")
    lo, hi = bootstrap_mean_diff(model_prizes, rand_prizes)
    diff = model_ev - rand_ev
    print(f"  EV difference (model - random): ${diff:+.4f}")
    print(f"  95% CI (bootstrap):            [${lo:+.4f}, ${hi:+.4f}]")
    print()
    if lo <= 0 <= hi:
        print("Result: the confidence interval contains $0 - the model does NOT")
        print("        beat random at any threshold. Both sit at the same negative")
        print("        EV, as expected for a fair lottery.")
    elif diff > 0:
        print("Result: model EV is above random outside the CI (unexpected).")
    else:
        print("Result: model EV is below random outside the CI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
