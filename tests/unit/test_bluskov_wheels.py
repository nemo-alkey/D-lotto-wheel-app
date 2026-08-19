"""Unit tests for bluskov_wheel_library (verified System #88 + registry)."""

from __future__ import annotations

import itertools
from collections import Counter

import pytest

from bluskov_wheel_library import (
    DOUBLE_4IF4_10,
    DOUBLE_4IF4_11,
    DOUBLE_4IF4_12,
    SIX_4IF5_12,
    TRIPLE_4IF5_12,
    WHEEL_EXPLORER,
    WHEEL_REGISTRY,
    get_optimal_wheel,
    substitute_numbers,
    validate_balance,
)


class TestSystem88Structure:
    def test_exactly_30_tickets(self) -> None:
        assert len(DOUBLE_4IF4_10) == 30

    def test_each_ticket_has_6_unique_numbers_in_range(self) -> None:
        for ticket in DOUBLE_4IF4_10:
            assert len(ticket) == 6
            assert len(set(ticket)) == 6, f"duplicates in {ticket}"
            assert all(1 <= n <= 10 for n in ticket)

    def test_validate_balance_passes_with_full_pair_coverage(self) -> None:
        valid, stats = validate_balance(DOUBLE_4IF4_10, pool_size=10)

        assert valid is True
        assert stats["pair_coverage_pct"] == 100.0
        assert stats["total_pairs_covered"] == 45  # C(10,2)
        assert stats["tickets"] == 30

    def test_documented_balance_each_number_in_18_combinations(self) -> None:
        freq = Counter(n for ticket in DOUBLE_4IF4_10 for n in ticket)
        assert set(freq) == set(range(1, 11))
        for number in range(1, 11):
            assert freq[number] == 18, f"number {number} appears {freq[number]}x"


class TestSystem88Guarantee:
    def test_two_4wins_guarantee_brute_force(self) -> None:
        """Every 4-subset of 1..10 must appear in at least TWO tickets."""
        ticket_sets = [set(t) for t in DOUBLE_4IF4_10]
        failures = []
        for combo in itertools.combinations(range(1, 11), 4):
            hits = sum(1 for ts in ticket_sets if set(combo) <= ts)
            if hits < 2:
                failures.append((combo, hits))
        assert failures == [], f"guarantee violated: {failures[:5]}"

    def test_documented_pair_balance_10_combinations_each(self) -> None:
        pair_freq = Counter(
            pair for ticket in DOUBLE_4IF4_10 for pair in itertools.combinations(sorted(ticket), 2)
        )
        assert len(pair_freq) == 45
        for pair, count in pair_freq.items():
            assert count == 10, f"pair {pair} appears {count}x"


class TestSubstituteNumbers:
    def test_maps_generic_indices_onto_user_numbers(self) -> None:
        user = [3, 7, 12, 14, 18, 22, 29, 33, 40, 46]
        tickets = substitute_numbers(DOUBLE_4IF4_10, user)

        assert len(tickets) == 30
        # First generic ticket is [1, 2, 3, 4, 5, 10]
        assert tickets[0] == [3, 7, 12, 14, 18, 46]
        for original, mapped in zip(DOUBLE_4IF4_10, tickets, strict=False):
            assert mapped == [user[pos - 1] for pos in original]

    def test_wrong_length_user_list_raises(self) -> None:
        with pytest.raises(ValueError):
            substitute_numbers(DOUBLE_4IF4_10, [1, 2, 3])
        with pytest.raises(ValueError):
            substitute_numbers(DOUBLE_4IF4_10, list(range(1, 12)))

    def test_empty_wheel_raises(self) -> None:
        with pytest.raises(ValueError):
            substitute_numbers(DOUBLE_4IF4_11, list(range(1, 12)))


class TestGetOptimalWheel:
    def test_double_4if4_10_is_ready_system_88(self) -> None:
        entry = get_optimal_wheel("double-4-if-4", 10)
        assert entry["system_number"] == 88
        assert entry["ready"] is True
        assert entry["key"] == "double4_10"
        assert entry["wheel"] is DOUBLE_4IF4_10 or entry["wheel"] == DOUBLE_4IF4_10

    @pytest.mark.parametrize(
        "guarantee_type,pool_size,expected_wheel",
        [
            ("double-4-if-4", 11, DOUBLE_4IF4_11),
            ("double-4-if-4", 12, DOUBLE_4IF4_12),
            ("triple-4-if-5", 12, TRIPLE_4IF5_12),
            ("six-4-if-5", 12, SIX_4IF5_12),
        ],
    )
    def test_pending_systems_not_ready_with_empty_wheels(
        self, guarantee_type: str, pool_size: int, expected_wheel: list[list[int]]
    ) -> None:
        entry = get_optimal_wheel(guarantee_type, pool_size)
        assert entry["ready"] is False
        assert entry["wheel"] == []
        assert expected_wheel == []

    @pytest.mark.parametrize(
        "guarantee_type,pool_size",
        [
            ("double-4-if-4", 9),  # pool size not registered
            ("double-4-if-4", 13),
            ("4-if-4", 10),  # registered type, no systems yet
            ("nonsense", 10),  # unknown guarantee type
        ],
    )
    def test_unregistered_combos_raise_key_error(self, guarantee_type: str, pool_size: int) -> None:
        with pytest.raises(KeyError):
            get_optimal_wheel(guarantee_type, pool_size)


class TestWheelRegistryConsistency:
    def test_tickets_field_matches_wheel_length_when_non_empty(self) -> None:
        for key, entry in WHEEL_REGISTRY.items():
            wheel = entry["wheel"]
            if wheel:
                assert len(wheel) == entry["tickets"], (
                    f"{key}: tickets={entry['tickets']} but " f"len(wheel)={len(wheel)}"
                )

    def test_explorer_keys_exist_in_registry(self) -> None:
        for guarantee_type, sizes in WHEEL_EXPLORER.items():
            for pool_size, key in sizes.items():
                assert key in WHEEL_REGISTRY, (
                    f"WHEEL_EXPLORER[{guarantee_type!r}][{pool_size}] -> "
                    f"missing registry key {key!r}"
                )
