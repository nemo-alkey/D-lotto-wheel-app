"""Regression: rotation_history must accept Powerball 11-14."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

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
    assert "BETWEEN 1 AND 14" in row[0], f"rotation_history still rejects PB 11-14: {row[0]}"


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
def test_rotation_history_accepts_new_powerballs(powerball: int, tmp_path: Path) -> None:
    """Both migrated and freshly initialized schemas accept the full new range."""
    copied_db = tmp_path / "rot.db"
    shutil.copy2(DB_PATH, copied_db)
    _assert_powerball_insert(copied_db, powerball)

    fresh_db = tmp_path / "fresh.db"
    init_rotation_db(str(fresh_db)).close()
    _assert_powerball_insert(fresh_db, powerball)


def test_rotation_db_constant_is_canonical() -> None:
    import rotation_scheduler

    assert Path(rotation_scheduler.ROTATION_DB) == Path(DB_PATH), (
        f"ROTATION_DB={rotation_scheduler.ROTATION_DB!r} is not the canonical "
        f"DB_PATH={DB_PATH!r}; scheduler output would be CWD-relative."
    )


def test_cli_does_not_create_cwd_rotation_db(tmp_path: Path) -> None:
    """Regression for P0.5: the CLI must not write a CWD-relative database."""
    import subprocess
    import sys

    work = tmp_path / "cwdtest"
    work.mkdir()
    script = Path(__file__).resolve().parents[2] / "rotation_scheduler.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stray = work / "rotation_scheduler.db"
    assert not stray.exists(), f"CLI created stray CWD database: {stray}"
