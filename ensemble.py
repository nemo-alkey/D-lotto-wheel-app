#!/usr/bin/env python3
"""
ensemble.py — Dynamic ensemble predictor fusing Bayesian, Markov, and Albert methods.

Walks forward over recent draws to compute each sub-predictor's accuracy
(Brier score), then assigns softmax-normalised weights.  The ensemble
prediction is a weighted average of sub-predictor probabilities for each
number (1-40 for mains, 1-40 for bonus, 1-10 for Powerball).

Requires a sqlite3.Connection to a 'draws' table.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable
from typing import Any


class EnsemblePredictor:
    """Dynamic ensemble predictor with walk-forward weight calibration.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to lotto.db.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

        # Load draws as list of (nums, pb, bonus, date)
        self.draws = self._load_draws()

        # Sub-predictor names
        self.method_names = ["frequency", "bayesian", "markov", "due_numbers"]

        # Current weights (initialised uniformly)
        self.weights: dict[str, float] = {
            name: 1.0 / len(self.method_names) for name in self.method_names
        }

        # Weight history for plotting
        self.weight_history: list[dict[str, float]] = []

    # ------------------------------------------------------------------
    def _load_draws(self) -> list[tuple[list[int], int, int, str]]:
        """Load draws from the database."""
        cursor = self.conn.execute(
            "SELECT numbers, powerball, bonus, draw_date " "FROM draws ORDER BY draw_date ASC"
        )
        draws = []
        for nums_str, pb, bonus, date in cursor:
            try:
                nums = [int(x.strip()) for x in nums_str.split(",")]
            except (ValueError, AttributeError):
                continue
            if len(nums) == 6:
                draws.append((nums, pb, bonus or 0, date))
        cursor.close()
        return draws

    # ------------------------------------------------------------------
    def _brier_score(self, probs: dict[int, float], actual: list[int]) -> float:
        """Compute Brier score: mean((p_i - y_i)^2) for numbers 1-40."""
        y = {n: 1.0 if n in actual else 0.0 for n in range(1, 41)}
        total = 0.0
        for n in range(1, 41):
            diff = probs.get(n, 0.0) - y[n]
            total += diff * diff
        return total / 40.0

    # ------------------------------------------------------------------
    def _sub_predictor_prob(
        self, method: str, train_draws: list[tuple[list[int], int, int, str]]
    ) -> dict[int, float]:
        """Return probability dict {number: prob} for a sub-predictor."""
        from predictions import bayesian, due_numbers, frequency, markov

        fn_map: dict[str, Callable[..., Any]] = {
            "frequency": frequency,
            "bayesian": bayesian,
            "markov": markov,
            "due_numbers": due_numbers,
        }
        fn = fn_map[method]

        # We only care about main-number probabilities here
        # Each method returns {"numbers": [6 ints], "powerball": int}
        # For Brier score we need per-number probabilities.
        # Convert top-6 picks to a probability distribution.
        result = fn(train_draws)
        top6 = set(result["numbers"])

        # Crude probability: top-6 share 0.6 probability mass, rest share 0.4
        probs: dict[int, float] = {}
        top_prob = 0.6 / 6.0
        other_prob = 0.4 / 34.0
        for n in range(1, 41):
            probs[n] = top_prob if n in top6 else other_prob
        return probs

    # ------------------------------------------------------------------
    def fit_weights(self, validation_draws: int = 10) -> None:
        """Walk-forward validation to calibrate sub-predictor weights.

        For each of the last `validation_draws` draws, trains each
        sub-predictor on all preceding draws, computes the Brier score on
        the actual outcome, then assigns weights proportional to the
        inverse Brier score (softmax-normalised).

        Parameters
        ----------
        validation_draws : int
            Number of most-recent draws to use for validation (default 10).
        """
        n = len(self.draws)
        if n <= validation_draws + 10:
            return  # not enough data

        self.weight_history = []
        brier_sums = {name: 0.0 for name in self.method_names}

        for i in range(n - validation_draws, n):
            train = self.draws[:i]
            actual_nums, _, _, _ = self.draws[i]

            step_weights = {}
            step_briers = {}
            for method in self.method_names:
                probs = self._sub_predictor_prob(method, train)
                brier = self._brier_score(probs, actual_nums)
                step_briers[method] = brier
                brier_sums[method] += brier

            # Softmax over inverse Brier (lower Brier = higher weight)
            inv_briers = {m: 1.0 / max(b, 1e-6) for m, b in step_briers.items()}
            total_inv = sum(inv_briers.values())
            if total_inv > 0:
                for m in self.method_names:
                    step_weights[m] = round(inv_briers[m] / total_inv, 4)
            else:
                for m in self.method_names:
                    step_weights[m] = 1.0 / len(self.method_names)

            self.weight_history.append(dict(step_weights))

        # Final weights: softmax over accumulated inverse Brier
        inv_total = 0.0
        inv_map = {}
        for m in self.method_names:
            inv = 1.0 / max(brier_sums[m], 1e-6)
            inv_map[m] = inv
            inv_total += inv
        if inv_total > 0:
            for m in self.method_names:
                self.weights[m] = round(inv_map[m] / inv_total, 4)
        else:
            for m in self.method_names:
                self.weights[m] = 1.0 / len(self.method_names)

    # ------------------------------------------------------------------
    def predict_main_numbers(self, top_n: int = 15) -> list[tuple[int, float]]:
        """Return top-n main numbers with ensemble probabilities.

        Returns
        -------
        list[tuple[int, float]]
            Sorted descending: [(number, ensemble_prob), ...]
        """
        # Weighted average of per-number probabilities from each method
        all_probs: dict[str, dict[int, float]] = {}
        for method in self.method_names:
            all_probs[method] = self._sub_predictor_prob(method, self.draws)

        ensemble: dict[int, float] = {}
        for n in range(1, 41):
            total = 0.0
            for method in self.method_names:
                total += self.weights[method] * all_probs[method].get(n, 0.0)
            ensemble[n] = total

        ranked = sorted(ensemble.items(), key=lambda x: x[1], reverse=True)
        return [(n, round(prob, 6)) for n, prob in ranked[:top_n]]

    # ------------------------------------------------------------------
    def predict_all(
        self, main_top: int = 15, bonus_top: int = 5, pb_top: int = 3
    ) -> dict[str, Any]:
        """Return ensemble predictions for mains, bonus, and Powerball.

        Parameters
        ----------
        main_top : int
            Number of top main numbers to return (default 15).
        bonus_top : int
            Number of top bonus numbers to return (default 5).
        pb_top : int
            Number of top Powerball numbers to return (default 3).

        Returns
        -------
        dict
            Keys: main, bonus, powerball, ensemble_weights.
        """
        # Main numbers: ensemble weighted average
        main = self.predict_main_numbers(top_n=main_top)

        # Bonus: HierarchicalBonusPredictor
        bonus = []
        bonus_draws = [(d, b) for _, _, b, d in self.draws if b and 1 <= b <= 40]
        if bonus_draws:
            from predictions import HierarchicalBonusPredictor

            hbp = HierarchicalBonusPredictor(bonus_draws, recency_halflife_days=90)
            hbp.fit()  # type: ignore[no-untyped-call]  # predictions.py is untyped
            top_b = hbp.predict_top_k(k=bonus_top)
            bonus = [(n, round(p, 6)) for n, p, _ in top_b]

        # Powerball: frequency-based
        pb_counts: Counter[int] = Counter()
        for _, pb, _, _ in self.draws:
            if 1 <= pb <= 10:
                pb_counts[pb] += 1
        total_pb = sum(pb_counts.values()) or 1
        pb_probs = {p: pb_counts.get(p, 0) / total_pb for p in range(1, 11)}
        pb_ranked = sorted(pb_probs.items(), key=lambda x: x[1], reverse=True)
        powerball = [(p, round(prob, 6)) for p, prob in pb_ranked[:pb_top]]

        return {
            "main": main,
            "bonus": bonus,
            "powerball": powerball,
            "ensemble_weights": self.weights,
        }
