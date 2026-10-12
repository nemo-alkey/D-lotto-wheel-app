"""Replace _pb_max(None) with POWERBALL_MAX_NEW across all swept files.

powerball_max_for_date rejects None (raises ValueError). The sweep's
assumption that None == "current rules" was wrong. Fix: import the
constant POWERBALL_MAX_NEW (= 14) directly from powerball_rules.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

FILES = [
    "main.py",
    "pipeline.py",
    "predictions.py",
    "predict_ml.py",
    "ensemble.py",
    "lotto_wheels.py",
    "ticket_wizard.py",
    "api.py",
    "dashboard.py",
]

OLD_IMPORT = "from powerball_rules import powerball_max_for_date as _pb_max"
NEW_IMPORT = "from powerball_rules import POWERBALL_MAX_NEW"
OLD_CALL = "_pb_max(None)"
NEW_CALL = "POWERBALL_MAX_NEW"


def fix_file(name: str) -> bool:
    p = Path(name)
    if not p.exists():
        print(f"SKIP: {name} not found")
        return True
    src = p.read_text(encoding="utf-8")
    if OLD_IMPORT not in src and OLD_CALL not in src:
        print(f"SKIP: {name} — already clean")
        return True

    src = src.replace(OLD_IMPORT, NEW_IMPORT)
    src = src.replace(OLD_CALL, NEW_CALL)

    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"FAIL: {name} line {e.lineno}: {e.msg}")
        return False

    p.write_text(src, encoding="utf-8")
    print(f"OK  : {name}")
    return True


def main() -> int:
    failed = sum(0 if fix_file(n) else 1 for n in FILES)
    if failed:
        print(f"\n{failed} file(s) failed")
        return 1
    print("\nDone. Verify powerball_rules exports POWERBALL_MAX_NEW:")
    print("  python -c \"from powerball_rules import POWERBALL_MAX_NEW; print(POWERBALL_MAX_NEW)\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())