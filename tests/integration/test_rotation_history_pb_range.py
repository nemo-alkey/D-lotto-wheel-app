"""Regression: rotation_history must accept Powerball 11-14."""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3

import pytest

from config.settings import DB_PATH
from rotation_scheduler import init_rotation_db


def test_canonical_db_rotation_history_check_is_1_to_14() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='rotation_history'"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "rotation_history table is missing"
    assert "BETWEEN 1 AND 14" in row[0], (
        f"rotation_history still rejects PB 11-14: {row[0]}"
    )


def _assert_powerball_insert(db_path: Path, powerball: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO rotation_history (created_at, period, numbers, powerball) "
            "VALUES (?, ?, ?, ?)",
            ("2026-10-30T00:00:00", 1, "1,2,3,4,5,6", powerball),
        )
        conn.commit()
        stored = conn.execute(
            "SELECT powerball FROM rotation_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert stored is not None and stored[0] == powerball
    finally:
        conn.close()


@pytest.mark.parametrize("powerball", [11, 12, 13, 14])
def test_rotation_history_accepts_new_powerballs(
    powerball: int, tmp_path: Path
) -> None:
    """Both migrated and freshly initialized schemas accept the full new range."""
    copied_db = tmp_path / "rot.db"
    shutil.copy2(DB_PATH, copied_db)
    _assert_powerball_insert(copied_db, powerball)

    fresh_db = tmp_path / "fresh.db"
    init_rotation_db(str(fresh_db)).close()
    _assert_powerball_insert(fresh_db, powerball)
