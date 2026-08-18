"""Unit tests for prize_calculator.py.

Covers:
  - resolve_divisions(): official NZ Lotto Powerball division mapping
    (all 7 Powerball divisions + lotto-only, no-Powerball mapping).
  - get_prize_for_matches(): prize dict assembly with mocked payouts
    (fetch_payouts is ALWAYS mocked — no network in tests).
  - allocate_pool(): prize-pool splitting, Div 1 $50M cap behaviour,
    Div 7 fixed prizes, roll-down redistribution, lotto (no-cap) mode.
  - Real behaviour for invalid inputs (no input validation exists —
    tests document what the code actually does rather than inventing
    exceptions).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import prize_calculator as pc

# Fixed payout table used for every mocked fetch_payouts call.
MOCK_PAYOUTS: dict[str, Any] = {
    "lotto": {
        1: 1_000_000.0,
        2: 30_000.0,
        3: 1_000.0,
        4: 100.0,
        5: 60.0,
        6: 40.0,
        7: 20.0,
    },
    "powerball": {
        1: 10_000_000.0,
        2: 100_000.0,
        3: 5_000.0,
        4: 500.0,
        5: 200.0,
        6: 100.0,
        7: 15.0,
    },
    "draw_date": "2024-01-01",
    "draw_number": 2200,
}


@pytest.fixture
def mock_payouts() -> Iterator[MagicMock]:
    """Patch fetch_payouts to return a fixed table (offline, deterministic)."""
    with patch("prize_calculator.fetch_payouts", return_value=dict(MOCK_PAYOUTS)) as m:
        yield m


# ---------------------------------------------------------------------------
# resolve_divisions — Powerball divisions (pb_hit=True)
# ---------------------------------------------------------------------------


class TestResolveDivisionsPowerball:
    """All 7 official Powerball divisions resolve to (lotto_div, pb_div)."""

    def test_div1_six_mains_plus_pb(self) -> None:
        # Bonus is irrelevant for Div 1.
        assert pc.resolve_divisions(6, False, True) == (1, 1)
        assert pc.resolve_divisions(6, True, True) == (1, 1)

    def test_div2_five_mains_bonus_pb(self) -> None:
        assert pc.resolve_divisions(5, True, True) == (2, 2)

    def test_div3_five_mains_pb_no_bonus(self) -> None:
        assert pc.resolve_divisions(5, False, True) == (3, 3)

    def test_div4_four_mains_bonus_pb(self) -> None:
        assert pc.resolve_divisions(4, True, True) == (4, 4)

    def test_div5_four_mains_pb_no_bonus(self) -> None:
        assert pc.resolve_divisions(4, False, True) == (5, 5)

    def test_div6_three_mains_bonus_pb(self) -> None:
        assert pc.resolve_divisions(3, True, True) == (6, 6)

    def test_div7_three_mains_pb_no_bonus(self) -> None:
        assert pc.resolve_divisions(3, False, True) == (7, 7)


# ---------------------------------------------------------------------------
# resolve_divisions — Lotto-only (pb_hit=False → pb component always None)
# ---------------------------------------------------------------------------


class TestResolveDivisionsLottoOnly:
    @pytest.mark.parametrize(
        "main,bonus,expected_lotto_div",
        [
            (6, False, 1),
            (6, True, 1),  # bonus irrelevant at 6 mains
            (5, True, 2),
            (5, False, 3),
            (4, True, 4),
            (4, False, 5),
            (3, True, 6),
            (3, False, 7),
        ],
    )
    def test_lotto_only_mapping(self, main: int, bonus: bool, expected_lotto_div: int) -> None:
        lotto_div, pb_div = pc.resolve_divisions(main, bonus, False)
        assert lotto_div == expected_lotto_div
        assert pb_div is None

    @pytest.mark.parametrize("main", [0, 1, 2])
    def test_fewer_than_3_mains_no_win(self, main: int) -> None:
        assert pc.resolve_divisions(main, False, False) == (None, None)
        assert pc.resolve_divisions(main, True, False) == (None, None)
        assert pc.resolve_divisions(main, False, True) == (None, None)
        assert pc.resolve_divisions(main, True, True) == (None, None)


# ---------------------------------------------------------------------------
# get_prize_for_matches — with mocked payouts
# ---------------------------------------------------------------------------


class TestGetPrizeForMatches:
    @pytest.mark.parametrize(
        "main,bonus,pb,expected_div",
        [
            (6, False, True, 1),
            (5, True, True, 2),
            (5, False, True, 3),
            (4, True, True, 4),
            (4, False, True, 5),
            (3, True, True, 6),
            (3, False, True, 7),
        ],
    )
    def test_all_seven_powerball_divisions_pay_lotto_plus_pb(
        self, mock_payouts: MagicMock, main: int, bonus: bool, pb: bool, expected_div: int
    ) -> None:
        info = pc.get_prize_for_matches(main, bonus, pb)
        expected = MOCK_PAYOUTS["lotto"][expected_div] + MOCK_PAYOUTS["powerball"][expected_div]
        assert info["main_division"] == expected_div
        assert info["pb_division"] == expected_div
        assert info["main_prize"] == MOCK_PAYOUTS["lotto"][expected_div]
        assert info["pb_prize"] == MOCK_PAYOUTS["powerball"][expected_div]
        assert info["total_prize"] == pytest.approx(expected)
        assert info["combined_label"] == f"Div {expected_div}+PB"
        assert info["is_estimated"] is False
        assert info["draw_date"] == "2024-01-01"

    @pytest.mark.parametrize("main", [0, 1, 2])
    def test_fewer_than_3_mains_pays_zero(self, mock_payouts: MagicMock, main: int) -> None:
        info = pc.get_prize_for_matches(main, True, True)
        assert info["total_prize"] == 0.0
        assert info["main_prize"] == 0.0
        assert info["pb_prize"] == 0.0
        assert info["main_division"] is None
        assert info["pb_division"] is None
        assert info["combined_label"] == "No win"
        assert info["main_label"] == "No win"

    def test_lotto_only_prizes_use_lotto_table(self, mock_payouts: MagicMock) -> None:
        # 5 mains + bonus, no PB → Div 2 lotto prize only.
        info = pc.get_prize_for_matches(5, True, False)
        assert info["main_division"] == 2
        assert info["pb_division"] is None
        assert info["pb_prize"] == 0.0
        assert info["total_prize"] == MOCK_PAYOUTS["lotto"][2]

    def test_fallback_when_fetch_fails(self) -> None:
        # fetch_payouts returning None → static fallback, is_estimated=True.
        with patch("prize_calculator.fetch_payouts", return_value=None):
            info = pc.get_prize_for_matches(3, False, True)
        assert info["is_estimated"] is True
        assert info["main_division"] == 7
        assert info["pb_division"] == 7
        assert info["total_prize"] == pytest.approx(
            pc.FALLBACK_LOTTO.get(7, 0.0) + pc.FALLBACK_PB.get(7, 0.0)
        )


# ---------------------------------------------------------------------------
# Invalid / out-of-range inputs — documents REAL behaviour (no validation)
# ---------------------------------------------------------------------------


class TestInvalidInputs:
    def test_seven_main_matches_treated_as_six(self, mock_payouts: MagicMock) -> None:
        # resolve_divisions has no upper bound check: main_matches >= 6 maps
        # to Div 1, so 7 matches silently pays the Div 1 prize.  This is the
        # real (arguably lenient) behaviour — asserted, not "fixed".
        assert pc.resolve_divisions(7, False, True) == (1, 1)
        info = pc.get_prize_for_matches(7, False, True)
        assert info["main_division"] == 1
        assert info["total_prize"] == pytest.approx(
            MOCK_PAYOUTS["lotto"][1] + MOCK_PAYOUTS["powerball"][1]
        )

    def test_negative_main_matches_no_win(self, mock_payouts: MagicMock) -> None:
        # Negative counts fall through the < 3 guard → no win, no exception.
        assert pc.resolve_divisions(-1, True, True) == (None, None)
        info = pc.get_prize_for_matches(-1, True, True)
        assert info["total_prize"] == 0.0
        assert info["combined_label"] == "No win"

    def test_get_prize_for_draw_validates_ticket_shape(self) -> None:
        # By contrast, get_prize_for_draw DOES validate its inputs.
        with pytest.raises(ValueError):
            pc.get_prize_for_draw([1, 2, 3, 4, 5], 3)
        with pytest.raises(ValueError):
            pc.get_prize_for_draw([1, 1, 2, 3, 4, 5], 3)
        with pytest.raises(ValueError):
            pc.get_prize_for_draw([1, 2, 3, 4, 5, 6], 11)


# ---------------------------------------------------------------------------
# allocate_pool — Div 1 cap, Div 7 fixed prizes, roll-down, lotto mode
# ---------------------------------------------------------------------------


class TestAllocatePool:
    def test_div1_capped_when_raw_share_exceeds_cap(self) -> None:
        # $100M turnover, no reserve, 1 Div 1 winner.
        # Raw Div 1 share = 85.74% × $100M = $85.74M > $50M cap.
        result = pc.allocate_pool(
            100_000_000.0,
            winners_per_division={1: 1},
            game="powerball",
            reserve_rate=0.0,
        )
        raw_share = round(100_000_000.0 * pc.PB_POOL_PERCENTAGES[1] / 100.0, 2)
        assert raw_share > pc.DIV1_CAP  # sanity: scenario actually exceeds cap

        assert result["div1_capped"] is True
        assert result["per_winner"][1] == pc.DIV1_CAP
        assert result["total_per_division"][1] == pc.DIV1_CAP
        # Excess is tracked and goes to reserve, NOT redistributed.
        assert result["excess_to_reserve"] == pytest.approx(raw_share - pc.DIV1_CAP)

    def test_div1_below_cap_not_capped_and_gets_rolldown(self) -> None:
        # $1M turnover, only a Div 1 winner: raw share is below the cap, and
        # every other division's un-won share rolls down to Div 1, so the
        # single winner collects the entire remaining pool.
        result = pc.allocate_pool(
            1_000_000.0,
            winners_per_division={1: 1},
            game="powerball",
            reserve_rate=0.0,
        )
        assert result["div1_capped"] is False
        assert result["excess_to_reserve"] == 0.0
        assert result["per_winner"][1] == pytest.approx(1_000_000.0)

    def test_custom_cap_override(self) -> None:
        result = pc.allocate_pool(
            1_000_000.0,
            winners_per_division={1: 1},
            game="powerball",
            reserve_rate=0.0,
            div1_cap=500_000.0,
        )
        raw_share = round(1_000_000.0 * pc.PB_POOL_PERCENTAGES[1] / 100.0, 2)
        assert result["div1_capped"] is True
        assert result["per_winner"][1] == 500_000.0
        assert result["excess_to_reserve"] == pytest.approx(raw_share - 500_000.0)

    def test_lotto_game_has_no_div1_cap(self) -> None:
        # Lotto mode: div1_cap defaults to None — no cap even at $100M.
        result = pc.allocate_pool(
            100_000_000.0,
            winners_per_division={1: 1},
            game="lotto",
            reserve_rate=0.0,
        )
        assert result["div1_capped"] is False
        assert result["excess_to_reserve"] == 0.0
        assert result["per_winner"][1] == pytest.approx(100_000_000.0)
        assert result["game"] == "lotto"

    def test_div7_fixed_prizes_deducted_first(self) -> None:
        # 10 Div 7 winners × $15 fixed (Powerball) = $150 off the top.
        result = pc.allocate_pool(
            1_000_000.0,
            winners_per_division={7: 10},
            game="powerball",
            reserve_rate=0.0,
        )
        assert result["div7_fixed_total"] == pytest.approx(10 * pc.DIV7_PB_PRIZE)
        assert result["per_winner"][7] == pc.DIV7_PB_PRIZE
        assert result["remaining_pool"] == pytest.approx(1_000_000.0 - 10 * pc.DIV7_PB_PRIZE)

    def test_single_winning_division_collects_whole_remaining_pool(self) -> None:
        # Reserve 25%, 100 Div 7 winners, then only Div 3 has winners —
        # roll-down gives Div 3 the entire remaining pool.
        result = pc.allocate_pool(
            1_000_000.0,
            winners_per_division={3: 2, 7: 100},
            game="powerball",
            reserve_rate=0.25,
        )
        assert result["reserve_deduction"] == 250_000.0
        assert result["prize_pool"] == 750_000.0
        div7_total = round(100 * pc.DIV7_PB_PRIZE, 2)
        remaining = 750_000.0 - div7_total
        assert result["remaining_pool"] == pytest.approx(remaining)
        # 2 Div 3 winners split the whole remaining pool evenly.
        assert result["per_winner"][3] == pytest.approx(remaining / 2)

    def test_pool_too_small_for_div7_pays_what_it_can(self) -> None:
        # Edge case in the code: when the pool can't cover Div 7 fixed
        # prizes, div7_fixed_total is clamped to the pool.
        result = pc.allocate_pool(
            10.0,
            winners_per_division={7: 5},
            game="powerball",
            reserve_rate=0.0,
        )
        assert result["div7_fixed_total"] == 10.0
        assert result["remaining_pool"] == 0.0

    def test_no_winners_at_all(self) -> None:
        result = pc.allocate_pool(1_000_000.0, game="powerball", reserve_rate=0.25)
        assert result["prize_pool"] == 750_000.0
        assert result["div7_fixed_total"] == 0.0
        assert result["per_winner"] == {}
        assert result["div1_capped"] is False


# ---------------------------------------------------------------------------
# calculate_lotto_only_prize — standard Lotto (bonus still upgrades)
# ---------------------------------------------------------------------------


class TestCalculateLottoOnlyPrize:
    @pytest.mark.parametrize(
        "main,bonus,expected_div",
        [
            (6, False, 1),
            (5, True, 2),
            (5, False, 3),
            (4, True, 4),
            (4, False, 5),
            (3, True, 6),
            (3, False, 7),
        ],
    )
    def test_lotto_only_divisions(self, main: int, bonus: bool, expected_div: int) -> None:
        pool = 215_000.0
        info = pc.calculate_lotto_only_prize(main, bonus, pool_amount=pool)
        assert info["division"] == expected_div
        expected_prize = round(pool * pc.LOTTO_POOL_PERCENTAGES[expected_div] / 100.0, 2)
        assert info["prize"] == pytest.approx(expected_prize)

    def test_lotto_only_no_win_under_3_matches(self) -> None:
        info = pc.calculate_lotto_only_prize(2, True, pool_amount=215_000.0)
        assert info["division"] is None
        assert info["prize"] == 0.0
        assert info["division_label"] == "No win"

    def test_bonus_upgrades_lotto_only_prize(self) -> None:
        # 5 mains: bonus upgrades Div 3 → Div 2, which pays a different share.
        with_bonus = pc.calculate_lotto_only_prize(5, True)
        without_bonus = pc.calculate_lotto_only_prize(5, False)
        assert with_bonus["division"] == 2
        assert without_bonus["division"] == 3
        assert with_bonus["prize"] != without_bonus["prize"]
