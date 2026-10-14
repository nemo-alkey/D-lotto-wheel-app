"""Chi-square uniformity test on NZ Lotto mains and Powerball.

Prompt #9 from the Covella prompt pack. Read-only.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import main_number_draws, section, subsection  # noqa: E402

try:
    from scipy.stats import chisquare
except ImportError:
    print("ABORT: scipy required. python -m pip install scipy")
    sys.exit(1)


def chi_square_uniform(counts: Counter, pool_size: int) -> tuple[float, int, float]:
    observed = [counts.get(i, 0) for i in range(1, pool_size + 1)]
    stat, p = chisquare(observed)
    return float(stat), pool_size - 1, float(p)


def main() -> int:
    draws = main_number_draws()
    print(f"Loaded {len(draws)} draws")
    if not draws:
        return 1

    # ---- Main numbers ----
    section("Chi-square: NZ Lotto main numbers (1-40, all history)")
    counts: Counter = Counter()
    for d in draws:
        for n in d["numbers"]:
            counts[n] += 1
    total = sum(counts.values())
    print(f"Total number appearances: {total}")
    print(f"Expected per number:      {total / 40:.1f}")
    stat, df, p = chi_square_uniform(counts, 40)
    print(f"Chi-square statistic:     {stat:.2f}")
    print(f"Degrees of freedom:       {df}")
    print(f"p-value:                  {p:.4f}")
    print()
    if p < 0.05:
        print("Result: REJECT uniformity at p<0.05. Significant deviation.")
    else:
        print("Result: consistent with uniformity. The main-number")
        print("        frequencies look like a fair random process.")

    # ---- Powerball, era split ----
    section("Chi-square: Powerball by era")

    for era_label, era_key, pool_size, min_date, max_date in [
        ("2001-2007 (pool 1-8, excluded)", "pre_2026_09_16", 8, None, "2008-01-01"),
        ("2008-2026-09-15 (pool 1-10)", "pre_2026_09_16", 10, "2008-01-01", None),
        ("Post-2026-09-16 (pool 1-14)", "post_2026_09_16", 14, None, None),
    ]:
        subset = [
            d for d in draws
            if d["rule_era"] == era_key
            and d["powerball"] is not None
            and 1 <= d["powerball"] <= pool_size
            and (min_date is None or d["draw_date"] >= min_date)
            and (max_date is None or d["draw_date"] < max_date)
        ]
        subsection(era_label)
        if not subset:
            print("No draws with a valid Powerball in this era.")
            continue
        pb_counts: Counter = Counter()
        for d in subset:
            pb_counts[d["powerball"]] += 1
        pb_total = sum(pb_counts.values())
        print(f"Draws in era:          {len(subset)}")
        print(f"PB appearances:        {pb_total}")
        print(f"Expected per PB:       {pb_total / pool_size:.1f}")
        if max_date is not None:
            # Pre-2008 window: the Powerball pool was 1-8, not 1-10. Excluded
            # from the uniformity test because the pool size changed in 2008,
            # so its distribution is not comparable with the 1-10 era after it.
            print("Excluded - pool 1-8 era (pool size changed in 2008).")
            continue
        if pb_total < 2 * pool_size:
            print("Sample too small for a reliable chi-square. Skipping.")
            continue
        print(f"Counts: {[pb_counts.get(i, 0) for i in range(1, pool_size + 1)]}")
        stat, df, p = chi_square_uniform(pb_counts, pool_size)
        print(f"Chi-square statistic:  {stat:.2f}")
        print(f"Degrees of freedom:    {df}")
        print(f"p-value:               {p:.4f}")
        if p < 0.05:
            print("Result: p<0.05. Sample deviates from uniform. With small")
            print("        samples this is often spurious - interpret with")
            print("        the sample size in mind.")
        else:
            print("Result: consistent with uniform.")

    section("How to read this")
    print("""
Chi-square asks: if the drawing machine were fair, how likely is it
that we would see frequencies this far from uniform?

  p < 0.05   unusual; investigate
  p >= 0.05  consistent with randomness

For NZ Lotto mains (2,400+ draws, 6 numbers each), the expectation is
uniform behaviour. A clean p >= 0.05 here confirms the game is behaving
as a random process.

For Powerball, sample size matters. The post-change era currently has
only 8 draws, so its chi-square result is not statistically meaningful.
The pre-change era has ~1,700 draws and can support the test.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())