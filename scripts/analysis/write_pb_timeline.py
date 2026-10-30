"""Timeline of Powerball counts per year to locate the 9/10 deficit."""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

DB = Path("data/lotto.db")
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT draw_date, powerball FROM draws "
    "WHERE rule_era = 'pre_2026_09_16' AND powerball BETWEEN 1 AND 10 "
    "ORDER BY draw_date"
).fetchall()

by_year: dict[int, Counter] = {}
for r in rows:
    year = int(r["draw_date"][:4])
    by_year.setdefault(year, Counter())[r["powerball"]] += 1

print(
    f"{'Year':>5}  {'N':>5}  {'P1':>4} {'P2':>4} {'P3':>4} {'P4':>4} "
    f"{'P5':>4} {'P6':>4} {'P7':>4} {'P8':>4} {'P9':>4} {'P10':>4}"
)
print("-" * 76)
for year in sorted(by_year):
    c = by_year[year]
    total = sum(c.values())
    print(f"{year:>5}  {total:>5}  " + "  ".join(f"{c.get(i, 0):>3}" for i in range(1, 11)))

print()
print("Totals across all years:")
totals = Counter()
for c in by_year.values():
    totals.update(c)
print(f"  {dict(sorted(totals.items()))}")
print(f"  P9+P10: {totals.get(9, 0) + totals.get(10, 0)}")
print(f"  P1-P8:  {sum(totals.get(i, 0) for i in range(1, 9))}")
print(
    f"  Ratio P9+P10 / P1-P8: "
    f"{(totals.get(9, 0) + totals.get(10, 0)) / sum(totals.get(i, 0) for i in range(1, 9)):.4f}"
)
print(f"  Expected ratio for uniform: {2/8:.4f}")
