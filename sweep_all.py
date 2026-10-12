"""One-shot sweep: replace 21 hardcoded Powerball 1-10 sites with era-aware helper.

v2 — all imports go at module scope (v1 broke predict_ml.py by inserting
an import inside a function body). Idempotent. Run: python sweep_all.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# Prelude anchor + block. Every file we touch gets this immediately after
# the `from __future__ import annotations` line.
ANCHOR = "from __future__ import annotations"
PRELUDE_BLOCK = """from __future__ import annotations

from powerball_rules import powerball_max_for_date as _pb_max
POWERBALL_MAX = _pb_max(None)  # era-aware: 10 pre-2026-09-16, 14 after"""

# Files that don't currently have the __future__ anchor need special handling.
FILES: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("main.py", [
        ("NUM_POWERBALL = 10",
         "NUM_POWERBALL = POWERBALL_MAX",
         "NUM_POWERBALL constant"),
    ]),
    ("pipeline.py", [
        ("NUM_POWERBALL = 10  # Number of possible Powerball values",
         "NUM_POWERBALL = POWERBALL_MAX  # era-aware",
         "NUM_POWERBALL constant"),
    ]),
    ("predictions.py", [
        ("(total_pb + 10 * alpha) for p in range(1, 11)",
         "(total_pb + POWERBALL_MAX * alpha) for p in range(1, POWERBALL_MAX + 1)",
         "Laplace-smoothed pb_probs"),
        ("top_pb = max(range(1, 11), key=lambda p: pb_scores[p - 1])",
         "top_pb = max(range(1, POWERBALL_MAX + 1), key=lambda p: pb_scores[p - 1])",
         "top_pb from pb_scores"),
        ("pb_probs = [pb_counts.get(p, 0) / total_pb for p in range(1, 11)]",
         "pb_probs = [pb_counts.get(p, 0) / total_pb for p in range(1, POWERBALL_MAX + 1)]",
         "pb_probs list"),
        ("top_pb = max(range(1, 11), key=lambda p: pb_probs[p - 1])",
         "top_pb = max(range(1, POWERBALL_MAX + 1), key=lambda p: pb_probs[p - 1])",
         "top_pb from pb_probs"),
        ("last_pb = {p: -1 for p in range(1, 11)}",
         "last_pb = {p: -1 for p in range(1, POWERBALL_MAX + 1)}",
         "last_pb dict"),
        ("gaps_pb = {p: n_draws - last_pb[p] - 1 for p in range(1, 11)}",
         "gaps_pb = {p: n_draws - last_pb[p] - 1 for p in range(1, POWERBALL_MAX + 1)}",
         "gaps_pb dict"),
        ("z_freq_pb = z_scores({p: -pb_count.get(p, 0) for p in range(1, 11)})",
         "z_freq_pb = z_scores({p: -pb_count.get(p, 0) for p in range(1, POWERBALL_MAX + 1)})",
         "z_freq_pb"),
        ("score_pb = {p: z_gap_pb[p] + z_freq_pb[p] for p in range(1, 11)}",
         "score_pb = {p: z_gap_pb[p] + z_freq_pb[p] for p in range(1, POWERBALL_MAX + 1)}",
         "score_pb"),
        ("pb_scores: dict[int, float] = {p: 0.0 for p in range(1, 11)}",
         "pb_scores: dict[int, float] = {p: 0.0 for p in range(1, POWERBALL_MAX + 1)}",
         "pb_scores init"),
    ]),
    ("predict_ml.py", [
        ("pb_rows = build_features_for_draw(draws, next_idx, range(1, 11))",
         "pb_rows = build_features_for_draw(draws, next_idx, range(1, POWERBALL_MAX + 1))",
         "pb_rows range"),
    ]),
    ("ensemble.py", [
        ("pb_probs = {p: pb_counts.get(p, 0) / total_pb for p in range(1, 11)}",
         "pb_probs = {p: pb_counts.get(p, 0) / total_pb for p in range(1, POWERBALL_MAX + 1)}",
         "pb_probs comprehension"),
    ]),
    ("lotto_wheels.py", [
        ("top3_pbs = list(range(1, 11))",
         "top3_pbs = list(range(1, POWERBALL_MAX + 1))",
         "top3_pbs list"),
    ]),
    ("ticket_wizard.py", [
        ('pb = st.selectbox("Powerball", list(range(1, 11)), key="wiz_pb_manual")',
         'pb = st.selectbox("Powerball", list(range(1, POWERBALL_MAX + 1)), key="wiz_pb_manual")',
         "selectbox PB range"),
    ]),
    ("api.py", [
        ('powerball: int = Field(ge=1, le=10, description="Powerball (1-10)")',
         'powerball: int = Field(ge=1, le=14, description="Powerball (1-14 post-2026-09-16)")',
         "Pydantic validator (described)"),
        ("powerball: int = Field(ge=1, le=10)",
         "powerball: int = Field(ge=1, le=14)",
         "Pydantic validator (bare)"),
    ]),
    ("dashboard.py", [
        ("pb_freq = np.array([pb_counter.get(n, 0) for n in range(1, 11)])",
         "pb_freq = np.array([pb_counter.get(n, 0) for n in range(1, POWERBALL_MAX + 1)])",
         "pb_freq array"),
        ("ax2.bar(np.arange(1, 11), pb_freq",
         "ax2.bar(np.arange(1, POWERBALL_MAX + 1), pb_freq",
         "ax2.bar x-axis"),
        ("ax2.set_xticks(range(1, 11))",
         "ax2.set_xticks(range(1, POWERBALL_MAX + 1))",
         "ax2 ticks"),
        ('"Powerball": range(1, 11),',
         '"Powerball": range(1, POWERBALL_MAX + 1),',
         "Powerball range literal"),
    ]),
]


def inject_prelude(src: str, name: str) -> tuple[str, bool]:
    """Insert POWERBALL_MAX at module scope. Returns (src, changed)."""
    if "POWERBALL_MAX = _pb_max(None)" in src:
        print("  SKIP: prelude already present")
        return src, False
    if ANCHOR not in src:
        print(f"  WARN: {name} has no '{ANCHOR}' — cannot inject prelude safely")
        print(f"        Add these two lines manually near the top of {name}:")
        print(f"        from powerball_rules import powerball_max_for_date as _pb_max")
        print(f"        POWERBALL_MAX = _pb_max(None)")
        return src, False
    src = src.replace(ANCHOR, PRELUDE_BLOCK, 1)
    print("  OK  : prelude injected (POWERBALL_MAX at module scope)")
    return src, True


def apply_file(name: str, edits) -> tuple[int, int, int]:
    path = Path(name)
    if not path.exists():
        print(f"\n=== {name} ===  NOT FOUND")
        return (0, 0, len(edits))

    src = path.read_text(encoding="utf-8")
    print(f"\n=== {name} ===")
    src, _ = inject_prelude(src, name)

    applied = skipped = missed = 0
    for old, new, desc in edits:
        if old in src:
            src = src.replace(old, new, 1)
            print(f"  OK  : {desc}")
            applied += 1
        elif new in src:
            print(f"  SKIP: {desc}")
            skipped += 1
        else:
            print(f"  MISS: {desc}")
            missed += 1

    path.write_text(src, encoding="utf-8")
    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"  SYNTAX FAIL at line {e.lineno}: {e.msg}")
        if e.text:
            print(f"  >>> {e.text.rstrip()}")
        raise SystemExit(2)
    return (applied, skipped, missed)


def main() -> int:
    total_applied = total_skipped = total_missed = 0
    for name, edits in FILES:
        a, s, m = apply_file(name, edits)
        total_applied += a
        total_skipped += s
        total_missed += m

    print("\n" + "=" * 60)
    print(f"Applied: {total_applied}   Skipped: {total_skipped}   Missed: {total_missed}")

    if total_missed:
        print("\nMISS = source text didn't match. Paste the MISS lines and the")
        print("matching source excerpt; the anchors will be adjusted.")
        return 1

    print("\nAll sites swept. Now run:")
    print("  python -m pytest tests/ -q --continue-on-collection-errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())