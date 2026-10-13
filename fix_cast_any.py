"""Replace the 'str | date' cast with cast to Any — no name resolution needed."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

P = Path("prize_calculator.py")
src = P.read_text(encoding="utf-8")

OLD = 'from typing import cast as _cast'
NEW = 'from typing import Any as _Any, cast as _cast'

# Two call sites, both use the same inline import pattern
if OLD in src:
    count = src.count(OLD)
    src = src.replace(OLD, NEW)
    print(f"OK  : updated {count} inline import(s) to bring in Any")

OLD_CAST = '_cast("str | date", effective)'
NEW_CAST = '_cast(_Any, effective)'

if OLD_CAST in src:
    count = src.count(OLD_CAST)
    src = src.replace(OLD_CAST, NEW_CAST)
    print(f"OK  : replaced {count} cast call(s) with cast to Any")
else:
    print("MISS: cast call not found — check the exact form")

try:
    ast.parse(src)
except SyntaxError as e:
    print(f"SYNTAX FAIL line {e.lineno}: {e.msg}")
    sys.exit(1)

P.write_text(src, encoding="utf-8")
print("\nDone. Now run: python -m mypy .")