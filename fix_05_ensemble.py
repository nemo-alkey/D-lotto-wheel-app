"""ensemble.py — line ~227 pb_probs comprehension."""
from __future__ import annotations
import ast, sys
from pathlib import Path

TARGET = Path("ensemble.py")
src = TARGET.read_text(encoding="utf-8")

OLD = "pb_probs = {p: pb_counts.get(p, 0) / total_pb for p in range(1, 11)}"
NEW = """from powerball_rules import powerball_max_for_date as _pb_max
    pb_probs = {p: pb_counts.get(p, 0) / total_pb for p in range(1, _pb_max(None) + 1)}"""

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    print("OK  : ensemble.py pb_probs range")
elif "range(1, _pb_max(None) + 1)" in src:
    print("SKIP: ensemble.py already era-aware")
else:
    print("MISS: ensemble.py pb_probs not found")

TARGET.write_text(src, encoding="utf-8")
try:
    ast.parse(src); print("\nSyntax check: OK")
except SyntaxError as e:
    print(f"\nSyntax FAILED at line {e.lineno}: {e.msg}"); sys.exit(1)