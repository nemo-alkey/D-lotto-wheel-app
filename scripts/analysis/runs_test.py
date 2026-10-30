"""Wald-Wolfowitz runs test and autocorrelation on draw sequences."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import main_number_draws, section, subsection  # noqa: E402

try:
    from scipy import stats
except ImportError:
    print("ABORT: scipy required.")
    sys.exit(1)


def runs_test(binary):
    n = len(binary)
    if n == 0:
        return 0, 0.0, 1.0
    runs = 1
    for i in range(1, n):
        if binary[i] != binary[i - 1]:
            runs += 1
    n1 = sum(binary)
    n0 = n - n1
    if n1 == 0 or n0 == 0:
        return runs, 0.0, 1.0
    mu = (2 * n1 * n0) / n + 1
    var = (2 * n1 * n0 * (2 * n1 * n0 - n)) / (n * n * (n - 1))
    if var <= 0:
        return runs, 0.0, 1.0
    z = (runs - mu) / var**0.5
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return runs, float(z), float(p)


def autocorr(series, max_lag=10):
    n = len(series)
    if n < 2:
        return []
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / n
    if var == 0:
        return [(lag, 0.0) for lag in range(1, max_lag + 1)]
    out = []
    for lag in range(1, max_lag + 1):
        num = sum((series[i] - mean) * (series[i + lag] - mean) for i in range(n - lag))
        denom = (n - lag) * var
        out.append((lag, float(num / denom) if denom else 0.0))
    return out


def main():
    draws = main_number_draws()
    print(f"Loaded {len(draws)} draws")
    if len(draws) < 50:
        print("Not enough draws.")
        return 1

    section("Runs test: draw sum above/below median")
    sums = [sum(d["numbers"]) for d in draws]
    median_sum = sorted(sums)[len(sums) // 2]
    binary = [1 if s > median_sum else 0 for s in sums]
    runs, z, p = runs_test(binary)
    print(f"Median threshold:    {median_sum}")
    print(f"Above/below:         {sum(binary)} / {len(binary) - sum(binary)}")
    print(f"Runs observed:       {runs}")
    print(f"Z statistic:         {z:.3f}")
    print(f"p-value (2-sided):   {p:.4f}")
    print()
    if p < 0.05:
        print("Result: p<0.05 - run pattern deviates from independence.")
    else:
        print("Result: consistent with independence.")

    section("Runs test: Powerball above/below median by era")
    for era_label, era_key in [
        ("Pre-2026-09-16", "pre_2026_09_16"),
        ("Post-2026-09-16", "post_2026_09_16"),
    ]:
        subset = [d for d in draws if d["rule_era"] == era_key and d["powerball"] > 0]
        subsection(era_label)
        if len(subset) < 30:
            print(f"Only {len(subset)} draws - too few.")
            continue
        pbs = [d["powerball"] for d in subset]
        median_pb = sorted(pbs)[len(pbs) // 2]
        binary = [1 if p > median_pb else 0 for p in pbs]
        runs, z, p = runs_test(binary)
        print(f"Draws:             {len(subset)}")
        print(f"Median threshold:  {median_pb}")
        print(f"Runs observed:     {runs}")
        print(f"Z statistic:       {z:.3f}")
        print(f"p-value:           {p:.4f}")
        if p < 0.05:
            print("Result: p<0.05 - potential non-independence.")
        else:
            print("Result: consistent with independence.")

    section("Autocorrelation: draw sums, lags 1-10")
    acf = autocorr([float(s) for s in sums], max_lag=10)
    n = len(sums)
    threshold = 1.96 / (n**0.5)
    print(f"{'Lag':>4}  {'Correlation':>12}  {'Significant?':>14}")
    print("-" * 36)
    for lag, corr in acf:
        sig = "yes" if abs(corr) > threshold else "no"
        print(f"{lag:>4}  {corr:>12.4f}  {sig:>14}")
    print()
    print(f"95% band: +/-{threshold:.4f}")

    section("Autocorrelation: Powerball (post-change era)")
    post = [d for d in draws if d["rule_era"] == "post_2026_09_16" and d["powerball"] > 0]
    if len(post) < 30:
        print(f"Only {len(post)} post-change draws. Skipping.")
    else:
        acf_pb = autocorr([float(d["powerball"]) for d in post], max_lag=10)
        for lag, corr in acf_pb:
            print(f"{lag:>4}  {corr:>12.4f}")

    section("Interpretation")
    print("""
The runs test asks: does the sequence alternate more or less than
chance would predict? Too few runs -> positive autocorrelation.

Autocorrelation asks: is draw t correlated with draw t-lag?

Under randomness:
  - Runs observed close to expected (z near 0, p > 0.05)
  - Correlations inside +/-1.96/sqrt(n)
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
