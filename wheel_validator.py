#!/usr/bin/env python3
"""
wheel_validator.py — Validate Bluskov wheel guarantees via Monte Carlo simulation.

For a given wheel (loaded from lotto_wheels.WHEELS), randomly draws sets of
6 numbers without replacement and checks whether the wheel's tickets satisfy
the claimed guarantee.  Also computes a pair-coverage matrix showing how
many tickets cover each pair of pool numbers.
"""

from __future__ import annotations

import numpy as np


class WheelValidator:
    """Monte Carlo validator for Bluskov wheel guarantees.

    Parameters
    ----------
    wheel : str
        Wheel name key in lotto_wheels.WHEELS.
    """

    def __init__(self, wheel: str):
        from lotto_wheels import WHEELS

        if wheel not in WHEELS:
            raise ValueError(f"Unknown wheel: '{wheel}'")
        self.name = wheel
        self.tickets, self.pb = WHEELS[wheel]
        self.pool: set[int] = set()
        for t in self.tickets:
            self.pool.update(t)
        self.pool_size = len(self.pool)
        self.pool_list = sorted(self.pool)

        # Determine the guarantee
        self._resolve_guarantee()

    # ------------------------------------------------------------------
    def _resolve_guarantee(self):
        """Infer the guarantee description and validation function."""
        if self.name == "jackpot7":
            self.claim = "6-if-6 (jackpot)"
            self._min_trigger = 6
            self._min_win = 6
            self._min_tickets = 1
        elif self.name == "five-if-six":
            self.claim = "5-if-6"
            self._min_trigger = 6
            self._min_win = 5
            self._min_tickets = 1
        elif self.name == "double":
            self.claim = "4-if-4 (double)"
            self._min_trigger = 4
            self._min_win = 4
            self._min_tickets = 2
        else:
            self.claim = "4-if-4"
            self._min_trigger = 4
            self._min_win = 4
            self._min_tickets = 1

    # ------------------------------------------------------------------
    def validate_guarantee(self, num_simulations: int = 10_000) -> dict:
        """Run Monte Carlo simulation to verify the wheel's guarantee.

        Randomly draws sets of 6 numbers from the pool, checks every ticket
        for matches, and verifies that the guarantee holds when the trigger
        condition is met.

        Parameters
        ----------
        num_simulations : int
            Number of random draws to simulate (default 10 000).

        Returns
        -------
        dict
            Keys: claimed_guarantee, passed, coverage_ratio,
            worst_case_match, simulations, trigger_count.
        """
        rng = np.random.default_rng()
        trigger_count = 0
        failures = 0
        worst_case = self._min_win  # worst-case best match seen

        for _ in range(num_simulations):
            # Draw trigger_match numbers from the pool
            draw = set(rng.choice(self.pool_list, size=self._min_trigger, replace=False))

            # Count tickets meeting the win threshold
            winning = 0
            best_matches = 0
            for ticket in self.tickets:
                matches = len(set(ticket) & draw)
                if matches >= self._min_win:
                    winning += 1
                if matches > best_matches:
                    best_matches = matches

            if winning < self._min_tickets:
                failures += 1
            if best_matches < worst_case:
                worst_case = best_matches
            trigger_count += 1  # every draw with trigger_match numbers counts

        coverage = (trigger_count - failures) / trigger_count if trigger_count > 0 else 0.0

        return {
            "claimed_guarantee": self.claim,
            "passed": failures == 0,
            "coverage_ratio": round(coverage, 4),
            "worst_case_match": worst_case,
            "simulations": num_simulations,
            "trigger_count": trigger_count,
        }

    # ------------------------------------------------------------------
    def coverage_matrix(self) -> np.ndarray:
        """Return a pair-coverage matrix for the wheel's pool.

        Cell [i][j] = number of tickets that include both pool numbers i and j.

        Returns
        -------
        np.ndarray
            (pool_size × pool_size) integer matrix, upper-triangular
            (diagonal = number of tickets containing that number).
        """
        n = self.pool_size
        matrix = np.zeros((n, n), dtype=int)

        for ticket in self.tickets:
            indices = [self.pool_list.index(num) for num in ticket if num in self.pool_list]
            for i in range(len(indices)):
                # Diagonal: ticket count per number
                matrix[indices[i], indices[i]] += 1
                for j in range(i + 1, len(indices)):
                    matrix[indices[i], indices[j]] += 1
                    matrix[indices[j], indices[i]] += 1

        return matrix
