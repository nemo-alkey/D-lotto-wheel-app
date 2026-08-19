"""Unit tests for the bonus-impact analysis in backtest.py.

Covers:
  - simulate_bonus_ev(): Monte Carlo bonus premium for a wheel — return
    structure, upgrade detection, the "what-if" ev_without_bonus path
    (bonus ignored), edge cases (empty wheel, unknown wheel name).
  - backtest_bonus_impact(): structured bonus-impact over draw history —
    tiny/absent history (patched load_draws), unknown wheel, and a hermetic
    1-draw SQLite database (integration).

fetch_payouts is ALWAYS mocked (patch on prize_calculator, since backtest
imports it lazily inside each function) — no network in tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

import backtest

# Fixed payout table: every bonus-upgraded division pays strictly more than
# its non-bonus counterpart (Div2>Div3, Div4>Div5, Div6>Div7) so the bonus
# can only ever add value.
MOCK_PAYOUTS = {
    "lotto": {
        1: 1_000_000.0,
        2: 30_000.0,
        3: 1_000.0,
        4: 500.0,
        5: 100.0,
        6: 50.0,
        7: 20.0,
    },
    "powerball": {
        1: 5_000_000.0,
        2: 50_000.0,
        3: 5_000.0,
        4: 800.0,
        5: 200.0,
        6: 100.0,
        7: 15.0,
    },
    "draw_date": "2024-01-01",
    "draw_number": 2200,
}

# Payout table where bonus-upgraded divisions pay EXACTLY the same as their
# non-bonus counterparts → the bonus ball adds zero value (fully
# deterministic: upgrade_count must be 0 and the two EVs must be equal).
FLAT_PAYOUTS = {
    "lotto": {
        1: 1_000_000.0,
        2: 1_000.0,
        3: 1_000.0,
        4: 100.0,
        5: 100.0,
        6: 20.0,
        7: 20.0,
    },
    "powerball": {
        1: 5_000_000.0,
        2: 5_000.0,
        3: 5_000.0,
        4: 200.0,
        5: 200.0,
        6: 15.0,
        7: 15.0,
    },
    "draw_date": "2024-01-01",
    "draw_number": 2200,
}


@pytest.fixture
def mock_payouts() -> Iterator[None]:
    with patch("prize_calculator.fetch_payouts", return_value=dict(MOCK_PAYOUTS)):
        yield


@pytest.fixture
def flat_payouts() -> Iterator[None]:
    with patch("prize_calculator.fetch_payouts", return_value=dict(FLAT_PAYOUTS)):
        yield


# ---------------------------------------------------------------------------
# simulate_bonus_ev — structure and basic invariants
# ---------------------------------------------------------------------------


class TestSimulateBonusEvStructure:
    EXPECTED_KEYS = {
        "ev_with_bonus",
        "ev_without_bonus",
        "bonus_premium_percent",
        "upgrade_count",
        "avg_prize_with",
        "avg_prize_without",
    }

    def test_returns_expected_keys(
        self, mock_payouts: None, sample_wheel: list[tuple[int, ...]]
    ) -> None:
        result = backtest.simulate_bonus_ev(sample_wheel, num_sims=500)
        assert set(result) >= self.EXPECTED_KEYS
        assert result["ev_with_bonus"] >= 0.0
        assert result["ev_without_bonus"] >= 0.0
        assert result["upgrade_count"] >= 0

    def test_wheel_accepts_name_string(self, mock_payouts: None) -> None:
        # A wheel name (key in WHEELS) resolves via lotto_wheels.WHEELS.
        result = backtest.simulate_bonus_ev("single1", num_sims=500)
        assert set(result) >= self.EXPECTED_KEYS

    def test_unknown_wheel_name_raises(self, mock_payouts: None) -> None:
        with pytest.raises(ValueError, match="Unknown wheel"):
            backtest.simulate_bonus_ev("no-such-wheel", num_sims=100)

    def test_empty_wheel_returns_zeros(self, mock_payouts: None) -> None:
        result = backtest.simulate_bonus_ev([], num_sims=100)
        assert result == {
            "ev_with_bonus": 0.0,
            "ev_without_bonus": 0.0,
            "bonus_premium_percent": 0.0,
            "upgrade_count": 0,
            "avg_prize_with": 0.0,
            "avg_prize_without": 0.0,
        }


# ---------------------------------------------------------------------------
# simulate_bonus_ev — upgrade detection and the with/without bonus paths
# ---------------------------------------------------------------------------


class TestSimulateBonusEvUpgrades:
    def test_bonus_never_reduces_ev(
        self, mock_payouts: None, sample_wheel: list[tuple[int, ...]]
    ) -> None:
        # Cell-by-cell the with-bonus prize is >= the without-bonus prize
        # (every bonus-upgraded division pays more), so this inequality is
        # deterministic regardless of the random draws.
        result = backtest.simulate_bonus_ev(sample_wheel, num_sims=2_000)
        assert result["ev_with_bonus"] >= result["ev_without_bonus"]
        assert result["upgrade_count"] >= 0

    def test_upgrades_detected_over_sims(self, mock_payouts: None) -> None:
        # single1 has 20 tickets; over 5 000 sims the expected number of
        # bonus-upgrade hits is large enough that zero is effectively
        # impossible, so a strict > 0 assertion is safe.
        result = backtest.simulate_bonus_ev("single1", num_sims=5_000)
        assert result["upgrade_count"] > 0
        # Any counted upgrade means the with-bonus total strictly exceeds
        # the without-bonus total.
        assert result["ev_with_bonus"] > result["ev_without_bonus"]
        assert result["bonus_premium_percent"] > 0.0

    def test_premium_percent_internally_consistent(
        self, mock_payouts: None, sample_wheel: list[tuple[int, ...]]
    ) -> None:
        result = backtest.simulate_bonus_ev(sample_wheel, num_sims=2_000)
        ev_w = result["ev_with_bonus"]
        ev_wo = result["ev_without_bonus"]
        if ev_wo > 0:
            expected = round((ev_w - ev_wo) / ev_wo * 100, 2)
            assert result["bonus_premium_percent"] == pytest.approx(expected, abs=0.02)
        else:
            assert result["bonus_premium_percent"] == 0.0

    def test_without_bonus_path_ignores_bonus(
        self, flat_payouts: None, sample_wheel: list[tuple[int, ...]]
    ) -> None:
        # "What-if" / standard-lotto mode: ev_without_bonus is always scored
        # with bonus_matched=False.  With FLAT_PAYOUTS the bonus divisions
        # pay the same as their non-bonus counterparts, so both paths must
        # produce identical EVs and zero upgrades — proving the
        # without-bonus path never picks up bonus-division value.
        result = backtest.simulate_bonus_ev(sample_wheel, num_sims=1_000)
        assert result["upgrade_count"] == 0
        assert result["ev_with_bonus"] == result["ev_without_bonus"]
        assert result["bonus_premium_percent"] == 0.0
        # Quirk in backtest.py: avg_prize_with is total_with / upgrade_count
        # (not per-sim), so it is 0.0 whenever no upgrades occurred.
        assert result["avg_prize_with"] == 0.0

    def test_pool_allocation_mode_smoke(
        self, mock_payouts: None, sample_wheel: list[tuple[int, ...]]
    ) -> None:
        # use_pool_allocation=True routes prizes through allocate_pool()
        # per simulated draw; keep the sim count tiny (per-sim Python loop).
        result = backtest.simulate_bonus_ev(
            sample_wheel,
            num_sims=200,
            use_pool_allocation=True,
            total_turnover=1_000_000.0,
        )
        assert result["allocation_mode"] == "pool"
        assert "div1_capped_draws" in result
        assert "per_winner_breakdown" in result
        assert result["ev_with_bonus"] >= result["ev_without_bonus"]
        assert result["upgrade_count"] >= 0

    @pytest.mark.slow
    def test_premium_positive_with_larger_sample(self, mock_payouts: None) -> None:
        result = backtest.simulate_bonus_ev("single1", num_sims=50_000)
        assert result["upgrade_count"] > 0
        assert result["bonus_premium_percent"] > 0.0
        assert result["ev_with_bonus"] > result["ev_without_bonus"]


# ---------------------------------------------------------------------------
# backtest_bonus_impact — history-driven behaviour
# ---------------------------------------------------------------------------


class TestBacktestBonusImpact:
    def test_no_draws_returns_error(self, mock_payouts: None) -> None:
        with patch("backtest.load_draws", return_value=[]):
            result = backtest.backtest_bonus_impact("single1")
        assert result == {"error": "No draws found."}

    def test_unknown_wheel_returns_error(
        self, mock_payouts: None, sample_draws: list[tuple[list[int], int, int, str]]
    ) -> None:
        with patch("backtest.load_draws", return_value=sample_draws):
            result = backtest.backtest_bonus_impact("no-such-wheel")
        assert "error" in result
        assert "Unknown wheel" in result["error"]

    def test_tiny_history_returns_structured_result(
        self, mock_payouts: None, sample_draws: list[tuple[list[int], int, int, str]]
    ) -> None:
        tiny = sample_draws[:5]
        with patch("backtest.load_draws", return_value=tiny):
            result = backtest.backtest_bonus_impact("single1", num_draws=3)

        assert "error" not in result
        assert result["wheel"] == "single1"
        assert result["draws_tested"] == 3
        assert result["upgraded_tickets"] >= 0
        # Bonus can only add value with MOCK_PAYOUTS.
        assert result["total_prize_with_bonus"] >= result["total_prize_without_bonus"]
        # bonus_added_value only counts pb_hit upgrades (matches 3-5), while
        # the with/without difference also includes non-PB bonus upgrades —
        # so the difference is always >= the tracked added value.
        diff = result["total_prize_with_bonus"] - result["total_prize_without_bonus"]
        assert diff >= result["bonus_added_value"] - 1e-9
        assert result["bonus_premium_percent"] >= 0.0
        # Premium formula consistency (when the denominator is non-zero).
        two = result["total_prize_without_bonus"]
        if two > 0:
            expected = round((result["total_prize_with_bonus"] - two) / two * 100, 2)
            assert result["bonus_premium_percent"] == pytest.approx(expected, abs=0.02)
        # Upgrade breakdown keys, if any, are "from->to" division strings.
        for key, count in result["upgrade_breakdown"].items():
            assert "->" in key
            assert count > 0

    def test_num_draws_defaults_to_all_and_clamps(
        self, mock_payouts: None, sample_draws: list[tuple[list[int], int, int, str]]
    ) -> None:
        tiny = sample_draws[:5]
        with patch("backtest.load_draws", return_value=tiny):
            default = backtest.backtest_bonus_impact("single1")
            clamped = backtest.backtest_bonus_impact("single1", num_draws=10_000)
        assert default["draws_tested"] == 5
        assert clamped["draws_tested"] == 5
        # Same window → identical totals.
        assert default["total_prize_with_bonus"] == clamped["total_prize_with_bonus"]

    @pytest.mark.integration
    def test_real_single_draw_database(self, mock_payouts: None, tmp_path: Path) -> None:
        # Hermetic single-draw database. The original version of this test
        # ran against the local lotto.db, which is gitignored and whose
        # contents vary per machine (CI seeds 60 synthetic draws), making
        # the "exactly 1 draw" assertion non-deterministic. Here we build a
        # dedicated one-draw SQLite file; load_draws still runs unpatched
        # through the real SQLAlchemy engine path (fetch_payouts stays
        # mocked — no network).
        import sqlite3

        from sqlalchemy import create_engine

        db_file = tmp_path / "one_draw.db"
        conn = sqlite3.connect(db_file)
        conn.execute(
            "CREATE TABLE draws (draw_id INTEGER PRIMARY KEY, draw_date TEXT, "
            "numbers TEXT, bonus INTEGER, powerball INTEGER)"
        )
        conn.execute(
            "INSERT INTO draws (draw_id, draw_date, numbers, bonus, powerball) "
            "VALUES (1, '2024-01-01', '1,2,3,4,5,6', 7, 1)"
        )
        conn.commit()
        conn.close()

        engine = create_engine(f"sqlite:///{db_file}")
        with patch("lotto_wheels.get_engine", return_value=engine):
            result = backtest.backtest_bonus_impact("single1")
        assert "error" not in result
        assert result["draws_tested"] == 1
        assert result["total_prize_with_bonus"] >= result["total_prize_without_bonus"]
