#!/usr/bin/env python3
"""
predictions.py — 7 prediction methods for NZ Lotto Powerball (6/40 + PB 1-10).

Each method accepts a list of draws in the format returned by
lotto_wheels.load_draws():  [(numbers_list, powerball, draw_date), ...]

Each method returns a dict:
    {"numbers": [6 ints], "powerball": int}

The ensemble() function combines all methods with configurable weights.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, TypeAlias, TypedDict, cast

if TYPE_CHECKING:
    import sqlite3

    import numpy as np
    from xgboost import XGBClassifier

# Draw record: (main_numbers, powerball, bonus, draw_date)
Draw: TypeAlias = tuple[list[int], int, int, str]


class Prediction(TypedDict):
    numbers: list[int]
    powerball: int


# ---------------------------------------------------------------------------
# 1. Frequency — top-6 most drawn numbers + most common PB
# ---------------------------------------------------------------------------


def frequency(draws: list[Draw]) -> Prediction:
    """Global frequency: pick the 6 most common main numbers and the most
    common Powerball across *all* historical draws."""
    main_counts: Counter[int] = Counter()
    pb_counts: Counter[int] = Counter()
    for nums, pb, _, _ in draws:
        main_counts.update(nums)
        pb_counts[pb] += 1

    top_nums = [n for n, _ in main_counts.most_common(6)]
    top_pb = pb_counts.most_common(1)[0][0]

    return {"numbers": sorted(top_nums), "powerball": top_pb}


# ---------------------------------------------------------------------------
# 2. Bayesian — Dirichlet-Multinomial posterior (alpha=1.0)
# ---------------------------------------------------------------------------


def bayesian(draws: list[Draw], alpha: float = 1.0) -> Prediction:
    """Dirichlet-Multinomial posterior mean for main numbers and Powerball.

    Posterior = (count_i + alpha) / (total + N * alpha)
    Picks the 6 main numbers and 1 PB with the highest posterior.
    """
    main_counts: Counter[int] = Counter()
    pb_counts: Counter[int] = Counter()
    for nums, pb, _, _ in draws:
        main_counts.update(nums)
        pb_counts[pb] += 1

    total_main = sum(main_counts.values())
    total_pb = sum(pb_counts.values())

    main_posterior = {
        n: (main_counts.get(n, 0) + alpha) / (total_main + 40 * alpha) for n in range(1, 41)
    }
    pb_posterior = {
        p: (pb_counts.get(p, 0) + alpha) / (total_pb + 10 * alpha) for p in range(1, 11)
    }

    top_nums = sorted(main_posterior, key=lambda n: main_posterior[n], reverse=True)[:6]
    top_pb = max(pb_posterior, key=lambda p: pb_posterior[p])

    return {"numbers": sorted(top_nums), "powerball": top_pb}


# ---------------------------------------------------------------------------
# 3. Markov — number-to-number transition matrix
# ---------------------------------------------------------------------------


def markov(draws: list[Draw]) -> Prediction:
    """Build a 40×40 transition matrix from consecutive draw pairs.
    Given the last draw's numbers, pick the 6 numbers with the highest
    cumulative transition probability from those numbers.
    Powerball: similar 10×10 transition matrix.
    """
    if len(draws) < 2:
        return frequency(draws)

    # Main numbers
    trans = [[0.0] * 40 for _ in range(40)]
    for i in range(1, len(draws)):
        prev_nums = draws[i - 1][0]
        curr_nums = draws[i][0]
        for a in prev_nums:
            for b in curr_nums:
                trans[a - 1][b - 1] += 1.0

    # Normalize rows
    for row in trans:
        s = sum(row)
        if s > 0:
            for j in range(40):
                row[j] /= s

    # Score from the last draw's numbers
    last_nums = draws[-1][0]
    scores = [0.0] * 40
    for a in last_nums:
        for b in range(40):
            scores[b] += trans[a - 1][b]

    # Sort descending and pick top 6
    ranked = sorted(range(1, 41), key=lambda n: scores[n - 1], reverse=True)
    top_nums = sorted(ranked[:6])

    # Powerball Markov
    pb_trans = [[0.0] * 10 for _ in range(10)]
    for i in range(1, len(draws)):
        prev_pb = draws[i - 1][1]
        curr_pb = draws[i][1]
        pb_trans[prev_pb - 1][curr_pb - 1] += 1.0

    for row in pb_trans:
        s = sum(row)
        if s > 0:
            for j in range(10):
                row[j] /= s

    last_pb = draws[-1][1]
    pb_scores = pb_trans[last_pb - 1]
    top_pb = max(range(1, 11), key=lambda p: pb_scores[p - 1])

    return {"numbers": top_nums, "powerball": top_pb}


# ---------------------------------------------------------------------------
# 4. Weighted Random — recency-weighted Thompson sampling
# ---------------------------------------------------------------------------


def weighted_random(draws: list[Draw]) -> Prediction:
    """Recency-weighted random sampling: last 20% of draws get 2× weight.

    Samples 6 numbers without replacement using weighted probabilities,
    then picks the most likely Powerball under the same weighting.
    """
    n = len(draws)
    split = max(1, n // 5)  # last 20%

    main_counts: Counter[int] = Counter()
    pb_counts: Counter[int] = Counter()

    for i, (nums, pb, _, _) in enumerate(draws):
        weight = 2.0 if i >= n - split else 1.0
        for x in nums:
            main_counts[x] += weight  # type: ignore[assignment]  # Counter stores float weights
        pb_counts[pb] += weight  # type: ignore[assignment]  # Counter stores float weights

    # Weighted probabilities
    total_main = sum(main_counts.values()) or 1
    main_probs = [main_counts.get(n, 0) / total_main for n in range(1, 41)]

    total_pb = sum(pb_counts.values()) or 1
    pb_probs = [pb_counts.get(p, 0) / total_pb for p in range(1, 11)]

    # Weighted random sample without replacement
    rng = random.Random()
    pool = list(range(1, 41))
    w = list(main_probs)
    candidates = []
    for _ in range(6):
        total = sum(w)
        r = rng.random() * total
        cumulative = 0.0
        for i in range(len(pool)):
            cumulative += w[i]
            if r <= cumulative:
                candidates.append(pool[i])
                pool.pop(i)
                w.pop(i)
                break
    top_nums = sorted(candidates)
    top_pb = max(range(1, 11), key=lambda p: pb_probs[p - 1])

    return {"numbers": top_nums, "powerball": top_pb}


# ---------------------------------------------------------------------------
# 5. Due Numbers — highest gap z-score (haven't appeared in the longest)
# ---------------------------------------------------------------------------


def due_numbers(draws: list[Draw]) -> Prediction:
    """Numbers with the largest gap since their last appearance.

    Gap = number of draws since the number last appeared.
    Combine gap z-score and frequency z-score to find "due" numbers.
    Powerball version: same but across PB values.
    """
    n_draws = len(draws)

    # Last appearance index for each number
    last_main = {n: -1 for n in range(1, 41)}
    last_pb = {p: -1 for p in range(1, 11)}
    # Frequency count
    main_count: Counter[int] = Counter()
    pb_count: Counter[int] = Counter()

    for idx, (nums, pb, _, _) in enumerate(draws):
        for n in nums:
            last_main[n] = idx
            main_count[n] += 1
        last_pb[pb] = idx
        pb_count[pb] += 1

    # Gap = draws since last appearance
    gaps_main = {n: n_draws - last_main[n] - 1 for n in range(1, 41)}
    gaps_pb = {p: n_draws - last_pb[p] - 1 for p in range(1, 11)}

    # Z-score normalisation for gap
    def z_scores(values: Mapping[int, float]) -> dict[int, float]:
        vals = list(values.values())
        mean = sum(vals) / len(vals)
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) or 1.0
        return {k: (v - mean) / std for k, v in values.items()}

    z_gap_main = z_scores(gaps_main)
    z_gap_pb = z_scores(gaps_pb)

    # Frequency z-score (negative = less frequent = more due)
    z_freq_main = z_scores({n: -main_count.get(n, 0) for n in range(1, 41)})
    z_freq_pb = z_scores({p: -pb_count.get(p, 0) for p in range(1, 11)})

    # Combined score: high gap + low frequency = due
    score_main = {n: z_gap_main[n] + z_freq_main[n] for n in range(1, 41)}
    score_pb = {p: z_gap_pb[p] + z_freq_pb[p] for p in range(1, 11)}

    top_nums = sorted(score_main, key=lambda n: score_main[n], reverse=True)[:6]
    top_pb = max(score_pb, key=lambda p: score_pb[p])

    return {"numbers": sorted(top_nums), "powerball": top_pb}


# ---------------------------------------------------------------------------
# 6. Pattern — odd/even + low/high extrapolation from last 10 draws
# ---------------------------------------------------------------------------


def pattern(draws: list[Draw]) -> Prediction:
    """Analyse the last 10 draws for odd/even and low(1-20)/high(21-40)
    patterns, then extrapolate a ticket that fits the most common pattern.
    """
    recent = draws[-10:] if len(draws) >= 10 else draws

    # Count odd/even per draw
    odd_counts = []
    low_counts = []
    pb_occurrences: Counter[int] = Counter()

    for nums, pb, _, _ in recent:
        odd_counts.append(sum(1 for n in nums if n % 2 == 1))
        low_counts.append(sum(1 for n in nums if n <= 20))
        pb_occurrences[pb] += 1

    # Most common odd/even and low/high pattern
    target_odd = Counter(odd_counts).most_common(1)[0][0]
    target_low = Counter(low_counts).most_common(1)[0][0]
    target_high = 6 - target_low
    target_even = 6 - target_odd

    # Available pools
    odd_nums = [n for n in range(1, 41) if n % 2 == 1]
    even_nums = [n for n in range(1, 41) if n % 2 == 0]
    low_nums = list(range(1, 21))
    high_nums = list(range(21, 41))

    # Prefer numbers that have appeared recently within each pool
    recent_set: set[int] = set()
    for nums, _, _, _ in recent:
        recent_set.update(nums)

    def pick_from_pool(pool: list[int], count: int, prefer_recent: bool = True) -> list[int]:
        if count <= 0:
            return []
        if prefer_recent:
            recent_in_pool = [n for n in pool if n in recent_set]
            others = [n for n in pool if n not in recent_set]
            rng = random.Random()
            if len(recent_in_pool) >= count:
                return rng.sample(recent_in_pool, count)
            return recent_in_pool + rng.sample(others, count - len(recent_in_pool))
        rng = random.Random()
        return rng.sample(pool, count)

    # Build ticket matching the pattern
    # Start with odd/even split, then filter by low/high
    odd_pool_low = sorted(set(odd_nums) & set(low_nums))
    odd_pool_high = sorted(set(odd_nums) & set(high_nums))
    even_pool_low = sorted(set(even_nums) & set(low_nums))
    even_pool_high = sorted(set(even_nums) & set(high_nums))

    candidates = []
    # We need: target_odd odds, target_even evens
    # Of those: target_low low, target_high high
    # So: odd_low + odd_high = target_odd, even_low + even_high = target_even
    # And: odd_low + even_low = target_low, odd_high + even_high = target_high

    for odd_low_cnt in range(
        max(0, target_odd - len(odd_pool_high)), min(target_odd, len(odd_pool_low)) + 1
    ):
        odd_high_cnt = target_odd - odd_low_cnt
        even_low_cnt = target_low - odd_low_cnt
        even_high_cnt = target_high - odd_high_cnt

        if odd_high_cnt < 0 or even_low_cnt < 0 or even_high_cnt < 0:
            continue
        if (
            odd_high_cnt > len(odd_pool_high)
            or even_low_cnt > len(even_pool_low)
            or even_high_cnt > len(even_pool_high)
        ):
            continue

        try:
            chosen = (
                pick_from_pool(odd_pool_low, odd_low_cnt)
                + pick_from_pool(odd_pool_high, odd_high_cnt)
                + pick_from_pool(even_pool_low, even_low_cnt)
                + pick_from_pool(even_pool_high, even_high_cnt)
            )
            if len(chosen) == 6:
                candidates.append(chosen)
        except ValueError:
            continue

    if candidates:
        rng = random.Random()
        chosen = rng.choice(candidates)
    else:
        # Fallback: just pick any numbers matching odd/even and low/high
        chosen = pick_from_pool(odd_nums, target_odd) + pick_from_pool(even_nums, target_even)

    # PB: most common in recent draws
    top_pb = pb_occurrences.most_common(1)[0][0]

    return {"numbers": sorted(chosen), "powerball": top_pb}


# ---------------------------------------------------------------------------
# 7. Ensemble — weighted vote across all methods
# ---------------------------------------------------------------------------


def ensemble(
    draws: list[Draw],
    weights: list[float] | None = None,
) -> Prediction:
    """Combine all 6 methods (self excluded) using weighted voting.

    Each method contributes its top 6 numbers and top Powerball.
    Numbers are scored by their *rank* within each method (6 pts for #1,
    5 pts for #2, …, 1 pt for #6) multiplied by the method's weight.
    Powerball is simple majority vote (each method's top PB gets its weight).
    """
    methods: list[Callable[[list[Draw]], Prediction]] = [
        frequency,
        bayesian,
        markov,
        weighted_random,
        due_numbers,
        pattern,
    ]

    if weights is None:
        weights = [1.0] * len(methods)

    # Sanity: if weights don't match, default to equal
    if len(weights) != len(methods):
        weights = [1.0] * len(methods)

    main_scores: dict[int, float] = {n: 0.0 for n in range(1, 41)}
    pb_scores: dict[int, float] = {p: 0.0 for p in range(1, 11)}

    for method, w in zip(methods, weights, strict=False):
        result = method(draws)

        # Top 6 main numbers: 6 pts for #1 down to 1 pt for #6
        for rank, n in enumerate(result["numbers"]):
            main_scores[n] += w * (6 - rank)

        # Powerball: weight goes entirely to the predicted PB
        pb_scores[result["powerball"]] += w

    top_nums = sorted(main_scores, key=lambda n: main_scores[n], reverse=True)[:6]
    top_pb = max(pb_scores, key=lambda p: pb_scores[p])

    return {"numbers": sorted(top_nums), "powerball": top_pb}


# ---------------------------------------------------------------------------
# Bonus Ball Prediction Methods
# ---------------------------------------------------------------------------


class BonusBayesian:
    """Dirichlet-Multinomial posterior for bonus balls (1-40).

    Uses a symmetric Dirichlet prior with alpha=1.0 for each bonus number.
    Posterior = (count_i + alpha) / (total_observations + 40 * alpha).

    Parameters
    ----------
    bonus_balls : list[int]
        Historical bonus ball values (each 1-40).
    alpha : float
        Dirichlet prior concentration (default 1.0).
    """

    def __init__(self, bonus_balls: list[int], alpha: float = 1.0) -> None:
        self.counts: Counter[int] = Counter()
        for b in bonus_balls:
            if 1 <= b <= 40:
                self.counts[b] += 1
        self.total = sum(self.counts.values())
        self.alpha = alpha
        self.posterior: dict[int, float] = {}
        denom = self.total + 40 * alpha
        for n in range(1, 41):
            self.posterior[n] = (self.counts.get(n, 0) + alpha) / denom

    def predict_top_k(self, k: int = 5) -> list[tuple[int, float]]:
        """Return top-k bonus numbers with highest posterior probability.

        Returns
        -------
        list[tuple[int, float]]
            Sorted descending by probability: [(bonus_number, prob), ...]
        """
        ranked = sorted(self.posterior.items(), key=lambda x: x[1], reverse=True)
        return ranked[:k]


def bonus_gap_prediction(conn: sqlite3.Connection, k: int = 5) -> list[tuple[int, float]]:
    """Predict top-k "due" bonus numbers using combined gap + frequency z-scores.

    For each bonus ball (1-40):
      - gap = draws since last appearance
      - gap_zscore = (gap - mean_gap) / std_gap
      - frequency_zscore = (count - mean_count) / std_count
      - combined = 0.5 * gap_zscore + 0.5 * frequency_zscore

    Lower combined score → more "due". Returns the k lowest.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to a DB with a 'draws' table (columns: bonus, draw_id).
    k : int
        Number of top predictions to return (default 5).

    Returns
    -------
    list[tuple[int, float]]
        Sorted ascending by combined score: [(bonus_number, score), ...]
    """
    rows = conn.execute("SELECT bonus, draw_id FROM draws ORDER BY draw_id ASC").fetchall()
    max_id = conn.execute("SELECT MAX(draw_id) FROM draws").fetchone()[0] or 0

    counts: Counter[int] = Counter()
    last_seen: dict[int, int] = {}
    for bonus, draw_id in rows:
        counts[bonus] += 1
        last_seen[bonus] = draw_id

    def z_score(values_dict: Mapping[int, float]) -> dict[int, float]:
        vals = list(values_dict.values())
        mean = sum(vals) / len(vals)
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) or 1.0
        return {k: (v - mean) / std for k, v in values_dict.items()}

    gap_zs = z_score({n: max_id - last_seen.get(n, 0) for n in range(1, 41)})
    freq_zs = z_score({n: counts.get(n, 0) for n in range(1, 41)})

    combined = {n: 0.5 * gap_zs[n] + 0.5 * freq_zs[n] for n in range(1, 41)}
    ranked = sorted(combined.items(), key=lambda x: x[1])
    return [(n, round(s, 4)) for n, s in ranked[:k]]


# ---------------------------------------------------------------------------
# Hierarchical Bonus Bayesian Predictor
# ---------------------------------------------------------------------------


class HierarchicalBonusPredictor:
    """Hierarchical Dirichlet-Multinomial bonus-ball predictor with recency weighting.

    Combines empirical frequencies with a symmetric Dirichlet prior and an
    exponential recency decay so that recent draws have higher influence on
    the posterior.

    Parameters
    ----------
    draws : list[tuple[str, int]]
        List of (draw_date_iso_string, bonus_number) pairs, chronologically ordered.
    smoothing : float
        Dirichlet prior concentration per number (default 1.0).
    recency_halflife_days : int
        Half-life in days for exponential decay weighting (default 90).
    """

    def __init__(
        self,
        draws: list[tuple[Any, ...]],
        smoothing: float = 1.0,
        recency_halflife_days: int = 90,
    ) -> None:
        self.draws = draws
        self.smoothing = smoothing
        self.halflife = recency_halflife_days
        self.posterior_mean: dict[int, float] = {}
        self.posterior_std: dict[int, float] = {}

    # ------------------------------------------------------------------
    def fit(self) -> None:
        """Compute recency-weighted posterior means and Dirichlet std deviations."""
        from datetime import datetime

        if not self.draws:
            return

        # Parse dates and find the most recent draw date
        parsed = []
        for date_str, bonus in self.draws:
            if bonus is None or not (1 <= bonus <= 40):
                continue
            try:
                dt = datetime.fromisoformat(date_str[:10])
            except (ValueError, TypeError):
                continue
            parsed.append((dt, bonus))

        if not parsed:
            return

        latest_date = max(dt for dt, _ in parsed)
        halflife_days = float(self.halflife)

        # Accumulate weighted counts
        weighted_counts = [0.0] * 41  # 1-indexed
        total_weight = 0.0

        for dt, bonus in parsed:
            days_ago = max(0.0, (latest_date - dt).total_seconds() / 86400.0)
            weight = 2.0 ** (-days_ago / halflife_days)
            weighted_counts[bonus] += weight
            total_weight += weight

        # Posterior mean: Dirichlet-Multinomial
        alpha0 = total_weight + 40 * self.smoothing
        for n in range(1, 41):
            alpha_n = weighted_counts[n] + self.smoothing
            self.posterior_mean[n] = alpha_n / alpha0

        # Posterior std: Dirichlet variance
        # Var[theta_i] = alpha_i * (alpha_0 - alpha_i) / (alpha_0^2 * (alpha_0 + 1))
        for n in range(1, 41):
            alpha_n = weighted_counts[n] + self.smoothing
            if alpha0 > 0:
                var = alpha_n * (alpha0 - alpha_n) / (alpha0**2 * (alpha0 + 1))
                self.posterior_std[n] = math.sqrt(max(var, 0.0))
            else:
                self.posterior_std[n] = 0.0

    # ------------------------------------------------------------------
    def predict_top_k(self, k: int = 5) -> list[tuple[int, float, float]]:
        """Return top-k bonus numbers with posterior mean and std.

        Returns
        -------
        list[tuple[int, float, float]]
            Sorted descending by posterior mean: [(bonus_num, mean, std), ...]
        """
        if not self.posterior_mean:
            return []
        ranked = sorted(self.posterior_mean.items(), key=lambda x: x[1], reverse=True)
        return [
            (
                n,
                round(self.posterior_mean[n], 6),
                round(self.posterior_std.get(n, 0), 6),
            )
            for n, _ in ranked[:k]
        ]

    # ------------------------------------------------------------------
    def probability_of_number(self, bonus_num: int) -> float:
        """Return posterior probability for a specific bonus number (1-40)."""
        return round(self.posterior_mean.get(bonus_num, 0.0), 6)


# ===========================================================================
# XGBoost Predictor with SHAP explainability
# ===========================================================================


class XGBoostPredictor:
    """Gradient-boosted trees predictor for main numbers with SHAP interpretability.

    Features per number: lagged frequencies (1, 2, 3 draws ago), recency-weighted
    count, cold streak length.  Target: 1 if number appears in next draw, else 0.
    Uses walk-forward training over the last N draws.
    """

    def __init__(self, draws: list[Draw]) -> None:
        """
        Parameters
        ----------
        draws : list[tuple]
            Each tuple: ([n1..n6], powerball, bonus, draw_date).
        """
        self.draws = draws
        self.model: XGBClassifier | None = None
        self.feature_names = [
            "freq_last_1",
            "freq_last_3",
            "freq_last_5",
            "recency_days",
            "cold_streak",
            "rolling_avg_10",
        ]
        self.shap_values: dict[str, Any] | None = None
        self._explainer: Any = None  # cached SHAP TreeExplainer
        self._explainer_X: Any = None  # background data used for explainer

    def _build_features(self, draws_slice: list[Draw]) -> tuple[np.ndarray, np.ndarray]:
        """Build feature matrix X and target y from a slice of draws."""
        import numpy as np

        draw_dates = []
        draw_sets = []
        for nums, _, _, date in draws_slice:
            draw_sets.append(set(nums))
            draw_dates.append(date)

        n_draws = len(draw_sets)
        if n_draws < 6:
            return np.empty((0, len(self.feature_names))), np.empty(0)

        from datetime import datetime

        rows = []
        targets = []

        for i in range(5, n_draws):
            target_set = draw_sets[i]
            past_sets = draw_sets[max(0, i - 20) : i]
            past_dates = draw_dates[max(0, i - 20) : i]

            for num in range(1, 41):
                # Frequencies over windows
                freq1 = sum(1 for s in past_sets[-1:] if num in s)
                freq3 = sum(1 for s in past_sets[-3:] if num in s) if len(past_sets) >= 3 else 0
                freq5 = sum(1 for s in past_sets[-5:] if num in s) if len(past_sets) >= 5 else 0

                # Recency (days since last appearance)
                last_idx = None
                for j in range(len(past_sets) - 1, -1, -1):
                    if num in past_sets[j]:
                        last_idx = j
                        break
                if last_idx is not None:
                    try:
                        d_last = datetime.strptime(past_dates[last_idx], "%Y-%m-%d")
                        d_cur = datetime.strptime(draw_dates[i], "%Y-%m-%d")
                        recency = (d_cur - d_last).days
                    except (ValueError, IndexError):
                        recency = 30
                else:
                    recency = 30

                # Cold streak
                streak = 0
                for j in range(len(past_sets) - 1, -1, -1):
                    if num not in past_sets[j]:
                        streak += 1
                    else:
                        break

                # Rolling average over last 10
                if len(past_sets) >= 10:
                    avg = sum(1 for s in past_sets[-10:] if num in s) / 10
                else:
                    avg = 0

                rows.append([freq1, freq3, freq5, recency, streak, avg])
                targets.append(1 if num in target_set else 0)

        return np.array(rows, dtype=float), np.array(targets, dtype=int)

    def fit(self, window_draws: int = 200) -> XGBoostPredictor:
        """Train the XGBoost model on the most recent window_draws."""
        import numpy as np
        from xgboost import XGBClassifier

        if len(self.draws) < window_draws:
            window_draws = len(self.draws)

        recent = self.draws[-window_draws:]
        x, y = self._build_features(recent)

        if len(x) == 0:
            return self

        n_numbers = 40
        n_samples = len(x) // n_numbers
        # Ensure even split
        x = x[: n_samples * n_numbers]
        y = y[: n_samples * n_numbers]
        # Add number index as feature (cyclic encoding)
        num_idx = np.tile(np.arange(1, 41), n_samples).reshape(-1, 1) / 40.0
        x = np.hstack([x, num_idx])

        try:
            scale_pos_weight = (y == 0).sum() / max((y == 1).sum(), 1)
        except Exception:
            scale_pos_weight = 5

        self.model = XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.05,
            objective="binary:logistic",
            eval_metric="logloss",
            scale_pos_weight=scale_pos_weight,
            verbosity=0,
            random_state=42,
        )
        self.model.fit(x, y)
        return self

    def predict_probabilities(self) -> dict[int, float]:
        """Return probability for each number 1-40 for the next draw.

        Uses the most recent features.
        """
        import numpy as np

        if self.model is None:
            return {n: 0.025 for n in range(1, 41)}  # uniform baseline

        # Build features for the most recent state
        draw_sets = [set(d[0]) for d in self.draws]
        draw_dates = [d[3] for d in self.draws if len(d) > 3]
        if len(draw_dates) < 6:
            return {n: 0.025 for n in range(1, 41)}

        past_sets = draw_sets[-5:]
        probs = {}
        from datetime import datetime

        for num in range(1, 41):
            freq1 = sum(1 for s in past_sets[-1:] if num in s)
            freq3 = sum(1 for s in past_sets[-3:] if num in s)
            freq5 = sum(1 for s in past_sets[-5:] if num in s)
            recency = 30
            for j in range(len(draw_sets) - 1, -1, -1):
                if num in draw_sets[j]:
                    try:
                        d_last = datetime.strptime(
                            draw_dates[min(j, len(draw_dates) - 1)], "%Y-%m-%d"
                        )
                        d_cur = datetime.strptime(draw_dates[-1], "%Y-%m-%d")
                        recency = (d_cur - d_last).days
                    except (ValueError, IndexError):
                        pass
                    break
            streak = 0
            for j in range(len(draw_sets) - 1, -1, -1):
                if num not in draw_sets[j]:
                    streak += 1
                else:
                    break
            avg10 = sum(1 for s in draw_sets[-10:] if num in s) / min(10, len(draw_sets))

            feats = np.array(
                [[freq1, freq3, freq5, recency, streak, avg10, num / 40.0]], dtype=float
            )
            p = float(self.model.predict_proba(feats)[0][1])
            probs[num] = round(p, 6)

        return probs

    def predict_top_k(self, k: int = 15) -> list[tuple[int, float]]:
        """Return top-k predicted numbers with probabilities."""
        probs = self.predict_probabilities()
        ranked = sorted(probs.items(), key=lambda x: x[1], reverse=True)
        return ranked[:k]

    def explain_prediction(self) -> dict[str, Any]:
        """Compute SHAP values for feature importance.

        Returns dict with keys: mean_shap (per feature), top_features.
        """
        import numpy as np

        if self.model is None:
            return {"error": "Model not trained"}

        try:
            import shap

            # Use a subset of training data for background
            recent = self.draws[-200:]
            x, _ = self._build_features(recent)
            if len(x) == 0:
                return {"error": "Not enough data for SHAP"}

            # Limit to 500 samples for speed
            x_sample = x[: min(500, len(x))]
            # Add number index
            n_numbers = 40
            n_samples = len(x_sample) // n_numbers
            x_sample = x_sample[: n_samples * n_numbers]
            num_idx = np.tile(np.arange(1, 41), n_samples).reshape(-1, 1) / 40.0
            x_sample = np.hstack([x_sample, num_idx])

            all_features = self.feature_names + ["number_idx"]

            explainer = shap.TreeExplainer(self.model)
            shap_vals = explainer.shap_values(x_sample[:200])

            self.shap_values = {
                "values": shap_vals.tolist(),
                "features": all_features,
                "mean_abs": [float(abs(shap_vals[:, i]).mean()) for i in range(len(all_features))],
            }
            return self.shap_values
        except ImportError:
            return {"error": "shap package not installed"}
        except Exception as e:
            return {"error": str(e)}

    def _get_explainer(self) -> Any:
        """Return a cached SHAP TreeExplainer (builds once, reuses thereafter)."""
        import numpy as np
        import shap

        if self._explainer is not None:
            return self._explainer, self._explainer_X

        if self.model is None:
            raise ValueError("Model not trained")

        # Use a subset of training data for background
        recent = self.draws[-200:]
        x, _ = self._build_features(recent)
        if len(x) == 0:
            raise ValueError("Not enough data for SHAP")

        x_sample = x[: min(300, len(x))]
        n_numbers = 40
        n_samples = len(x_sample) // n_numbers
        x_sample = x_sample[: n_samples * n_numbers]
        num_idx = np.tile(np.arange(1, 41), n_samples).reshape(-1, 1) / 40.0
        x_sample = np.hstack([x_sample, num_idx])

        self._explainer = shap.TreeExplainer(self.model)
        self._explainer_X = x_sample[:200]
        return self._explainer, self._explainer_X

    def get_force_plot_html(self, number: int, base_value: float | None = None) -> str:
        """Generate an interactive SHAP force plot as HTML for a single number.

        Parameters
        ----------
        number : int
            The lotto number (1–40) to explain.
        base_value : float or None
            Expected model output.  If None, uses the explainer's expected_value.

        Returns
        -------
        str
            HTML string suitable for ``st.components.v1.html()``.
        """
        import numpy as np
        import shap

        if self.model is None:
            return "<p style='color:red'>Model not trained.</p>"

        try:
            explainer, bg_x = self._get_explainer()
        except (ValueError, ImportError) as e:
            return f"<p style='color:red'>SHAP unavailable: {e}</p>"

        # Build a single-row feature vector for `number`
        draw_sets = [set(d[0]) for d in self.draws]
        draw_dates = [d[3] for d in self.draws if len(d) > 3]
        if len(draw_dates) < 6:
            return "<p style='color:red'>Not enough draw data.</p>"

        past_sets = draw_sets[-5:]
        from datetime import datetime

        freq1 = sum(1 for s in past_sets[-1:] if number in s)
        freq3 = sum(1 for s in past_sets[-3:] if number in s)
        freq5 = sum(1 for s in past_sets[-5:] if number in s)
        recency = 30
        for j in range(len(draw_sets) - 1, -1, -1):
            if number in draw_sets[j]:
                try:
                    d_last = datetime.strptime(draw_dates[min(j, len(draw_dates) - 1)], "%Y-%m-%d")
                    d_cur = datetime.strptime(draw_dates[-1], "%Y-%m-%d")
                    recency = (d_cur - d_last).days
                except Exception:
                    pass
                break
        streak = 0
        for j in range(len(draw_sets) - 1, -1, -1):
            if number not in draw_sets[j]:
                streak += 1
            else:
                break
        avg10 = sum(1 for s in draw_sets[-10:] if number in s) / min(10, len(draw_sets))

        row = np.array(
            [[freq1, freq3, freq5, recency, streak, avg10, number / 40.0]],
            dtype=float,
        )

        all_features = self.feature_names + ["number_idx"]

        # Compute SHAP for this single row
        shap_vals = explainer.shap_values(row)

        if base_value is None:
            base_value = float(explainer.expected_value)

        # Generate force plot HTML
        force_vis = shap.plots.force(
            base_value=base_value,
            shap_values=shap_vals[0] if shap_vals.ndim > 1 else shap_vals,
            features=row[0],
            feature_names=all_features,
            matplotlib=False,
        )

        # shap.plots.force with matplotlib=False returns an object;
        # extract the HTML string via its _repr_html_() or html() method.
        if hasattr(force_vis, "html"):
            return cast(str, force_vis.html())
        elif hasattr(force_vis, "_repr_html_"):
            return cast(str, force_vis._repr_html_())
        else:
            # Fallback: wrap in a simple HTML container
            return f"<div>{force_vis}</div>"

    def save_shap_summary_plot(self, save_path: str = "data/plots/shap_summary.png") -> str | None:
        """Generate a SHAP summary plot (global feature importance) as PNG.

        Renders shap.summary_plot (beeswarm, matplotlib backend) over the
        explainer background sample and saves it to ``save_path``.

        Returns the saved path on success, or None if shap/matplotlib is
        unavailable or the model is not trained (failure is graceful — a
        message is printed instead of raising).
        """
        if self.model is None:
            print("SHAP summary plot skipped: model not trained.")
            return None

        try:
            import matplotlib

            matplotlib.use("Agg")  # headless backend
            import matplotlib.pyplot as plt
            import shap
        except ImportError as e:
            print(f"SHAP summary plot skipped: missing dependency ({e}).")
            return None

        try:
            explainer, bg_x = self._get_explainer()
        except (ValueError, ImportError) as e:
            print(f"SHAP summary plot skipped: {e}")
            return None

        shap_vals = explainer.shap_values(bg_x)
        all_features = self.feature_names + ["number_idx"]

        from pathlib import Path

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)

        shap.summary_plot(shap_vals, bg_x, feature_names=all_features, show=False)
        plt.savefig(save_path, bbox_inches="tight", dpi=120)
        plt.close()
        return save_path
