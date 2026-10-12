#!/usr/bin/env python3
"""Migrate the draws table: add rule_era column and backfill it.

Values: 'pre_2026_09_16' for draw_date < 2026-09-16, 'post_2026_09_16'
otherwise. Idempotent — safe to re-run; existing non-empty values are kept.

Usage:
    python scripts/migrate_rule_era.py              # migrate data/lotto.db
    python scripts/migrate_rule_era.py --db PATH    # another database
    python scripts/migrate_rule_era.py --dry-run    # report only, no writes
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from era_features import RULE_ERA_POST, RULE_ERA_PRE, ensure_rule_era_column

DB_PATH = Path("data/lotto.db")


def migrate(db_path: Path = DB_PATH, dry_run: bool = False) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path), timeout=10)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(draws)")}
    has_column = "rule_era" in cols

    pre = conn.execute(
        "SELECT COUNT(*) FROM draws WHERE draw_date < '2026-09-16'"
    ).fetchone()[0]
    post = conn.execute(
        "SELECT COUNT(*) FROM draws WHERE draw_date >= '2026-09-16'"
    ).fetchone()[0]
    unfilled = 0
    if has_column:
        unfilled = conn.execute(
            "SELECT COUNT(*) FROM draws WHERE rule_era IS NULL OR rule_era = ''"
        ).fetchone()[0]

    print(f"draws: {pre} pre-change, {post} post-change, {unfilled} rows needing rule_era")
    if dry_run:
        print(f"[dry-run] would {'add column and ' if not has_column else ''}backfill {unfilled} rows")
        conn.close()
        return {"pre": pre, "post": post, "backfilled": 0, "column_created": 0}

    created = ensure_rule_era_column(conn)
    conn.close()
    print(f"migrated: column {'created' if created else 'already existed'}, "
          f"backfilled {unfilled} rows")
    return {"pre": pre, "post": post, "backfilled": unfilled, "column_created": int(created)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(db_path=args.db, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
