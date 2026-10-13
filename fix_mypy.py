"""Fix the two prize_calculator.py type errors + one import in deep_learning.

The remaining 11 errors are pre-existing in files unrelated to Powerball 2026
and can be scoped/excluded in mypy.ini separately.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Fix 1 & 2: prize_calculator.py — cast effective to the expected union
# ---------------------------------------------------------------------------
PC = Path("prize_calculator.py")
pc = PC.read_text(encoding="utf-8")

OLD1 = '''    prizes = dict(FALLBACK_PB)
    effective = draw_date if draw_date is not None else POWERBALL_CHANGE_DATE
    prizes.update(pb_fixed_prizes(effective))
    return prizes'''

NEW1 = '''    from typing import cast as _cast

    prizes = dict(FALLBACK_PB)
    effective = draw_date if draw_date is not None else POWERBALL_CHANGE_DATE
    prizes.update(pb_fixed_prizes(_cast("str | date", effective)))
    return prizes'''

OLD2 = '''    effective = draw_date if draw_date is not None else POWERBALL_CHANGE_DATE
    return pb_fixed_prizes(effective)'''

NEW2 = '''    from typing import cast as _cast

    effective = draw_date if draw_date is not None else POWERBALL_CHANGE_DATE
    return pb_fixed_prizes(_cast("str | date", effective))'''

if OLD1 in pc:
    pc = pc.replace(OLD1, NEW1, 1)
    print("OK  : prize_calculator.py fix 1 (_fallback_pb_prizes)")
elif "_cast(\"str | date\"" in pc:
    print("SKIP: prize_calculator.py fix 1 already applied")
else:
    print("MISS: prize_calculator.py fix 1 pattern not found")

if OLD2 in pc:
    pc = pc.replace(OLD2, NEW2, 1)
    print("OK  : prize_calculator.py fix 2 (second _pb_fixed_prizes helper)")
elif '_cast("str | date", effective)' in pc:
    print("SKIP: prize_calculator.py fix 2 already applied")
else:
    print("MISS: prize_calculator.py fix 2 pattern not found")

try:
    ast.parse(pc)
except SyntaxError as e:
    print(f"SYNTAX FAIL in prize_calculator.py line {e.lineno}: {e.msg}")
    sys.exit(1)
PC.write_text(pc, encoding="utf-8")

# ---------------------------------------------------------------------------
# Fix 3: steps/deep_learning.py — add Any to the typing import
# ---------------------------------------------------------------------------
DL = Path("steps/deep_learning.py")
dl = DL.read_text(encoding="utf-8")

if "from typing import cast" in dl and "from typing import Any" not in dl:
    dl = dl.replace(
        "from typing import cast",
        "from typing import Any, cast",
        1,
    )
    print("OK  : steps/deep_learning.py — added Any to typing import")
elif "from typing import Any" in dl:
    print("SKIP: steps/deep_learning.py already imports Any")
else:
    print("MISS: steps/deep_learning.py typing import not found")

try:
    ast.parse(dl)
except SyntaxError as e:
    print(f"SYNTAX FAIL in deep_learning.py line {e.lineno}: {e.msg}")
    sys.exit(2)
DL.write_text(dl, encoding="utf-8")

print("\nDone. Now update mypy.ini to exclude the remaining one-off scripts,")
print("then re-run: python -m mypy .")