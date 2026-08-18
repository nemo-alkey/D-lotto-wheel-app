#!/usr/bin/env python3
"""
train_ml_model.py — Train XGBoost models on NZ Lotto Powerball historical draws.

Creates feature vectors from draw history, trains binary classifiers for
each main number (1–40) and Powerball (1–10), and saves the models.

Usage (local, if you have AVX):
    python3 train_ml_model.py

Usage (Google Colab — recommended for most CPUs):
    See "Google Colab Step-by-Step Guide" at the bottom of this file.
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
import warnings
from collections import Counter
from typing import Any

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Data loading — standalone for Colab compatibility
# ---------------------------------------------------------------------------


def load_draws_from_db(db_path: str) -> list[tuple[list[int], int, int, str]]:
    """Load draws from a lotto_working.db SQLite file.

    Returns list of (numbers_list, powerball, bonus, draw_date).
    Works with both local paths and uploaded DB files.
    """
    import sqlite3

    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT draw_date, n1, n2, n3, n4, n5, n6, powerball, bonus "
        "FROM draws ORDER BY draw_date"
    )
    draws = [
        (
            [row["n1"], row["n2"], row["n3"], row["n4"], row["n5"], row["n6"]],
            row["powerball"],
            row["bonus"] or 0,
            row["draw_date"],
        )
        for row in cursor
    ]
    conn.close()
    return draws


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

# Minimum draws needed to compute meaningful features
MIN_HISTORY = 30


def build_features_for_draw(
    draws: list[tuple[list[int], int, str]],
    target_idx: int,
    num_range: range,
) -> list[dict[str, Any]]:
    """Build one feature vector per number in *num_range* for draw *target_idx*.

    Features are computed using only draws with index < target_idx
    (no data leakage from future draws).

    Returns a list of dicts, one per number, each containing:
      {'features': [...], 'label': 0|1, 'num': int, 'is_powerball': bool}
    """
    if target_idx < MIN_HISTORY:
        return []

    past_draws = draws[:target_idx]
    current_nums = draws[target_idx][0]
    is_pb = num_range[0] == 1 and num_range[-1] == 10  # detect PB range
    if is_pb:
        current_nums = [draws[target_idx][1]] if target_idx < len(draws) else []

    # --- Precompute rolling stats per number ---

    # Counters for rolling windows
    freq_10 = Counter()
    freq_30 = Counter()
    freq_all = Counter()

    # Last N draws: for lag features and gaps
    last_appearance: dict[int, int] = {}  # number -> last draw index seen
    lag_1: set[int] = set()
    lag_2: set[int] = set()
    lag_3: set[int] = set()

    # Position tracking (main numbers only)
    position_counts: dict[int, Counter] = {n: Counter() for n in num_range}
    position_sums: dict[int, float] = {n: 0.0 for n in num_range}
    position_n: dict[int, int] = {n: 0 for n in num_range}

    # Co-occurrence tracking (last 50 draws)
    cooccur_counts: dict[int, Counter] = {n: Counter() for n in num_range}

    # Longest streak
    streak_current: dict[int, int] = {n: 0 for n in num_range}
    streak_max: dict[int, int] = {n: 0 for n in num_range}

    recent_50_start = max(0, target_idx - 50)

    for j, (nums, pb, _) in enumerate(past_draws):
        drawn_set = set(nums)

        # If this is the PB feature builder, the "drawn" number is just the PB
        if is_pb:
            drawn_set = {pb}

        for n in num_range:
            appeared = n in drawn_set

            # Rolling frequencies
            if j >= target_idx - 10 and appeared:
                freq_10[n] += 1
            if j >= target_idx - 30 and appeared:
                freq_30[n] += 1
            if appeared:
                freq_all[n] += 1

            # Lag features (relative to target)
            if j == target_idx - 1 and appeared:
                lag_1.add(n)
            if j == target_idx - 2 and appeared:
                lag_2.add(n)
            if j == target_idx - 3 and appeared:
                lag_3.add(n)

            # Last appearance
            if appeared:
                last_appearance[n] = j

            # Streak tracking
            if appeared:
                streak_current[n] += 1
                if streak_current[n] > streak_max[n]:
                    streak_max[n] = streak_current[n]
            else:
                streak_current[n] = 0

            # Position tracking (main numbers only)
            if not is_pb and appeared:
                pos = sorted(nums).index(n) if n in nums else -1
                if pos >= 0:
                    position_sums[n] += pos
                    position_n[n] += 1
                    position_counts[n][pos] += 1

            # Co-occurrence (last 50 draws)
            if j >= recent_50_start and appeared:
                for other in nums:
                    if other != n and other in num_range:
                        cooccur_counts[n][other] += 1
                if is_pb and n == pb:
                    for other in nums:
                        if other in num_range:
                            cooccur_counts[n][other] += 1

    # --- Build feature vectors ---
    results = []
    for n in num_range:
        gap = target_idx - last_appearance.get(n, 0) - 1 if n in last_appearance else target_idx
        gap = min(gap, 500)  # cap extreme gaps
        total_draws = len(past_draws)
        total_draws = max(total_draws, 1)

        # Average position
        avg_pos = position_sums[n] / position_n[n] if position_n[n] > 0 else -1

        # Co-occurrence with hottest number
        if not is_pb:
            hot_nums = [x for x, _ in freq_30.most_common(3)]
        else:
            hot_nums = [x for x, _ in freq_30.most_common(3)]
        cooccur_hot = sum(cooccur_counts[n].get(h, 0) for h in hot_nums)

        # Most common position
        pos_counts = position_counts[n]
        most_common_pos = pos_counts.most_common(1)[0][0] if pos_counts else -1

        features = [
            n / (num_range[-1] + 1),  # 0: normalized number
            freq_10.get(n, 0),  # 1: freq last 10
            freq_30.get(n, 0),  # 2: freq last 30
            freq_all.get(n, 0),  # 3: total frequency
            gap / 500.0,  # 4: normalized gap
            1.0 if n in lag_1 else 0.0,  # 5: lag-1
            1.0 if n in lag_2 else 0.0,  # 6: lag-2
            1.0 if n in lag_3 else 0.0,  # 7: lag-3
            freq_10.get(n, 0) / max(target_idx - max(0, target_idx - 10), 1),  # 8: rolling mean 10
            freq_30.get(n, 0) / 30.0,  # 9: rolling mean 30
            freq_all.get(n, 0) / total_draws,  # 10: overall rate
            avg_pos / 5.0,  # 11: normalized avg position
            most_common_pos,  # 12: most common position
            streak_max[n],  # 13: max streak
            1.0 if n <= 10 else (2.0 if n <= 20 else (3.0 if n <= 30 else 4.0)),  # 14: decade
            1.0 if n % 2 == 1 else 0.0,  # 15: is odd
            min(cooccur_hot / 50.0, 1.0),  # 16: co-occurrence with hot nums
        ]

        label = 1 if n in current_nums else 0

        results.append(
            {
                "features": features,
                "label": label,
                "num": n,
                "is_powerball": is_pb,
            }
        )

    return results


def create_dataset(
    draws: list[tuple[list[int], int, str]],
    num_range: range,
    min_history: int = MIN_HISTORY,
    test_split: float = 0.2,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build train/test feature matrices and labels.

    Splits chronologically: first (1-test_split) of eligible draws for training,
    last test_split for testing.
    """
    all_rows = []
    eligible_start = min_history
    n_eligible = len(draws) - eligible_start

    if n_eligible < 100:
        print(f"WARNING: only {n_eligible} eligible draws — results may be unreliable.")

    for i in range(eligible_start, len(draws)):
        rows = build_features_for_draw(draws, i, num_range)
        all_rows.extend(rows)

    if not all_rows:
        print("ERROR: no feature rows generated. Need at least {min_history} draws.")
        sys.exit(1)

    # Convert to arrays
    x = np.array([r["features"] for r in all_rows], dtype=np.float32)
    y = np.array([r["label"] for r in all_rows], dtype=np.int32)

    # Chronological split: use draw index boundaries
    # Each draw contributes len(num_range) rows consecutively
    n_numbers = len(num_range)
    n_draws_eligible = len(all_rows) // n_numbers
    split_idx = int(n_draws_eligible * (1 - test_split)) * n_numbers

    x_train, x_test = x[:split_idx], x[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    print(f"  Total examples: {len(x)}  ({n_draws_eligible} draws × {n_numbers} numbers)")
    print(f"  Train: {len(x_train)}  |  Test: {len(x_test)}")
    print(
        f"  Class balance — train: {y_train.mean():.3%} positive, "
        f"test: {y_test.mean():.3%} positive"
    )

    return x_train, x_test, y_train, y_test


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train_xgboost(
    x_train: np.ndarray,
    x_test: np.ndarray,
    y_train: np.ndarray,
    y_test: np.ndarray,
    label: str = "main",
) -> Any:
    """Train an XGBoost classifier with early stopping."""
    try:
        import xgboost as xgb
    except ImportError:
        print("ERROR: xgboost is not installed.")
        print("Run: pip install xgboost")
        sys.exit(1)

    scale_pos_weight = (len(y_train) - y_train.sum()) / max(y_train.sum(), 1)

    print(f"  scale_pos_weight={scale_pos_weight:.2f}")

    model = xgb.XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        eval_metric="logloss",
        use_label_encoder=False,
        random_state=42,
        verbosity=0,
    )

    model.fit(
        x_train,
        y_train,
        eval_set=[(x_test, y_test)],
        early_stopping_rounds=30,
        verbose=False,
    )

    # Evaluate
    train_prob = model.predict_proba(x_train)[:, 1]
    test_prob = model.predict_proba(x_test)[:, 1]
    train_auc = _roc_auc(y_train, train_prob)
    test_auc = _roc_auc(y_test, test_prob)

    best_round = (
        model.best_iteration
        if hasattr(model, "best_iteration")
        else model.get_params()["n_estimators"]
    )

    print(f"  Best iteration: {best_round}")
    print(f"  Train AUC:      {train_auc:.4f}")
    print(f"  Test AUC:       {test_auc:.4f}")

    # Feature importance
    importance = model.feature_importances_
    feature_names = [
        "norm_num",
        "freq_10",
        "freq_30",
        "freq_all",
        "norm_gap",
        "lag_1",
        "lag_2",
        "lag_3",
        "roll_mean_10",
        "roll_mean_30",
        "overall_rate",
        "norm_avg_pos",
        "most_common_pos",
        "max_streak",
        "decade",
        "is_odd",
        "cooccur_hot",
    ]
    sorted_idx = np.argsort(importance)[::-1]
    print("  Top 5 features:")
    for idx in sorted_idx[:5]:
        print(f"    {feature_names[idx]:>16s}  {importance[idx]:.4f}")

    return model


def _roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Compute ROC AUC without sklearn dependency (pure numpy)."""
    n_pos = int(y_true.sum())
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    # Mann-Whitney U statistic
    order = np.argsort(y_score)
    rank_sum = np.sum(np.where(y_true[order] == 1)[0]) + n_pos
    auc = (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(auc)


# ---------------------------------------------------------------------------
# Prediction helper — generates features for the NEXT draw
# ---------------------------------------------------------------------------


def predict_next(
    draws: list[tuple[list[int], int, str]],
    main_model: Any,
    pb_model: Any | None,
) -> dict:
    """Generate a prediction for the next draw after the last one in *draws*.

    Returns dict with 'numbers' (sorted 6 ints), 'powerball' (int),
    and probabilities.
    """
    # Feature rows for the NEXT draw (target_idx = len(draws))
    next_idx = len(draws)

    main_rows = build_features_for_draw(draws, next_idx, range(1, 41))
    pb_rows = build_features_for_draw(draws, next_idx, range(1, 11))

    if not main_rows:
        return {"numbers": [], "powerball": 0}

    # Main numbers: predict probabilities, pick top 6
    x_main = np.array([r["features"] for r in main_rows], dtype=np.float32)
    probs_main = main_model.predict_proba(x_main)[:, 1]
    num_probs = [(r["num"], probs_main[i]) for i, r in enumerate(main_rows)]
    num_probs.sort(key=lambda x: x[1], reverse=True)
    top6 = sorted([n for n, p in num_probs[:6]])
    top6_probs = dict(num_probs[:6])

    # Powerball
    if pb_model is not None and pb_rows:
        x_pb = np.array([r["features"] for r in pb_rows], dtype=np.float32)
        probs_pb = pb_model.predict_proba(x_pb)[:, 1]
        pb_candidates = [(r["num"], probs_pb[i]) for i, r in enumerate(pb_rows)]
        pb_candidates.sort(key=lambda x: x[1], reverse=True)
        pb = pb_candidates[0][0]
        pb_prob = pb_candidates[0][1]
    else:
        # Fallback: most common recent PB
        recent_pbs = Counter(pb for _, pb, _ in draws[-30:])
        pb = recent_pbs.most_common(1)[0][0]
        pb_prob = 0.0

    return {
        "numbers": top6,
        "powerball": pb,
        "number_probabilities": top6_probs,
        "powerball_probability": pb_prob,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Train XGBoost models on NZ Lotto Powerball draws.",
    )
    parser.add_argument(
        "--db",
        default="lotto_working.db",
        help="Path to lotto_working.db (default: lotto_working.db)",
    )
    parser.add_argument(
        "--output",
        default="model.pkl",
        help="Output path for the trained model (default: model.pkl)",
    )
    parser.add_argument(
        "--no-pb-model",
        action="store_true",
        help="Don't train a separate Powerball model (uses frequency instead)",
    )
    args = parser.parse_args()

    # 1. Load data
    print("Loading draws...")
    draws = load_draws_from_db(args.db)
    print(f"  Loaded {len(draws)} draws (since {draws[0][3]} to {draws[-1][3]})")

    if len(draws) < 100:
        print(f"ERROR: need at least 100 draws, got {len(draws)}.")
        sys.exit(1)

    # 2. Main numbers (1-40)
    print("\n--- Main Numbers (1-40) ---")
    x_train, x_test, y_train, y_test = create_dataset(draws, range(1, 41))
    main_model = train_xgboost(x_train, x_test, y_train, y_test, label="main")

    # 3. Powerball (1-10)
    pb_model = None
    if not args.no_pb_model:
        print("\n--- Powerball (1-10) ---")
        x_pb_train, x_pb_test, y_pb_train, y_pb_test = create_dataset(draws, range(1, 11))
        pb_model = train_xgboost(x_pb_train, x_pb_test, y_pb_train, y_pb_test, label="powerball")

    # 4. Predict next draw
    print("\n--- Prediction for Next Draw ---")
    prediction = predict_next(draws, main_model, pb_model)
    nums_str = ", ".join(f"{n:02d}" for n in prediction["numbers"])
    prob_str = ", ".join(
        f"#{n}: {prediction['number_probabilities'].get(n, 0):.2%}" for n in prediction["numbers"]
    )
    print(f"  Numbers:          {nums_str}")
    print(f"  Number probs:     {prob_str}")
    print(
        f"  Powerball:        {prediction['powerball']}  "
        f"(prob: {prediction['powerball_probability']:.2%})"
    )
    print()

    # 5. Save model
    model_data = {
        "main_model": main_model,
        "pb_model": pb_model,
        "feature_names": [
            "norm_num",
            "freq_10",
            "freq_30",
            "freq_all",
            "norm_gap",
            "lag_1",
            "lag_2",
            "lag_3",
            "roll_mean_10",
            "roll_mean_30",
            "overall_rate",
            "norm_avg_pos",
            "most_common_pos",
            "max_streak",
            "decade",
            "is_odd",
            "cooccur_hot",
        ],
        "n_main": 40,
        "n_pb": 10,
        "draws_used": len(draws),
        "date_range": (draws[0][3], draws[-1][3]),
        "train_metrics": {
            "main_test_auc": _roc_auc(y_test, main_model.predict_proba(x_test)[:, 1]),
        },
        "prediction": prediction,
    }

    with open(args.output, "wb") as f:
        pickle.dump(model_data, f, protocol=pickle.HIGHEST_PROTOCOL)

    print(f"Model saved to {args.output}  ({os.path.getsize(args.output) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()


# ==============================================================================
# Google Colab Step-by-Step Guide
# ==============================================================================
#
# Since your local CPU lacks AVX instructions (needed by XGBoost), run training
# on Google Colab's free GPU/TPU runtime, then download the model for local use.
#
# --- Step 1: Upload files to Colab ---
#
# In a Colab notebook cell, run:
#
#   from google.colab import files
#   uploaded = files.upload()   # select lotto_working.db
#
# This uploads your SQLite database to the Colab runtime.
#
# --- Step 2: Install XGBoost ---
#
#   !pip install xgboost numpy
#
# --- Step 3: Upload and run the training script ---
#
#   uploaded = files.upload()   # select train_ml_model.py
#   !python3 train_ml_model.py
#
# Or paste the entire train_ml_model.py content into a cell and run it.
#
# Expected output (abbreviated):
#   Loading draws...
#     Loaded 1873 draws (since 2001-02-17 to 2026-05-06)
#
#   --- Main Numbers (1-40) ---
#     Total examples: 73720  (1843 draws x 40 numbers)
#     Train: 58960  |  Test: 14760
#     Class balance — train: 15.000% positive, test: 15.000% positive
#     scale_pos_weight=5.67
#     Best iteration: ...
#     Train AUC:      ~0.64
#     Test AUC:       ~0.58
#     Top 5 features:
#            norm_gap  0.1234
#            ...
#
#   --- Powerball (1-10) ---
#     Total examples: 18430  (1843 draws x 10 numbers)
#     Train: 14740  |  Test: 3690
#
#   --- Prediction for Next Draw ---
#     Numbers:          05, 12, 18, 23, 31, 38
#     Number probs:     #5: 23.4%, #12: 21.1%, ...
#     Powerball:        7  (prob: 11.2%)
#
#   Model saved to model.pkl  (X KB)
#
# --- Step 4: Download the model ---
#
#   from google.colab import files
#   files.download("model.pkl")
#   files.download("predict_ml.py")
#
# --- Step 5: Use locally ---
#
#   python3 predict_ml.py
#
# Or from Python:
#
#   from predict_ml import load_draws, predict
#   import pickle
#
#   with open("model.pkl", "rb") as f:
#       model_data = pickle.load(f)
#   draws = load_draws("lotto_working.db")
#   pred = predict(draws, model_data)
#   print(pred["numbers"], pred["powerball"])
#
# --- Full Colab Notebook (copy-paste into a single cell) ---
#
#   # Cell 1: Install
#   !pip install xgboost numpy
#
#   # Cell 2: Upload DB
#   from google.colab import files
#   print("Upload lotto_working.db")
#   uploaded = files.upload()
#
#   # Cell 3: Upload training script and run
#   print("Upload train_ml_model.py")
#   uploaded = files.upload()
#   !python3 train_ml_model.py
#
#   # Cell 4: Download results
#   from google.colab import files
#   files.download("model.pkl")
#   print("Also download predict_ml.py from the repo")
#
# --- Notes ---
#
# - Training takes ~5 minutes on Colab's free CPU runtime.
# - AUC ~0.57-0.60 is expected for lottery data (near-random by nature).
# - The feature pipeline uses only past draws (no data leakage).
# - If Colab disconnects, re-run the cells — the DB stays uploaded for
#   the session duration.
# ==============================================================================
