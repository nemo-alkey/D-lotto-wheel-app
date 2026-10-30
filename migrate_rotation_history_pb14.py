"""One-shot migration: rotation_history CHECK powerball 1-10 -> 1-14."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

from config.settings import DB_PATH


def main() -> None:
    db_path = Path(DB_PATH)
    backup = db_path.with_name(
        f"{db_path.stem}.pre_pb14_{datetime.now():%Y%m%d_%H%M%S}{db_path.suffix}"
    )
    shutil.copy2(db_path, backup)
    print(f"Backup: {backup}")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        old_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='rotation_history'"
        ).fetchone()
        if old_sql_row is None:
            print("rotation_history does not exist; nothing to migrate.")
            return

        old_sql = old_sql_row[0]
        if "BETWEEN 1 AND 14" in old_sql:
            print("rotation_history already accepts Powerball 1-14; no rebuild needed.")
        else:
            try:
                conn.execute("BEGIN")
                conn.execute(
                    """
                    CREATE TABLE rotation_history_new (
                        id INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        period INTEGER NOT NULL,
                        numbers TEXT NOT NULL,
                        powerball INTEGER NOT NULL,
                        PRIMARY KEY (id),
                        CHECK (period >= 1),
                        CHECK (powerball BETWEEN 1 AND 14)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO rotation_history_new (id, created_at, period, numbers, powerball)
                    SELECT id, created_at, period, numbers, powerball FROM rotation_history
                    """
                )
                old_count = conn.execute("SELECT COUNT(*) FROM rotation_history").fetchone()[0]
                new_count = conn.execute("SELECT COUNT(*) FROM rotation_history_new").fetchone()[0]
                if old_count != new_count:
                    raise RuntimeError(f"Row count mismatch: {old_count} -> {new_count}")

                conn.execute("DROP TABLE rotation_history")
                conn.execute("ALTER TABLE rotation_history_new RENAME TO rotation_history")
                conn.commit()
                print(f"Migrated {new_count} rows.")
            except Exception as exc:
                conn.rollback()
                print(f"MIGRATION FAILED, rolled back: {exc}")
                raise

        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='rotation_history'"
        ).fetchone()[0]
        assert "BETWEEN 1 AND 14" in sql, "Constraint not updated"
        conn.execute(
            "INSERT INTO rotation_history (created_at, period, numbers, powerball) "
            "VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), 1, "1,2,3,4,5,6", 14),
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("DELETE FROM rotation_history WHERE id = ?", (row_id,))
        conn.commit()
        print("PB 14 insert/delete OK.")
        print("New schema:")
        print(sql)
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()


if __name__ == "__main__":
    main()
