#!/usr/bin/env python3
"""
migrate.py — Alembic database migration CLI for NZ Lotto.

Commands:
    python migrate.py upgrade [rev]              # run pending migrations (default: head)
    python migrate.py downgrade [rev]            # rollback (default: -1, one migration)
    python migrate.py revision -m "description" [--autogenerate]
    python migrate.py current                    # show current schema version
    python migrate.py history                    # show migration history
    python migrate.py stamp [rev]                # mark DB as at rev without migrating
    python migrate.py check                      # warn if DB is behind latest migration

The database URL is resolved the same way as alembic/env.py:
settings.database_url -> DATABASE_URL env var -> sqlite:///lotto.db.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from alembic.config import Config

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent


def _alembic_config() -> Config:
    """Build an Alembic Config pointed at this project."""
    from alembic.config import Config

    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    return cfg


def _resolve_db_url() -> str:
    """Resolve the database URL (mirrors alembic/env.py)."""
    try:
        from settings import settings

        url = getattr(settings, "database_url", None)
        if url:
            return cast(str, url)
    except ImportError:
        pass
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    return f"sqlite:///{_ROOT / 'lotto.db'}"


def check_schema_version() -> tuple[str | None, str | None]:
    """Compare the database's schema version against the latest migration.

    Returns:
        (current, head) — current is None when the DB has never been
        stamped/migrated. Logs a warning when they differ; intended to be
        called at app startup.
    """
    from sqlalchemy import create_engine, text

    from alembic.script import ScriptDirectory

    cfg = _alembic_config()
    head = ScriptDirectory.from_config(cfg).get_current_head()

    engine = create_engine(_resolve_db_url())
    try:
        with engine.connect() as conn:
            try:
                row = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).fetchone()
            except Exception:
                row = None  # table missing — DB never migrated
        current = row[0] if row else None
    finally:
        engine.dispose()

    if current != head:
        logger.warning(
            "Database schema version (%s) does not match the latest "
            "migration (%s) — run 'python migrate.py upgrade'.",
            current or "unversioned",
            head,
        )
    return current, head


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_up = sub.add_parser("upgrade", help="Run pending migrations (default: head)")
    p_up.add_argument("revision", nargs="?", default="head")

    p_down = sub.add_parser("downgrade", help="Rollback migrations (default: -1)")
    p_down.add_argument("revision", nargs="?", default="-1")

    p_rev = sub.add_parser("revision", help="Create a new migration script")
    p_rev.add_argument("-m", "--message", required=True)
    p_rev.add_argument("--autogenerate", action="store_true")

    sub.add_parser("current", help="Show current schema version")
    sub.add_parser("history", help="Show migration history")

    p_stamp = sub.add_parser(
        "stamp", help="Stamp DB as at a revision without migrating"
    )
    p_stamp.add_argument("revision", nargs="?", default="head")

    sub.add_parser("check", help="Warn if the DB schema is behind the latest migration")

    args = parser.parse_args()

    from alembic import command

    cfg = _alembic_config()

    if args.command == "upgrade":
        command.upgrade(cfg, args.revision)
    elif args.command == "downgrade":
        command.downgrade(cfg, args.revision)
    elif args.command == "revision":
        command.revision(cfg, message=args.message, autogenerate=args.autogenerate)
    elif args.command == "current":
        command.current(cfg)
    elif args.command == "history":
        command.history(cfg)
    elif args.command == "stamp":
        command.stamp(cfg, args.revision)
    elif args.command == "check":
        current, head = check_schema_version()
        if current == head:
            print(f"Schema is up to date (revision {head}).")
        else:
            print(
                f"Schema mismatch: DB is at {current or 'unversioned'}, "
                f"latest migration is {head}. Run: python migrate.py upgrade"
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
