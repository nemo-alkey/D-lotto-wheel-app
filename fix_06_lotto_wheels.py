"""lotto_wheels.py — line ~819 top3_pbs."""
from __future__ import annotations
import ast, sys
from pathlib import Path

TARGET = Path("lotto_wheels.py")
src = TARGET.read_text(encoding="utf-8")

OLD = "top3_pbs = list(range(1, 11))"
NEW = """from powerball_rules import powerball_max_for_date as _pb_max
    top3_pbs = list(range(1, _pb_max(None) + 1))"""

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    print("OK  : lotto_wheels.py top3_pbs")
elif "range(1, _pb_max(None) + 1)" in src:
    print("SKIP: lotto_wheels.py already era-aware")
else:
    print("MISS: lotto_wheels.py top3_pbs not found")

TARGET.write_text(src, encoding="utf-8")
try:
    ast.parse(src); print("\nSyntax check: OK")
except SyntaxError as e:
    print(f"\nSyntax FAILED at line {e.lineno}: {e.msg}"); sys.exit(1)