"""api.py — lines ~614, ~1200 Pydantic PB validators."""
from __future__ import annotations
import ast, sys
from pathlib import Path

TARGET = Path("api.py")
src = TARGET.read_text(encoding="utf-8")

SITES = [
    (
        'powerball: int = Field(ge=1, le=10, description="Powerball (1-10)")',
        'powerball: int = Field(ge=1, le=14, description="Powerball (1-14 post-2026-09-16)")',
        "line ~614: Pydantic validator (description variant)",
    ),
    (
        "powerball: int = Field(ge=1, le=10)",
        "powerball: int = Field(ge=1, le=14)",
        "line ~1200: Pydantic validator (bare)",
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
    ast.parse(src); print(f"\nSyntax check: OK ({applied}/2 applied)")
except SyntaxError as e:
    print(f"\nSyntax FAILED at line {e.lineno}: {e.msg}"); sys.exit(1)