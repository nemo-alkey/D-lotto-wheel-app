"""Insert the POWERBALL_MAX prelude at module scope in any file that
references it without defining it. Handles files that lack the
'from __future__ import annotations' anchor.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

PRELUDE = (
    "from powerball_rules import powerball_max_for_date as _pb_max\n"
    "POWERBALL_MAX = _pb_max(None)  # era-aware: 10 pre-2026-09-16, 14 after\n\n"
)

TARGETS = ["lotto_wheels.py", "dashboard.py"]


def needs_prelude(src: str) -> bool:
    return "POWERBALL_MAX" in src and "POWERBALL_MAX = _pb_max(None)" not in src


def insert_at_module_scope(src: str) -> str | None:
    """Insert the prelude before the first top-level import line."""
    lines = src.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith(("import ", "from ")):
            lines.insert(i, PRELUDE)
            return "".join(lines)
    # No top-level import found — insert after the module docstring instead
    if lines and (lines[0].lstrip().startswith(('"""', "'''"))):
        quote = lines[0].lstrip()[:3]
        # Find closing quote on a later line
        for j in range(1, len(lines)):
            if quote in lines[j]:
                lines.insert(j + 1, "\n" + PRELUDE)
                return "".join(lines)
    return None


def main() -> int:
    failed = 0
    for name in TARGETS:
        path = Path(name)
        if not path.exists():
            print(f"SKIP: {name} not found")
            continue
        src = path.read_text(encoding="utf-8")
        if not needs_prelude(src):
            print(f"SKIP: {name} prelude already present or not needed")
            continue
        new_src = insert_at_module_scope(src)
        if new_src is None:
            print(f"FAIL: {name} — no safe insertion point found")
            failed += 1
            continue
        try:
            ast.parse(new_src)
        except SyntaxError as e:
            print(f"FAIL: {name} line {e.lineno}: {e.msg}")
            failed += 1
            continue
        path.write_text(new_src, encoding="utf-8")
        print(f"OK  : {name} prelude inserted")

    if failed:
        print(f"\n{failed} file(s) failed — paste the FAIL lines and check manually")
        return 1
    print("\nPreludes inserted. Now run:")
    print("  python -m pytest tests/ -q --continue-on-collection-errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())