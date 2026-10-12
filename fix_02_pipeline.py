"""pipeline.py — replace NUM_POWERBALL = 10 with era-aware value."""
from __future__ import annotations
import ast, sys
from pathlib import Path

TARGET = Path("pipeline.py")
src = TARGET.read_text(encoding="utf-8")

OLD = "NUM_POWERBALL = 10  # Number of possible Powerball values"
NEW = """from powerball_rules import powerball_max_for_date as _pb_max
NUM_POWERBALL = _pb_max(None)  # era-aware: 10 pre-2026-09-16, 14 after"""

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    print("OK  : pipeline.py NUM_POWERBALL")
elif "NUM_POWERBALL = _pb_max(None)" in src:
    print("SKIP: pipeline.py already era-aware")
else:
    print("MISS: pipeline.py NUM_POWERBALL = 10 not found")

TARGET.write_text(src, encoding="utf-8")
try:
    ast.parse(src); print("\nSyntax check: OK")
except SyntaxError as e:
    print(f"\nSyntax FAILED at line {e.lineno}: {e.msg}"); sys.exit(1)