"""predict_ml.py — line ~201 pb_rows range(1, 11)."""
from __future__ import annotations
import ast, sys
from pathlib import Path

TARGET = Path("predict_ml.py")
src = TARGET.read_text(encoding="utf-8")

OLD = "pb_rows = build_features_for_draw(draws, next_idx, range(1, 11))"
NEW = """from powerball_rules import powerball_max_for_date as _pb_max
    pb_rows = build_features_for_draw(draws, next_idx, range(1, _pb_max(None) + 1))"""

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    print("OK  : predict_ml.py pb_rows range")
elif "range(1, _pb_max(None) + 1)" in src:
    print("SKIP: predict_ml.py already era-aware")
else:
    print("MISS: predict_ml.py pb_rows not found — check surrounding indent")

TARGET.write_text(src, encoding="utf-8")
try:
    ast.parse(src); print("\nSyntax check: OK")
except SyntaxError as e:
    print(f"\nSyntax FAILED at line {e.lineno}: {e.msg}"); sys.exit(1)