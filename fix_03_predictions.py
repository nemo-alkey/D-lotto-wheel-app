"""predictions.py — sweep 9 hardcoded Powerball 1-10 sites."""
from __future__ import annotations
import ast, sys
from pathlib import Path

TARGET = Path("predictions.py")
src = TARGET.read_text(encoding="utf-8")

# Step 1: define the module-level constant once.
PRELUDE_OLD = "from __future__ import annotations"
PRELUDE_NEW = """from __future__ import annotations

from powerball_rules import powerball_max_for_date as _pb_max
POWERBALL_MAX = _pb_max(None)  # era-aware: 10 pre-2026-09-16, 14 after"""

# Step 2: each site replaces range(1, 11) / 10*alpha with the constant.
SITES = [
    (
        "(total_pb + 10 * alpha) for p in range(1, 11)",
        "(total_pb + POWERBALL_MAX * alpha) for p in range(1, POWERBALL_MAX + 1)",
        "line ~81: Laplace-smoothed pb_probs",
    ),
    (
        "top_pb = max(range(1, 11), key=lambda p: pb_scores[p - 1])",
        "top_pb = max(range(1, POWERBALL_MAX + 1), key=lambda p: pb_scores[p - 1])",
        "line ~146: top_pb from pb_scores",
    ),
    (
        "pb_probs = [pb_counts.get(p, 0) / total_pb for p in range(1, 11)]",
        "pb_probs = [pb_counts.get(p, 0) / total_pb for p in range(1, POWERBALL_MAX + 1)]",
        "line ~179: pb_probs list",
    ),
    (
        "top_pb = max(range(1, 11), key=lambda p: pb_probs[p - 1])",
        "top_pb = max(range(1, POWERBALL_MAX + 1), key=lambda p: pb_probs[p - 1])",
        "line ~198: top_pb from pb_probs",
    ),
    (
        "last_pb = {p: -1 for p in range(1, 11)}",
        "last_pb = {p: -1 for p in range(1, POWERBALL_MAX + 1)}",
        "line ~219: last_pb dict",
    ),
    (
        "gaps_pb = {p: n_draws - last_pb[p] - 1 for p in range(1, 11)}",
        "gaps_pb = {p: n_draws - last_pb[p] - 1 for p in range(1, POWERBALL_MAX + 1)}",
        "line ~233: gaps_pb dict",
    ),
    (
        "z_freq_pb = z_scores({p: -pb_count.get(p, 0) for p in range(1, 11)})",
        "z_freq_pb = z_scores({p: -pb_count.get(p, 0) for p in range(1, POWERBALL_MAX + 1)})",
        "line ~247: z_freq_pb",
    ),
    (
        "score_pb = {p: z_gap_pb[p] + z_freq_pb[p] for p in range(1, 11)}",
        "score_pb = {p: z_gap_pb[p] + z_freq_pb[p] for p in range(1, POWERBALL_MAX + 1)}",
        "line ~251: score_pb",
    ),
    (
        "pb_scores: dict[int, float] = {p: 0.0 for p in range(1, 11)}",
        "pb_scores: dict[int, float] = {p: 0.0 for p in range(1, POWERBALL_MAX + 1)}",
        "line ~397: pb_scores init",
    ),
]

# Apply prelude
if PRELUDE_OLD in src and "POWERBALL_MAX = _pb_max(None)" not in src:
    src = src.replace(PRELUDE_OLD, PRELUDE_NEW, 1)
    print("OK  : prelude — module constant POWERBALL_MAX added")
elif "POWERBALL_MAX = _pb_max(None)" in src:
    print("SKIP: prelude already present")
else:
    print("MISS: prelude anchor (from __future__ import annotations) not found")

applied = 0
for old, new, desc in SITES:
    if old in src:
        src = src.replace(old, new, 1)
        print(f"OK  : {desc}")
        applied += 1
    elif new in src:
        print(f"SKIP: {desc}")
    else:
        print(f"MISS: {desc} — check source line, may have drifted")

TARGET.write_text(src, encoding="utf-8")
try:
    ast.parse(src); print(f"\nSyntax check: OK ({applied}/9 site edits applied)")
except SyntaxError as e:
    print(f"\nSyntax FAILED at line {e.lineno}: {e.msg}"); sys.exit(1)