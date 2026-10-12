"""Normalize main.py and pipeline.py to the POWERBALL_MAX form."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

OLD_MAIN = """from powerball_rules import powerball_max_for_date as _pb_max
NUM_POWERBALL = _pb_max(None)"""

NEW_MAIN = """from powerball_rules import powerball_max_for_date as _pb_max
POWERBALL_MAX = _pb_max(None)  # era-aware: 10 pre-2026-09-16, 14 after
NUM_POWERBALL = POWERBALL_MAX"""

OLD_PIPE = """from powerball_rules import powerball_max_for_date as _pb_max
NUM_POWERBALL = _pb_max(None)  # era-aware"""

NEW_PIPE = """from powerball_rules import powerball_max_for_date as _pb_max
POWERBALL_MAX = _pb_max(None)  # era-aware: 10 pre-2026-09-16, 14 after
NUM_POWERBALL = POWERBALL_MAX"""

for name, old, new in [("main.py", OLD_MAIN, NEW_MAIN), ("pipeline.py", OLD_PIPE, NEW_PIPE)]:
    p = Path(name)
    src = p.read_text(encoding="utf-8")
    if old in src:
        p.write_text(src.replace(old, new, 1), encoding="utf-8")
        try:
            ast.parse(p.read_text(encoding="utf-8"))
            print(f"OK  : {name} normalized")
        except SyntaxError as e:
            print(f"FAIL: {name} line {e.lineno}: {e.msg}")
            sys.exit(1)
    elif "NUM_POWERBALL = POWERBALL_MAX" in src:
        print(f"SKIP: {name} already normalized")
    else:
        print(f"MISS: {name} — anchor not found")