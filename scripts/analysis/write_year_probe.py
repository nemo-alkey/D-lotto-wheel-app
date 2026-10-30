"""Probe specific years for PB anomalies.

Investigates two suspected data gaps:
  2001-2007: PB 9 and 10 both absent from every year
  2013:      PB 6 and 9 both absent from every year
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path("data/lotto.db")
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# ---- Part 1: full PB distribution for each suspect year ----
print("=" * 70)
print("Part 1: PB distribution per year, 2001-2008")
print("=" * 70)
for year in range(2001, 2009):
    rows = conn.execute(
        "SELECT powerball, COUNT(*) AS n FROM draws "
        "WHERE draw_date LIKE ? GROUP BY powerball ORDER BY powerball",
        (f"{year}%",),
    ).fetchall()
    counts = {r["powerball"]: r["n"] for r in rows}
    total = sum(counts.values())
    print(f"  {year}: total={total:>4}  counts={dict(sorted(counts.items()))}")

print()
print("=" * 70)
print("Part 2: PB distribution per year, 2012-2014")
print("=" * 70)
for year in range(2012, 2015):
    rows = conn.execute(
        "SELECT powerball, COUNT(*) AS n FROM draws "
        "WHERE draw_date LIKE ? GROUP BY powerball ORDER BY powerball",
        (f"{year}%",),
    ).fetchall()
    counts = {r["powerball"]: r["n"] for r in rows}
    total = sum(counts.values())
    print(f"  {year}: total={total:>4}  counts={dict(sorted(counts.items()))}")

# ---- Part 3: raw rows with PB=0 in suspect years ----
print()
print("=" * 70)
print("Part 3: rows with powerball=0 in suspect years")
print("=" * 70)
for year in [2006, 2007, 2013]:
    zeros = conn.execute(
        "SELECT draw_date, numbers, bonus, powerball FROM draws "
        "WHERE draw_date LIKE ? AND powerball = 0 ORDER BY draw_date",
        (f"{year}%",),
    ).fetchall()
    print(f"\n  {year}: {len(zeros)} row(s) with PB=0")
    for r in zeros[:5]:
        print(
            f"    {r['draw_date']}  numbers={r['numbers']}  bonus={r['bonus']}  pb={r['powerball']}"
        )
    if len(zeros) > 5:
        print(f"    ... {len(zeros) - 5} more")

# ---- Part 4: all distinct PB values in 2013 ----
print()
print("=" * 70)
print("Part 4: every distinct PB value in 2013")
print("=" * 70)
vals = conn.execute(
    "SELECT DISTINCT powerball FROM draws " "WHERE draw_date LIKE '2013%' ORDER BY powerball"
).fetchall()
print(f"  Distinct PB values: {[r['powerball'] for r in vals]}")

# ---- Part 5: sample 2013 rows, sorted by date, to eyeball the sequence ----
print()
print("=" * 70)
print("Part 5: first 15 rows of 2013 (raw)")
print("=" * 70)
rows = conn.execute(
    "SELECT draw_date, numbers, bonus, powerball FROM draws "
    "WHERE draw_date LIKE '2013%' ORDER BY draw_date LIMIT 15"
).fetchall()
for r in rows:
    print(
        f"  {r['draw_date']}  numbers={r['numbers']:>26}  bonus={r['bonus']:>3}  pb={r['powerball']}"
    )

# ---- Part 6: what does a normal year look like, for contrast ----
print()
print("=" * 70)
print("Part 6: PB distribution for a healthy year (2019)")
print("=" * 70)
rows = conn.execute(
    "SELECT powerball, COUNT(*) AS n FROM draws "
    "WHERE draw_date LIKE '2019%' GROUP BY powerball ORDER BY powerball",
).fetchall()
counts = {r["powerball"]: r["n"] for r in rows}
print(f"  2019: total={sum(counts.values())}  counts={dict(sorted(counts.items()))}")

print()
print("=" * 70)
print("Summary")
print("=" * 70)
print("""
If Part 1 shows 2001-2007 with P9=P10=0 but P1-P8 normal, that's a data gap:
either the source data is wrong, or ingestion dropped those values.

If Part 3 shows powerball=0 for affected rows, the repair pipeline can fix
them. If Part 3 shows valid-looking values, we need to re-fetch from the
official API.

Part 4 tells us exactly which PB values exist in 2013.
Part 5 shows whether the missing values are scattered or clustered in a
specific span of dates (which would point at a specific scraping window).
""")
