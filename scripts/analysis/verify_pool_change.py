"""Check chi-square uniformity for 2008+ only (post pool-1-8 era).

Hypothesis: the PB 9/10 deficit in the full-history chi-square is due
to the 2001-2007 era when the pool was 1-8. Restricting to 2008+ should
return p >= 0.05 if that's the explanation.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis._common import load_draws  # noqa: E402

try:
    from scipy.stats import chisquare
except ImportError:
    print("scipy required")
    sys.exit(1)


def chi2(counts: Counter, pool_size: int) -> tuple[float, float]:
    observed = [counts.get(i, 0) for i in range(1, pool_size + 1)]
    stat, p = chisquare(observed)
    return float(stat), float(p)


# Full pre-change era (2001 to 2026-09-15)
full = [d for d in load_draws() if d["draw_date"] < "2026-09-16" and 1 <= d["powerball"] <= 10]
counts_full = Counter(d["powerball"] for d in full)
stat, p = chi2(counts_full, 10)
print(f"Full pre-change era ({len(full)} draws):")
print(f"  Counts: {[counts_full.get(i, 0) for i in range(1, 11)]}")
print(f"  Chi-square: {stat:.2f}  p: {p:.4f}")
print()

# 2008+ only
modern = [
    d
    for d in load_draws()
    if "2008-01-01" <= d["draw_date"] < "2026-09-16" and 1 <= d["powerball"] <= 10
]
counts_mod = Counter(d["powerball"] for d in modern)
stat, p = chi2(counts_mod, 10)
print(f"2008-01-01 to 2026-09-15 ({len(modern)} draws):")
print(f"  Counts: {[counts_mod.get(i, 0) for i in range(1, 11)]}")
print(f"  Chi-square: {stat:.2f}  p: {p:.4f}")
print()

# 2008+, only balls 1-8 (control: is it the pool or the era?)
subset_1_8 = [d["powerball"] for d in modern if 1 <= d["powerball"] <= 8]
if len(subset_1_8) > 100:
    counts_1_8 = Counter(subset_1_8)
    stat, p = chi2(counts_1_8, 8)
    print(f"2008+ draws with PB in 1-8 only ({len(subset_1_8)} draws):")
    print(f"  Counts: {[counts_1_8.get(i, 0) for i in range(1, 9)]}")
    print(f"  Chi-square: {stat:.2f}  p: {p:.4f}")
    print()
