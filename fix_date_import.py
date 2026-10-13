"""Add 'from datetime import date' to prize_calculator.py so the cast string resolves."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

P = Path("prize_calculator.py")
src = P.read_text(encoding="utf-8")

if "from datetime import date" in src:
    print("SKIP: date already imported")
    sys.exit(0)

# Insert right after the module docstring (before the first import)
lines = src.splitlines(keepends=True)
insert_at = 0
in_docstring = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if not in_docstring and i == 0 and stripped.startswith(('"""', "'''")):
        quote = stripped[:3]
        if stripped.count(quote) >= 2:
            insert_at = i + 1
            break
        in_docstring = True
        continue
    if in_docstring:
        if '"""' in line or "'''" in line:
            insert_at = i + 1
            break
        continue
    # First non-empty, non-comment line
    if stripped and not stripped.startswith("#"):
        insert_at = i
        break

lines.insert(insert_at, "from datetime import date\n")

src = "".join(lines)

try:
    ast.parse(src)
except SyntaxError as e:
    print(f"SYNTAX FAIL line {e.lineno}: {e.msg}")
    sys.exit(1)

P.write_text(src, encoding="utf-8")
print("OK  : added 'from datetime import date'")