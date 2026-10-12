"""Preflight: confirm powerball_rules.powerball_max_for_date is importable."""
from __future__ import annotations

import sys

try:
    from powerball_rules import powerball_max_for_date
except ImportError as e:
    print(f"ABORT: powerball_rules missing or incomplete — {e}")
    sys.exit(1)

pre = powerball_max_for_date("2026-09-12")
post = powerball_max_for_date("2026-09-16")
none = powerball_max_for_date(None)
print(f"pre-change  (2026-09-12) -> {pre}  (expect 10)")
print(f"post-change (2026-09-16) -> {post} (expect 14)")
print(f"None (current rules)     -> {none} (expect 14)")

if (pre, post, none) != (10, 14, 14):
    print("\nABORT: helper returns unexpected values — fix powerball_rules first")
    sys.exit(2)

print("\nPreflight OK — safe to run the sweep.")