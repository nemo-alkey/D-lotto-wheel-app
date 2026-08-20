"""Integration tests for the database layer.

Covers update_draws.py insert/exists helpers against an in-memory SQLite
schema, the real lotto.db schema (read-only), pos_neg_tracker persistence
against a temp file DB, and the SQLAlchemy fetch helpers in database.py.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import cast

import pytest

pytestmark = pytest.mark.integration

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
LOTTO_DB = os.path.join(PROJECT_ROOT, "lotto.db")

DRAW = {
    "draw_date": "2024-01-01",
    "numbers": [3, 7, 12, 14, 18, 22],
    "bonus": 9,
    "powerball": 4,
}


# ---------------------------------------------------------------------------
# update_draws.insert_draw / draw_exists (sqlite3 connection API)
# ---------------------------------------------------------------------------


class TestInsertDraw:
    def test_insert_draw_round_trip(self, db_connection: sqlite3.Connection) -> None:
        from update_draws import insert_draw

        assert insert_draw(db_connection, DRAW) is True

        row = db_connection.execute(
            "SELECT draw_date, numbers, bonus, powerball FROM draws"
        ).fetchone()
        assert row is not None
        assert row[0] == "2024-01-01"
        assert [int(n) for n in row[1].split(",")] == [3, 7, 12, 14, 18, 22]
        assert row[2] == 9
        assert row[3] == 4

    def test_draw_exists_and_duplicate_rejected(
        self, db_connection: sqlite3.Connection
    ) -> None:
        from update_draws import draw_exists, insert_draw

        assert draw_exists(db_connection, cast(str, DRAW["draw_date"])) is False
        assert insert_draw(db_connection, DRAW) is True

        assert draw_exists(db_connection, cast(str, DRAW["draw_date"])) is True
        # Same date again -> UNIQUE constraint -> insert_draw returns False
        assert insert_draw(db_connection, DRAW) is False

        # Still exactly one row
        count = db_connection.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# Real lotto.db schema (read-only)
# ---------------------------------------------------------------------------


class TestRealSchema:
    EXPECTED_COLUMNS = ["draw_id", "draw_date", "numbers", "bonus", "powerball"]

    def test_draws_table_and_columns(self) -> None:
        assert os.path.exists(LOTTO_DB), "lotto.db must exist for this test"
        # Open read-only via URI so the test can never mutate the real DB
        conn = sqlite3.connect(f"file:{LOTTO_DB}?mode=ro", uri=True)
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "draws" in tables

            cols = [r[1] for r in conn.execute("PRAGMA table_info(draws)")]
            assert cols == self.EXPECTED_COLUMNS
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# pos_neg_tracker.save_classification (temp file DB)
# ---------------------------------------------------------------------------


class TestPosNegPersistence:
    def test_save_classification_round_trip(self, tmp_path: Path) -> None:
        from pos_neg_tracker import save_classification

        db_path = str(tmp_path / "test_pos_neg.db")
        classification = {
            "positive": [1, 2, 3, 4, 5],
            "negative": [36, 37, 38, 39, 40],
            "neutral": [10, 11, 12],
        }

        save_classification(42, classification, db_path, shift_detected=2)

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT draw_id, classification_json, shift_detected "
                "FROM pos_neg_history"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        assert row[0] == 42
        assert json.loads(row[1]) == classification
        assert row[2] == 2


# ---------------------------------------------------------------------------
# database.py SQLAlchemy fetch helpers (read-only against lotto.db)
# ---------------------------------------------------------------------------


class TestFetchDraws:
    REQUIRED_KEYS = {"draw_date", "numbers", "bonus", "powerball"}

    def _check_rows(self, rows: list[dict[str, object]]) -> None:
        assert isinstance(rows, list)
        assert len(rows) >= 1, "lotto.db should contain at least one draw"
        for row in rows:
            assert isinstance(row, dict)
            assert set(row.keys()) >= self.REQUIRED_KEYS
            assert isinstance(row["numbers"], list)
            assert all(isinstance(n, int) for n in row["numbers"])

    def test_fetch_all_draws(self) -> None:
        from database import fetch_all_draws

        self._check_rows(fetch_all_draws())

    def test_fetch_recent_draws(self) -> None:
        from database import fetch_recent_draws

        rows = fetch_recent_draws(limit=5)
        assert isinstance(rows, list)
        assert len(rows) <= 5
        assert len(rows) >= 1
        for row in rows:
            assert set(row.keys()) >= self.REQUIRED_KEYS
