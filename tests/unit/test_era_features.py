"""Tests for the rule-era system: era flags, pool sizes, the mixed-era
training guard, and the draws-table rule_era migration.

Acceptance covered here:
  - Post-change Powerball training data contains only post-change draws.
  - Mixed-era training without the explicit era-aware flag is blocked.
  - The rule_era column migrates and backfills correctly on a temp DB.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from era_features import (
    RULE_ERA_POST,
    RULE_ERA_PRE,
    MixedEraTrainingError,
    check_single_era,
    current_rule_era,
    ensure_rule_era_column,
    era_flags,
    filter_draws_by_era,
    powerball_pool_size,
    powerball_training_draws,
    rule_era_for_date,
)


def _draw(d: str, pb: int) -> dict:
    return {"draw_date": d, "numbers": [1, 2, 3, 4, 5, 6], "powerball": pb}


MIXED = [_draw("2026-09-12", 7), _draw("2026-09-16", 11), _draw("2026-09-19", 14)]
POST_ONLY = [_draw("2026-09-16", 11), _draw("2026-09-19", 14), _draw("2026-09-23", 12)]
PRE_ONLY = [_draw("2026-09-09", 10), _draw("2026-09-12", 7)]


class TestRuleEraLabels:
    def test_boundary(self):
        assert rule_era_for_date("2026-09-12") == RULE_ERA_PRE
        assert rule_era_for_date("2026-09-16") == RULE_ERA_POST
        assert rule_era_for_date(date(2026, 9, 16)) == RULE_ERA_POST

    def test_current_era_is_post(self):
        assert current_rule_era() == RULE_ERA_POST

    def test_pool_sizes(self):
        assert powerball_pool_size(RULE_ERA_PRE) == 10
        assert powerball_pool_size(RULE_ERA_POST) == 14
        assert powerball_pool_size() == 14  # current era

    def test_unknown_era_rejected(self):
        with pytest.raises(ValueError, match="Unknown rule era"):
            powerball_pool_size("nonsense")


class TestFilterDrawsByEra:
    def test_post_filter(self):
        result = filter_draws_by_era(MIXED, RULE_ERA_POST)
        assert [d["draw_date"] for d in result] == ["2026-09-16", "2026-09-19"]
        assert all(d["powerball"] > 10 for d in result)  # 1-14 distribution only

    def test_pre_filter(self):
        result = filter_draws_by_era(MIXED, RULE_ERA_PRE)
        assert [d["draw_date"] for d in result] == ["2026-09-12"]

    def test_tuple_draws_with_date_index(self):
        draws = [([1, 2, 3, 4, 5, 6], 7, 21, "2026-09-12"), ([1, 2, 3, 4, 5, 6], 11, 21, "2026-09-16")]
        result = filter_draws_by_era(draws, RULE_ERA_POST, date_index=3)
        assert len(result) == 1 and result[0][1] == 11

    def test_missing_date_raises(self):
        with pytest.raises(ValueError, match="draw_date"):
            filter_draws_by_era([{"powerball": 5}], RULE_ERA_POST)


class TestMixedEraGuard:
    """The guard that blocks mixed-era Powerball training."""

    def test_mixed_eras_raise_without_flag(self):
        with pytest.raises(MixedEraTrainingError, match="mixes rule eras"):
            check_single_era(MIXED, context="unit-test")

    def test_training_draws_default_never_mixes(self):
        """Default training-data selection filters to one era — mixing is
        impossible, which is the block. (Direct mixed input to the guard
        itself raises: see test_mixed_eras_raise_without_flag.)"""
        result = powerball_training_draws(MIXED)
        assert {d["draw_date"] for d in result} == {"2026-09-16", "2026-09-19"}
        eras = {rule_era_for_date(d["draw_date"]) for d in result}
        assert eras == {RULE_ERA_POST}

    def test_single_era_passes(self):
        assert check_single_era(POST_ONLY, context="unit-test") == RULE_ERA_POST
        assert check_single_era(PRE_ONLY) == RULE_ERA_PRE
        assert check_single_era([]) is None

    def test_era_aware_opt_in_allowed(self):
        # Explicitly era-aware: mixing permitted, caller adds era flags as features
        assert check_single_era(MIXED, era_aware=True) is None
        assert era_flags(MIXED) == [0, 1, 1]

    def test_training_draws_default_is_current_era_only(self):
        result = powerball_training_draws(MIXED)
        assert {d["draw_date"] for d in result} == {"2026-09-16", "2026-09-19"}

    def test_training_draws_era_aware_returns_all(self):
        result = powerball_training_draws(MIXED, era_aware=True)
        assert len(result) == 3

    def test_training_draws_with_tuples(self):
        draws = [([1, 2, 3, 4, 5, 6], 7, 21, "2026-09-12"), ([1, 2, 3, 4, 5, 6], 11, 21, "2026-09-16")]
        result = powerball_training_draws(draws, date_index=3)
        assert len(result) == 1 and result[0][1] == 11


# ---------------------------------------------------------------------------
# draws-table rule_era migration (temporary DB)
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE draws (
    draw_id    INTEGER PRIMARY KEY,
    draw_number INTEGER,
    draw_date  TEXT NOT NULL UNIQUE,
    numbers    TEXT NOT NULL,
    bonus      INTEGER,
    powerball  INTEGER
)
"""


@pytest.fixture
def db_conn(tmp_path):
    conn = sqlite3.connect(tmp_path / "lotto.db")
    conn.execute(SCHEMA)
    conn.executemany(
        "INSERT INTO draws (draw_number, draw_date, numbers, bonus, powerball) VALUES (?, ?, ?, ?, ?)",
        [
            (2620, "2026-09-12", "3,4,26,29,38,40", 27, 7),
            (2621, "2026-09-16", "1,10,20,25,29,30", 35, 11),
            (2622, "2026-09-19", "7,10,11,28,35,37", 12, 14),
        ],
    )
    conn.commit()
    return conn


class TestRuleEraMigration:
    def test_column_created_and_backfilled(self, db_conn):
        created = ensure_rule_era_column(db_conn)
        assert created is True
        rows = dict(
            db_conn.execute("SELECT draw_date, rule_era FROM draws ORDER BY draw_date").fetchall()
        )
        assert rows == {
            "2026-09-12": RULE_ERA_PRE,
            "2026-09-16": RULE_ERA_POST,
            "2026-09-19": RULE_ERA_POST,
        }

    def test_idempotent_second_call(self, db_conn):
        assert ensure_rule_era_column(db_conn) is True
        assert ensure_rule_era_column(db_conn) is False
        assert db_conn.execute("SELECT COUNT(*) FROM draws WHERE rule_era IS NULL").fetchone()[0] == 0

    def test_existing_values_not_overwritten(self, db_conn):
        ensure_rule_era_column(db_conn)
        db_conn.execute(
            "UPDATE draws SET rule_era = 'custom' WHERE draw_date = '2026-09-12'"
        )
        db_conn.commit()
        ensure_rule_era_column(db_conn)
        val = db_conn.execute(
            "SELECT rule_era FROM draws WHERE draw_date = '2026-09-12'"
        ).fetchone()[0]
        assert val == "custom"
