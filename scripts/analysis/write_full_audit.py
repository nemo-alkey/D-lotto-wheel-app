"""Full year-by-year draw audit — no PB filter."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path("data/lotto.db")
conn = sqlite3.connect(DB)

print(f"{'Year':>5}  {'Rows':>5}  {'Expected':>9}  {'Gap':>6}  {'Earliest':>12}  {'Latest':>12}")
print("-" * 68)

for year in range(1987, 2027):
    row = conn.execute(
        "SELECT COUNT(*), MIN(draw_date), MAX(draw_date) FROM draws "
        "WHERE draw_date LIKE ?",
        (f"{year}%",),
    ).fetchone()
    n, earliest, latest = row
    # Rough expectation: 1/week before 2015, 2/week after
    weeks = 52
    expected = 52 if year < 2015 else 104
    if year == 2026:
        expected = 78  # Jan-Sep
    if year == 2015:
        expected = 70  # transition
    gap = expected - n
    marker = "  **" if gap > 10 else ""
    print(f"{year:>5}  {n:>5}  {expected:>9}  {gap:>+6}  {str(earliest):>12}  {str(latest):>12}{marker}")

print()
print("Rows starting 2023+ with powerball outside 1-10:")
rows = conn.execute(
    "SELECT draw_date, powerball FROM draws "
    "WHERE draw_date >= '2023-01-01' AND (powerball < 1 OR powerball > 10) "
    "ORDER BY draw_date LIMIT 20"
).fetchall()
for r in rows:
    print(f"  {r[0]}  pb={r[1]}")
print(f"  (total: {len(rows)})")