"""Unit tests for numerical-attraction / hot-cold classification helpers.

Targets:
  - lotto_wheels.numerical_attraction
  - quantum_selector.build_attraction_profile
  - pos_neg_tracker.classify_pos_neg
"""

from __future__ import annotations

from lotto_wheels import numerical_attraction
from pos_neg_tracker import classify_pos_neg
from quantum_selector import build_attraction_profile


def _make_draws(
    numbers_list: list[list[int]],
    powerball: int = 1,
    bonus: int = 1,
    date: str = "2024-01-01",
) -> list[tuple[list[int], int, int, str]]:
    """Wrap plain number lists in the 4-tuple shape lotto_wheels expects."""
    return [(list(nums), powerball, bonus, date) for nums in numbers_list]


class TestNumericalAttraction:
    def test_all_draws_with_consecutive_pair_returns_one(self) -> None:
        # Every draw contains the consecutive pair (5, 6); all other gaps > 2.
        draws = _make_draws([[5, 6, 12, 20, 28, 36]] * 30)
        assert numerical_attraction(draws, last_n=30) == 1.0

    def test_plus_two_gap_counts_as_attraction(self) -> None:
        # Gap of exactly 2 (7, 9) also satisfies gap <= 2.
        draws = _make_draws([[7, 9, 15, 23, 31, 39]] * 30)
        assert numerical_attraction(draws, last_n=30) == 1.0

    def test_no_close_pairs_returns_zero(self) -> None:
        # Minimum gap in this draw is 4.
        draws = _make_draws([[1, 10, 20, 30, 35, 40]] * 30)
        assert numerical_attraction(draws, last_n=30) == 0.0

    def test_fraction_of_draws_with_close_pairs(self) -> None:
        with_pair = [[5, 6, 12, 20, 28, 36]] * 15
        without_pair = [[1, 10, 20, 30, 35, 40]] * 15
        draws = _make_draws(with_pair + without_pair)
        assert numerical_attraction(draws, last_n=30) == 0.5

    def test_result_within_unit_interval_on_sample_draws(
        self, sample_draws: list[tuple[list[int], int, int, str]]
    ) -> None:
        value = numerical_attraction(sample_draws)
        assert 0.0 <= value <= 1.0


class TestBuildAttractionProfile:
    def test_injected_pair_in_every_draw_has_weight_one(self) -> None:
        # (7, 8) appears in every draw; all other pairs have gap > 2.
        draws = [[7, 8, 15, 22, 30, 38]] * 10
        profile = build_attraction_profile(draws, last_n=30)

        assert profile[(7, 8)] == 1.0

    def test_pairs_with_gap_over_two_are_absent(self) -> None:
        draws = [[7, 8, 15, 22, 30, 38]] * 10
        profile = build_attraction_profile(draws, last_n=30)

        for a, b in profile:
            assert 1 <= b - a <= 2
        # Spot-check a wide pair that occurs in every draw.
        assert (8, 15) not in profile
        assert (7, 22) not in profile

    def test_weights_normalised_to_unit_interval(self) -> None:
        draws = [[7, 8, 15, 22, 30, 38]] * 10 + [[7, 8, 9, 20, 28, 36]] * 5
        profile = build_attraction_profile(draws, last_n=30)

        assert profile
        assert all(0.0 < w <= 1.0 for w in profile.values())
        # (7, 8) is in all 15 draws; (8, 9) only in 5 -> lower weight.
        assert profile[(7, 8)] == 1.0
        assert profile[(8, 9)] < 1.0

    def test_no_close_pairs_returns_empty_profile(self) -> None:
        draws = [[1, 10, 20, 30, 35, 40]] * 10
        assert build_attraction_profile(draws, last_n=30) == {}

    def test_takes_plain_lists_not_tuples(self) -> None:
        # API contract: plain lists of numbers, not 4-tuples.
        draws = [[3, 4, 10, 20, 30, 40]]
        profile = build_attraction_profile(draws)
        assert profile == {(3, 4): 1.0}


def _hot_cold_draws(n_draws: int = 30) -> list[list[int]]:
    """Draws built only from numbers 1-13 (hot), leaving 14-40 undrawn.

    Each draw is 6 distinct numbers cycling through 1-13, so every hot
    number appears in roughly a third of the draws.
    """
    return [[((i * 6 + j) % 13) + 1 for j in range(6)] for i in range(n_draws)]


class TestClassifyPosNeg:
    def test_hot_numbers_classified_positive_cold_negative(self) -> None:
        result = classify_pos_neg(_hot_cold_draws(), pool_size=40, window=30)

        # With 14-40 all at zero frequency, the tie-break on number puts
        # 28-40 at the bottom. The split is exact:
        assert result["positive"] == list(range(1, 14))
        assert result["negative"] == list(range(28, 41))
        assert result["neutral"] == list(range(14, 28))

    def test_groups_partition_pool_exactly(self) -> None:
        result = classify_pos_neg(_hot_cold_draws(), pool_size=40, window=30)

        assert len(result["positive"]) == 13
        assert len(result["negative"]) == 13
        assert len(result["neutral"]) == 14
        combined = result["positive"] + result["neutral"] + result["negative"]
        assert sorted(combined) == list(range(1, 41))
        assert len(set(combined)) == 40

    def test_deterministic_tie_breaking(self) -> None:
        draws = _hot_cold_draws()
        first = classify_pos_neg(draws, pool_size=40, window=30)
        second = classify_pos_neg(draws, pool_size=40, window=30)
        assert first == second

        # All frequencies tied (no draws at all): ranking falls back to
        # ascending number order.
        tied = classify_pos_neg([], pool_size=40, window=30)
        assert tied["positive"] == list(range(1, 14))
        assert tied["negative"] == list(range(28, 41))
        assert tied["neutral"] == list(range(14, 28))

    def test_result_shape_on_sample_draws(
        self, sample_draws: list[tuple[list[int], int, int, str]]
    ) -> None:
        plain_draws = [list(nums) for nums, _, _, _ in sample_draws]
        result = classify_pos_neg(plain_draws, pool_size=40, window=30)

        assert set(result) == {"positive", "negative", "neutral"}
        combined = sorted(result["positive"] + result["neutral"] + result["negative"])
        assert combined == list(range(1, 41))
