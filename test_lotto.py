"""Tests for core functions in lotto_wheels.py and rotation_scheduler.py."""

import csv
import io
import os
import sys
import tempfile
from collections import Counter
from unittest.mock import patch

import pytest

from lotto_wheels import (
    WHEELS,
    DIVISIONS,
    show_wheel,
    check_wheel,
    export_wheel,
    positive_negative_split,
    block_analysis,
    sum_range,
    numerical_attraction,
    bayesian_posterior,
    bandit_recommendation,
)
from rotation_scheduler import bayesian_posterior as rot_bayesian, build_rotation


# =========================================================================
# Wheel definitions
# =========================================================================

class TestWheels:
    def test_all_wheels_present(self):
        assert set(WHEELS.keys()) == {"single1", "single2", "double", "five-if-six", "jackpot7"}

    def test_each_wheel_has_tickets_and_pb(self):
        for name, (tickets, pb) in WHEELS.items():
            assert isinstance(tickets, list), f"{name}: tickets not a list"
            assert len(tickets) > 0, f"{name}: empty tickets"
            assert isinstance(pb, int) and 1 <= pb <= 10, f"{name}: invalid PB {pb}"
            for t in tickets:
                assert len(t) == 6, f"{name}: ticket has {len(t)} numbers"
                assert all(1 <= n <= 40 for n in t), f"{name}: number out of range"
                assert len(set(t)) == 6, f"{name}: duplicate in ticket"

    def test_jackpot7_is_full_wheel(self):
        tickets, pb = WHEELS["jackpot7"]
        pool = {9, 11, 12, 14, 38, 39, 40}
        expected = 7  # C(7,6) = 7
        assert len(tickets) == expected
        for t in tickets:
            assert set(t).issubset(pool)

    def test_ticket_counts(self):
        assert len(WHEELS["single1"][0]) == 20
        assert len(WHEELS["single2"][0]) == 20
        assert len(WHEELS["double"][0]) == 30
        assert len(WHEELS["five-if-six"][0]) == 22
        assert len(WHEELS["jackpot7"][0]) == 7


# =========================================================================
# Division constants
# =========================================================================

class TestDivisions:
    def test_seven_divisions(self):
        assert len(DIVISIONS) == 7

    def test_first_division_is_jackpot(self):
        label, main, pb, prize = DIVISIONS[0]
        assert "6+PB" in label
        assert main == 6
        assert pb is True
        assert prize == 1_000_000

    def test_last_division_is_div7(self):
        label, main, pb, prize = DIVISIONS[6]
        assert "3" in label
        assert main == 3
        assert pb is False
        assert prize == 20

    def test_divisions_ordered_highest_first(self):
        for i in range(len(DIVISIONS) - 1):
            main_i = DIVISIONS[i][1]
            main_next = DIVISIONS[i + 1][1]
            assert main_i >= main_next, f"Div {i} ({main_i}) < Div {i+1} ({main_next})"

    def test_all_prizes_positive(self):
        for label, _, _, prize in DIVISIONS:
            assert prize > 0, f"{label}: prize must be positive"


# =========================================================================
# check_wheel — division counting
# =========================================================================

class TestCheckWheel:
    def test_unknown_wheel_exits(self):
        with pytest.raises(SystemExit):
            check_wheel("nonexistent", "1,2,3,4,5,6", 3)

    def test_wrong_number_count_exits(self):
        with pytest.raises(SystemExit):
            check_wheel("double", "1,2,3,4,5", 3)

    def test_duplicate_numbers_exits(self):
        with patch.object(sys, "exit") as mock_exit:
            check_wheel("double", "1,2,3,4,5,5", 3)
            mock_exit.assert_called_once_with(1)

    def test_out_of_range_exits(self):
        with patch.object(sys, "exit") as mock_exit:
            check_wheel("double", "1,2,3,4,5,41", 3)
            mock_exit.assert_called_once_with(1)

    def test_bad_powerball_exits(self):
        with patch.object(sys, "exit") as mock_exit:
            check_wheel("double", "1,2,3,4,5,6", 11)
            mock_exit.assert_called_once_with(1)

    def test_jackpot7_full_match(self):
        """jackpot7 has all 7 pool numbers in the draw — every ticket matches 6."""
        with patch.object(sys, "exit") as mock_exit:
            with patch("sys.stdout", io.StringIO()):
                check_wheel("jackpot7", "9,11,12,14,38,39", 3)
            mock_exit.assert_not_called()

    def test_zero_overlap_returns_no_winners(self):
        """single2 pool is disjoint from this draw."""
        with patch("sys.stdout", io.StringIO()) as buf:
            check_wheel("single2", "1,4,6,20,21,22", 3)
        output = buf.getvalue()
        assert "Total prize:" in output
        assert "0.00" in output

    def test_division_highest_only(self):
        """A ticket with 6+PB should only count Div 1, not Div 2 or Div 5."""
        result = _score_tickets_against_draw("jackpot7", "9,11,12,14,38,39", 3)
        div1_count = result.get("Div 1 (6+PB)", 0)
        total_other = sum(v for k, v in result.items() if k != "Div 1 (6+PB)")
        # Only the ticket missing number 40 (not in the draw) matches all 6 draw numbers.
        # The other 6 tickets have 5 matches + PB hit → Div 2.
        assert div1_count == 1
        assert total_other == 6


# =========================================================================
# export_wheel
# =========================================================================

class TestExportWheel:
    def test_export_creates_csv(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            path = f.name
        try:
            with patch("sys.stdout", io.StringIO()), patch("builtins.input", return_value="y"):
                export_wheel("single1", path)
            with open(path) as f:
                reader = csv.reader(f)
                rows = list(reader)
            assert len(rows) == 21  # header + 20 tickets
            assert rows[0] == ["Main Numbers", "Powerball"]
            assert len(rows[1]) == 7  # 6 numbers + PB
        finally:
            os.unlink(path)

    def test_export_unknown_wheel_exits(self):
        with pytest.raises(SystemExit):
            export_wheel("ghost", "/tmp/ghost.csv")

    def test_export_without_name_exits(self):
        with pytest.raises(SystemExit):
            export_wheel("", "")


# =========================================================================
# show_wheel
# =========================================================================

class TestShowWheel:
    def test_show_unknown_prints_error(self):
        with patch("sys.stdout", io.StringIO()) as buf:
            show_wheel("ghost")
        assert "Unknown wheel" in buf.getvalue()

    def test_show_known_prints_tickets(self):
        with patch("sys.stdout", io.StringIO()) as buf:
            show_wheel("jackpot7")
        output = buf.getvalue()
        assert "Wheel: jackpot7" in output
        assert "Tickets: 7" in output
        assert "Powerball: 3" in output
        assert "$10.50" in output


# =========================================================================
# Statistical methods
# =========================================================================

class TestPositiveNegativeSplit:
    def test_empty_draws_returns_empty(self):
        pos, neg, freq = positive_negative_split([], last_n=30)
        assert pos == []
        assert neg == []

    def test_single_draw_all_same_freq(self):
        draws = [([1, 2, 3, 4, 5, 6], 3, "2024-01-01")]
        pos, neg, freq = positive_negative_split(draws, last_n=30)
        # All 6 numbers have freq=1, threshold=0.5, so all are positive
        assert 1 in pos
        assert 7 not in pos

    def test_many_draws(self):
        draws = [([1, 2, 3, 4, 5, 6], 3, f"2024-01-{d:02d}") for d in range(1, 31)]
        draws.extend([([7, 8, 9, 10, 11, 12], 3, f"2024-02-{d:02d}") for d in range(1, 31)])
        pos, neg, freq = positive_negative_split(draws, last_n=30)
        # Last 30 are all [7..12], so those are positive
        assert set(pos) == {7, 8, 9, 10, 11, 12}


class TestBlockAnalysis:
    def test_empty_draws(self):
        blocks = block_analysis([], last_n=30)
        assert len(blocks) == 6
        for i in range(6):
            assert blocks[i] == {"01-10": 0, "11-20": 0, "21-30": 0, "31-40": 0}

    def test_all_low_numbers(self):
        draws = [([1, 2, 3, 4, 5, 6], 3, "2024-01-01")]
        blocks = block_analysis(draws, last_n=30)
        assert blocks[0]["01-10"] == 1
        assert blocks[5]["01-10"] == 1

    def test_all_high_numbers(self):
        draws = [([31, 32, 33, 34, 35, 36], 3, "2024-01-01")]
        blocks = block_analysis(draws, last_n=30)
        assert blocks[0]["31-40"] == 1


class TestSumRange:
    def test_small_draws(self):
        draws = [([1, 2, 3, 4, 5, 6], 3, f"2024-01-{d:02d}") for d in range(1, 31)]
        low, high = sum_range(draws, last_n=30)
        assert low <= high

    def test_known_sum(self):
        draws = [([10, 20, 30, 31, 32, 33], 3, f"2024-01-{d:02d}") for d in range(1, 31)]
        low, high = sum_range(draws, last_n=30)
        assert low <= 156 <= high


class TestNumericalAttraction:
    def test_no_draws(self):
        result = numerical_attraction([], last_n=30)
        assert result == 0.0

    def test_all_adjacent(self):
        draws = [([1, 2, 3, 4, 5, 6], 3, "2024-01-01")]
        assert numerical_attraction(draws, last_n=1) == 1.0

    def test_none_adjacent(self):
        draws = [([1, 4, 7, 10, 13, 16], 3, "2024-01-01")]
        assert numerical_attraction(draws, last_n=1) == 0.0


class TestBayesianPosterior:
    def test_no_draws_uniform(self):
        posterior = bayesian_posterior([], alpha=1.0)
        for n in range(1, 41):
            expected = 1.0 / 40
            assert abs(posterior[n] - expected) < 1e-10

    def test_single_draw(self):
        draws = [([1, 2, 3, 4, 5, 6], 3, "2024-01-01")]
        posterior = bayesian_posterior(draws, alpha=1.0)
        assert posterior[1] > posterior[7]  # number that appeared has higher prob
        # (1 + 1) / (6 + 40) = 2/46, (0 + 1) / (6 + 40) = 1/46
        assert abs(posterior[1] - 2 / 46) < 1e-10
        assert abs(posterior[7] - 1 / 46) < 1e-10

    def test_all_numbers_seen_once(self):
        draws = [([n * 6 + i + 1 for i in range(6)], 3, f"2024-01-{n:02d}") for n in range(7)]
        posterior = bayesian_posterior(draws, alpha=1.0)
        # Number 1 appears 1 time (in draw 0). Total count = 7*6 = 42.
        # posterior[1] = (1 + 1) / (42 + 40) = 2/82
        assert abs(posterior[1] - 2 / 82) < 1e-10


class TestBanditRecommendation:
    def test_returns_6_numbers(self):
        draws = [([1, 2, 3, 4, 5, 6], 3, "2024-01-01")]
        result = bandit_recommendation(draws)
        assert len(result) == 6
        for n in result:
            assert 1 <= n <= 40

    def test_all_numbers_unique(self):
        draws = [([1, 2, 3, 4, 5, 6], 3, "2024-01-01")]
        result = bandit_recommendation(draws)
        assert len(set(result)) == 6


# =========================================================================
# rotation_scheduler
# =========================================================================

class TestRotationSchedulerBayesian:
    def test_posterior_same_as_lotto_wheels(self):
        """rot_bayesian and lotto_wheels.bayesian_posterior agree on same data."""
        draws = [([1, 2, 3, 4, 5, 6], 3, "2024-01-01")]
        r1 = rot_bayesian(draws, alpha=1.0)
        r2 = bayesian_posterior(draws, alpha=1.0)
        for n in range(1, 41):
            assert abs(r1[n] - r2[n]) < 1e-10

    def test_rotation_has_correct_length(self):
        posterior = {n: 1.0 / (n + 1) for n in range(1, 41)}
        schedule = build_rotation(posterior)
        assert len(schedule) == 6
        for week in schedule:
            assert len(week) == 11

    def test_rotation_changes_each_week(self):
        posterior = {n: 1.0 / n for n in range(1, 41)}
        schedule = build_rotation(posterior)
        for i in range(1, len(schedule)):
            assert set(schedule[i]) != set(schedule[i - 1]), f"Week {i+1} unchanged"

    def test_rotation_numbers_in_range(self):
        posterior = {n: 1.0 / n for n in range(1, 41)}
        schedule = build_rotation(posterior)
        for week in schedule:
            for n in week:
                assert 1 <= n <= 40

    def test_each_week_no_duplicates(self):
        posterior = {n: 1.0 for n in range(1, 41)}
        schedule = build_rotation(posterior)
        for week in schedule:
            assert len(set(week)) == 11


# =========================================================================
# Helper for division counting tests
# =========================================================================

def _score_tickets_against_draw(wheel_name, draw_str, pb):
    """Run check_wheel logic silently and return division counts."""
    from lotto_wheels import WHEELS, DIVISIONS
    nums = [int(x.strip()) for x in draw_str.split(",")]
    draw_set = set(nums)
    tickets, wheel_pb = WHEELS[wheel_name]
    counts = {d[0]: 0 for d in DIVISIONS}
    for ticket in tickets:
        matches = len(set(ticket) & draw_set)
        pb_hit = (wheel_pb == pb)
        for label, main_needed, pb_must_match, _ in DIVISIONS:
            if matches == main_needed and pb_hit == pb_must_match:
                counts[label] += 1
                break
    return counts
