"""Unit tests for wheel_generator.generate_abbreviated_wheel."""

from __future__ import annotations

import itertools

import pytest

from wheel_generator import generate_abbreviated_wheel


def _ticket_sets(tickets):
    return [set(t) for t in tickets]


class TestValidGeneration:
    @pytest.mark.parametrize("pool_size", [8, 10, 12])
    def test_tickets_are_valid_six_number_combos(self, pool_size):
        pool = list(range(1, pool_size + 1))
        tickets, desc = generate_abbreviated_wheel(pool, "4 if 4")

        assert tickets, "expected a non-empty wheel"
        pool_set = set(pool)
        for ticket in tickets:
            assert len(ticket) == 6
            assert len(set(ticket)) == 6, f"duplicate numbers in {ticket}"
            assert set(ticket) <= pool_set
        # Greedy cover must not exceed the ticket cap
        assert len(tickets) <= 200

    def test_guarantee_description_returned(self):
        pool = list(range(1, 11))
        tickets, desc = generate_abbreviated_wheel(pool, "4 if 4")

        assert isinstance(desc, str)
        assert "4" in desc
        # Description reflects the actual pool size
        assert "10" in desc

    def test_4if4_covering_property_holds(self):
        """Every 4-subset of the pool must be contained in some ticket."""
        pool = list(range(1, 11))  # C(10,4) = 210 trigger combos
        tickets, desc = generate_abbreviated_wheel(pool, "4 if 4")

        assert (
            "covered" not in desc.lower()
        ), f"greedy cover should complete for a 10-number pool: {desc}"
        ticket_sets = _ticket_sets(tickets)
        uncovered = [
            combo
            for combo in itertools.combinations(pool, 4)
            if not any(set(combo) <= ts for ts in ticket_sets)
        ]
        assert uncovered == [], f"uncovered 4-subsets: {uncovered[:5]}"


class TestInputHandling:
    def test_duplicate_numbers_are_deduplicated(self):
        tickets, desc = generate_abbreviated_wheel([8, 3, 5, 3, 1, 8, 2, 4, 6, 7, 5], "4 if 4")
        # Effective pool is sorted(set(...)) == [1..8]
        assert tickets
        assert "8" in desc  # pool size 8 in description
        for ticket in tickets:
            assert set(ticket) <= set(range(1, 9))

    @pytest.mark.parametrize(
        "bad_guarantee",
        ["garbage", "", "4", "4 if four", "7 if 7", "4 if 3", "1 if 1"],
    )
    def test_invalid_guarantees_raise_value_error(self, bad_guarantee):
        with pytest.raises(ValueError):
            generate_abbreviated_wheel(list(range(1, 11)), bad_guarantee)

    def test_pool_smaller_than_trigger_returns_empty(self):
        tickets, desc = generate_abbreviated_wheel([1, 2, 3], "4 if 4")
        assert tickets == []
        assert isinstance(desc, str) and desc

    def test_pool_smaller_than_ticket_size_returns_empty(self):
        tickets, desc = generate_abbreviated_wheel([1, 2, 3, 4, 5], "4 if 4")
        assert tickets == []
        assert isinstance(desc, str) and desc


class TestSumRangeFilter:
    def test_sum_range_filters_candidate_tickets(self):
        pool = list(range(5, 15))  # 10 numbers, sums can span 39..75+
        tickets, desc = generate_abbreviated_wheel(pool, "4 if 4", sum_range=(45, 60))
        assert tickets
        for ticket in tickets:
            assert 45 <= sum(ticket) <= 60

    def test_impossible_sum_range_returns_empty(self):
        pool = list(range(1, 11))  # max possible sum is 5+6+7+8+9+10 = 45
        tickets, desc = generate_abbreviated_wheel(pool, "4 if 4", sum_range=(90, 180))
        assert tickets == []
        assert "sum" in desc.lower()


class TestExcludeNumbers:
    def test_exclude_numbers_strips_pool(self):
        pool = list(range(1, 11))
        tickets, desc = generate_abbreviated_wheel(pool, "4 if 4", exclude_numbers=[1, 2])
        assert tickets
        for ticket in tickets:
            assert 1 not in ticket
            assert 2 not in ticket
        # Remaining pool is 3..10 (8 numbers)
        assert "8" in desc


class TestFullWheel:
    def test_full_wheel_returns_all_combinations(self):
        pool = list(range(1, 8))  # C(7,6) = 7 <= max_tickets
        tickets, desc = generate_abbreviated_wheel(pool, "6 if 6")

        expected = set(itertools.combinations(pool, 6))
        assert len(tickets) == 7
        assert set(tickets) == expected

    def test_full_wheel_larger_pool(self):
        pool = list(range(1, 9))  # C(8,6) = 28
        tickets, _ = generate_abbreviated_wheel(pool, "6 if 6")
        assert len(tickets) == 28
        assert set(tickets) == set(itertools.combinations(pool, 6))

    def test_full_wheel_over_max_tickets_returns_empty(self):
        pool = list(range(1, 11))  # C(10,6) = 210 > 200
        tickets, desc = generate_abbreviated_wheel(pool, "6 if 6")
        assert tickets == []
        assert "210" in desc
