"""dashboard.py — lines ~3968, 4031, 4035, 4068 PB charts."""
from powerball_rules import powerball_max_for_date as _pb_max
POWERBALL_MAX = _pb_max(None)
from __future__ import annotations
import ast, sys
from pathlib import Path

TARGET = Path("dashboard.py")
src = TARGET.read_text(encoding="utf-8")

SITES = [
    (
        "pb_freq = np.array([pb_counter.get(n, 0) for n in range(1, 11)])",
        "pb_freq = np.array([pb_counter.get(n, 0) for n in range(1, POWERBALL_MAX + 1)])",
        "line ~3968: pb_freq array",
    ),
    (
        "ax2.bar(np.arange(1, 11), pb_freq",
        "ax2.bar(np.arange(1, POWERBALL_MAX + 1), pb_freq",
        "line ~4031: ax2.bar x-axis",
    ),
    (
        "ax2.set_xticks(range(1, 11))",
        "ax2.set_xticks(range(1, POWERBALL_MAX + 1))",
        "line ~4035: ax2 ticks",
    ),
    (
        '"Powerball": range(1, 11),',
        '"Powerball": range(1, POWERBALL_MAX + 1),',
        "line ~4068: Powerball range literal",
    ),
]

applied = 0
for old, new, desc in SITES:
    if old in src:
        src = src.replace(old, new, 1)
        print(f"OK  : {desc}")
        applied += 1
    elif new in src:
        print(f"SKIP: {desc}")
    else:
        print(f"MISS: {desc}")

TARGET.write_text(src, encoding="utf-8")
try:
    ast.parse(src); print(f"\nSyntax check: OK ({applied}/4 applied)")
except SyntaxError as e:
    print(f"\nSyntax FAILED at line {e.lineno}: {e.msg}"); sys.exit(1)