"""Tests for scripts/repair_powerball_zero.py and scripts/backfill_draws.py.

All tests run against temporary SQLite databases with injected fetchers —
no network access, no touching the real data/lotto.db.
"""

from __future__ import annotations

import sqlite3

import pytest

from scripts.backfill_draws import backfill
from scripts.repair_powerball_zero import repair

SCHEMA = """
CREATE TABLE draws (
    draw_id    INTEGER PRIMARY KEY,
    draw_number INTEGER,
    draw_date  TEXT NOT NULL UNIQUE,
    numbers    TEXT NOT NULL,
    bonus      INTEGER,
    powerball  INTEGER,
    rule_era   TEXT
)
"""


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "lotto.db"
    conn = sqlite3.connect(p)
    conn.execute(SCHEMA)
    conn.commit()
    conn.close()
    return p


def _seed(db_path, rows):
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO draws (draw_number, draw_date, numbers, bonus, powerball) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _get(db_path, draw_number):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT powerball FROM draws WHERE draw_number = ?", (draw_number,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def _duplicates(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT draw_date, COUNT(*) c FROM draws GROUP BY draw_date HAVING c > 1"
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# repair_powerball_zero
# ---------------------------------------------------------------------------


class TestRepair:
    def test_zero_powerball_is_repaired(self, db_path, tmp_path):
        _seed(db_path, [(2613, "2026-08-19", "13,16,19,20,25,37", 12, 0)])
        log = tmp_path / "repair.log"
        counts = repair(
            db_path=db_path, log_path=log,
            fetcher=lambda n, d, nums, b: (10, "fake"),
        )
        assert _get(db_path, 2613) == 10
        assert counts["repaired"] == 1
        assert "REPAIRED" in log.read_text()

    def test_unfetchable_is_marked_missing_not_invented(self, db_path, tmp_path):
        _seed(db_path, [(2512, "2025-08-30", "4,9,13,15,33,40", 1, 0)])
        log = tmp_path / "repair.log"
        counts = repair(db_path=db_path, log_path=log, fetcher=lambda *a: None)
        assert _get(db_path, 2512) == 0  # untouched — no invented number
        assert counts["missing"] == 1
        assert "MISSING" in log.read_text()

    def test_pre_powerball_zero_is_left_alone(self, db_path, tmp_path):
        _seed(db_path, [(500, "1999-07-10", "1,6,7,8,20,36", 35, 0)])

        def boom(*a):  # must not even try to fetch pre-Powerball draws
            raise AssertionError("fetcher called for pre-Powerball draw")

        log = tmp_path / "repair.log"
        counts = repair(db_path=db_path, log_path=log, fetcher=boom)
        assert _get(db_path, 500) == 0
        assert counts["pre_powerball"] == 1
        assert "PRE-POWERBALL" in log.read_text()

    def test_invalid_value_raises_loudly(self, db_path, tmp_path):
        _seed(db_path, [(2625, "2026-09-30", "1,8,19,23,25,30", 7, 0)])
        with pytest.raises(ValueError, match="out of range"):
            repair(
                db_path=db_path, log_path=tmp_path / "repair.log",
                fetcher=lambda n, d, nums, b: (15, "fake"),
            )
        assert _get(db_path, 2625) == 0  # nothing written

    def test_null_powerball_is_repaired(self, db_path, tmp_path):
        _seed(db_path, [(2613, "2026-08-19", "13,16,19,20,25,37", 12, None)])
        repair(db_path=db_path, log_path=tmp_path / "repair.log",
               fetcher=lambda n, d, nums, b: (9, "fake"))
        assert _get(db_path, 2613) == 9

    def test_idempotent_second_run_makes_no_writes(self, db_path, tmp_path):
        _seed(db_path, [(2613, "2026-08-19", "13,16,19,20,25,37", 12, 0)])
        fetcher_calls = []

        def counting_fetcher(n, d, nums, b):
            fetcher_calls.append(n)
            return (9, "fake")

        repair(db_path=db_path, log_path=tmp_path / "r1.log", fetcher=counting_fetcher)
        assert _get(db_path, 2613) == 9
        repair(db_path=db_path, log_path=tmp_path / "r2.log", fetcher=counting_fetcher)
        assert len(fetcher_calls) == 1  # second run found nothing to repair

    def test_valid_rows_never_selected(self, db_path, tmp_path):
        _seed(db_path, [(2621, "2026-09-16", "1,10,20,25,29,30", 35, 11)])
        repair(db_path=db_path, log_path=tmp_path / "repair.log",
               fetcher=lambda *a: (_ for _ in ()).throw(AssertionError("called")))
        assert _get(db_path, 2621) == 11


# ---------------------------------------------------------------------------
# backfill_draws
# ---------------------------------------------------------------------------

def _draw(n: int, date: str, pb: int) -> dict:
    return {
        "draw_number": n,
        "draw_date": date,
        "numbers": [3, 14, 20, 22, 37, 40],
        "bonus": 12,
        "powerball": pb,
    }


# Candidates after anchor 2616, aligned: fetcher(n) returns draw number n.
BACKFILL_MAP = {
    2617: _draw(2617, "2026-09-02", 9),    # pre-change, PB 1-10
    2618: _draw(2618, "2026-09-05", 6),    # pre-change
    2619: _draw(2619, "2026-09-09", 8),    # pre-change
    2620: _draw(2620, "2026-09-12", 7),    # last draw under old rules
    2621: _draw(2621, "2026-09-16", 11),   # FIRST new-rules draw: PB 11 valid 1-14
}


class TestBackfill:
    def _fetcher(self, mapping):
        return lambda n: mapping.get(n)

    def test_inserts_missing_draws_with_post_change_pb_range(self, db_path, tmp_path):
        _seed(db_path, [(2616, "2026-08-29", "2,5,20,24,25,31", 18, 5)])
        log = tmp_path / "backfill.log"
        counts = backfill(db_path=db_path, log_path=log, end=2621,
                          fetcher=self._fetcher(BACKFILL_MAP))
        assert counts["inserted"] == 5
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT draw_date, powerball FROM draws WHERE draw_date >= '2026-09-16' "
            "ORDER BY draw_date"
        ).fetchall()
        conn.close()
        assert rows == [("2026-09-16", 11)]  # changeover draw present, PB in 1-14
        assert "INSERTED" in log.read_text()

    def test_skips_existing_and_is_idempotent(self, db_path, tmp_path):
        _seed(db_path, [
            (2616, "2026-08-29", "2,5,20,24,25,31", 18, 5),
            (2617, "2026-09-02", "11,13,14,21,27,39", 32, 9),
        ])
        log1 = tmp_path / "b1.log"
        counts1 = backfill(db_path=db_path, log_path=log1, end=2621,
                           fetcher=self._fetcher(BACKFILL_MAP))
        counts2 = backfill(db_path=db_path, log_path=tmp_path / "b2.log", end=2621,
                           fetcher=self._fetcher(BACKFILL_MAP))
        assert counts1["inserted"] == 4
        assert counts2["inserted"] == 0
        assert _duplicates(db_path) == []

    def test_rejects_out_of_era_powerball_loudly(self, db_path, tmp_path):
        _seed(db_path, [(2616, "2026-08-29", "2,5,20,24,25,31", 18, 5)])
        bad = {2617: _draw(2617, "2026-09-05", 13)}  # pre-change: PB must be 1-10
        with pytest.raises(ValueError, match="out of range"):
            backfill(db_path=db_path, log_path=tmp_path / "b.log", end=2617,
                     fetcher=self._fetcher(bad))
        conn = sqlite3.connect(db_path)
        n = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
        conn.close()
        assert n == 1  # nothing inserted

    def test_not_found_is_logged_and_not_fatal(self, db_path, tmp_path):
        _seed(db_path, [(2616, "2026-08-29", "2,5,20,24,25,31", 18, 5)])
        mapping = {2617: BACKFILL_MAP[2617], 2618: None}
        log = tmp_path / "b.log"
        counts = backfill(db_path=db_path, log_path=log, end=2618,
                          fetcher=self._fetcher(mapping))
        assert counts["not_found"] == 1
        assert counts["inserted"] == 1
        assert "NOT-FOUND" in log.read_text()
        assert _duplicates(db_path) == []

    def test_no_duplicate_draw_dates(self, db_path, tmp_path):
        _seed(db_path, [
            (2616, "2026-08-29", "2,5,20,24,25,31", 18, 5),
            (2617, "2026-09-02", "11,13,14,21,27,39", 32, 9),
        ])
        backfill(db_path=db_path, log_path=tmp_path / "b.log", end=2621,
                 fetcher=self._fetcher(BACKFILL_MAP))
        assert _duplicates(db_path) == []
