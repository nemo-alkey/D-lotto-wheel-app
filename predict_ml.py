#!/usr/bin/env python3
"""
predict_ml.py — Load a trained XGBoost model and predict the next Lotto draw.

Emits the top-N numbers, the Powerball, and a ranked list of candidate sets.

Usage:
    python3 predict_ml.py                        # uses model.pkl + data/lotto.db
    python3 predict_ml.py --model /path/to/model.pkl
    python3 predict_ml.py --db /path/to/other.db
    python3 predict_ml.py --top 10               # show top 10 numbers, not just 6
    python3 predict_ml.py --sets 5               # number of candidate sets
"""

from __future__ import annotations

import random

from powerball_rules import POWERBALL_MAX_NEW

POWERBALL_MAX = POWERBALL_MAX_NEW  # era-aware: 10 pre-2026-09-16, 14 after

import argparse
import os
import pickle
import sys
from collections import Counter
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Data loading (standalone, no lotto_wheels dependency needed)
# ---------------------------------------------------------------------------


def load_draws(db_path: str) -> list[tuple[list[int], int, int, str]]:
    """Load draws from a SQLite file.

    Supports both schemas:
      - wide (legacy ``lotto_working.db``): n1..n6, powerball, bonus, draw_date
      - canonical (``data/lotto.db``): numbers (comma-joined), powerball, bonus, draw_date
    """
    import sqlite3

    if not os.path.exists(db_path):
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cols = {row[1] for row in conn.execute("PRAGMA table_info(draws)")}
    if {"n1", "n6"} <= cols:
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
    else:
        cursor = conn.execute(
            "SELECT draw_date, numbers, powerball, bonus FROM draws ORDER BY draw_date"
        )
        draws = []
        for row in cursor:
            nums = [int(x) for x in (row["numbers"] or "").split(",") if x.strip()]
            if len(nums) != 6:
                continue
            draws.append((nums, row["powerball"] or 0, row["bonus"] or 0, row["draw_date"]))
    conn.close()
    return draws


# ---------------------------------------------------------------------------
# Feature builder (must match train_ml_model.py exactly)
# ---------------------------------------------------------------------------

MIN_HISTORY = 30


def build_features_for_draw(
    draws: list[tuple[list[int], int, int, str]],
    target_idx: int,
    num_range: range,
) -> list[dict[str, Any]]:
    """Build one feature vector per number for draw *target_idx*.

    See train_ml_model.py for the full feature specification.
    """
    if target_idx < MIN_HISTORY:
        return []

    past_draws = draws[:target_idx]
    current_nums = draws[target_idx][0] if target_idx < len(draws) else []
    is_pb = num_range[0] == 1 and num_range[-1] in (10, 14)
    if is_pb:
        current_nums = [draws[target_idx][1]] if target_idx < len(draws) else []

    freq_10: Counter[int] = Counter()
    freq_30: Counter[int] = Counter()
    freq_all: Counter[int] = Counter()
    last_appearance: dict[int, int] = {}
    lag_1: set[int] = set()
    lag_2: set[int] = set()
    lag_3: set[int] = set()
    position_counts: dict[int, Counter[int]] = {n: Counter() for n in num_range}
    position_sums: dict[int, float] = {n: 0.0 for n in num_range}
    position_n: dict[int, int] = {n: 0 for n in num_range}
    cooccur_counts: dict[int, Counter[int]] = {n: Counter() for n in num_range}
    streak_current: dict[int, int] = {n: 0 for n in num_range}
    streak_max: dict[int, int] = {n: 0 for n in num_range}
    recent_50 = max(0, target_idx - 50)

    for j, (nums, pb, _, _) in enumerate(past_draws):
        drawn_set = set(nums)
        if is_pb:
            drawn_set = {pb}

        for n in num_range:
            appeared = n in drawn_set
            if j >= target_idx - 10 and appeared:
                freq_10[n] += 1
            if j >= target_idx - 30 and appeared:
                freq_30[n] += 1
            if appeared:
                freq_all[n] += 1
            if j == target_idx - 1 and appeared:
                lag_1.add(n)
            if j == target_idx - 2 and appeared:
                lag_2.add(n)
            if j == target_idx - 3 and appeared:
                lag_3.add(n)
            if appeared:
                last_appearance[n] = j
            if appeared:
                streak_current[n] += 1
                streak_max[n] = max(streak_max[n], streak_current[n])
            else:
                streak_current[n] = 0
            if not is_pb and appeared and n in nums:
                pos = sorted(nums).index(n)
                position_sums[n] += pos
                position_n[n] += 1
                position_counts[n][pos] += 1
            if j >= recent_50 and appeared:
                for other in nums:
                    if other != n and other in num_range:
                        cooccur_counts[n][other] += 1
                if is_pb and n == pb:
                    for other in nums:
                        if other in num_range:
                            cooccur_counts[n][other] += 1

    results = []
    for n in num_range:
        gap = target_idx - last_appearance.get(n, 0) - 1 if n in last_appearance else target_idx
        gap = min(gap, 500)
        total_draws = max(len(past_draws), 1)
        avg_pos = position_sums[n] / position_n[n] if position_n[n] > 0 else -1.0
        hot_nums = [x for x, _ in freq_30.most_common(3)]
        cooccur_hot = sum(cooccur_counts[n].get(h, 0) for h in hot_nums)
        mcp = position_counts[n].most_common(1)[0][0] if position_counts[n] else -1

        features = [
            n / (num_range[-1] + 1),
            float(freq_10.get(n, 0)),
            float(freq_30.get(n, 0)),
            float(freq_all.get(n, 0)),
            gap / 500.0,
            1.0 if n in lag_1 else 0.0,
            1.0 if n in lag_2 else 0.0,
            1.0 if n in lag_3 else 0.0,
            freq_10.get(n, 0) / max(target_idx - max(0, target_idx - 10), 1),
            freq_30.get(n, 0) / 30.0,
            freq_all.get(n, 0) / total_draws,
            avg_pos / 5.0,
            float(mcp),
            float(streak_max[n]),
            1.0 if n <= 10 else (2.0 if n <= 20 else (3.0 if n <= 30 else 4.0)),
            1.0 if n % 2 == 1 else 0.0,
            min(cooccur_hot / 50.0, 1.0),
        ]

        label = 1 if n in current_nums else 0
        results.append({"features": features, "label": label, "num": n, "is_powerball": is_pb})

    return results


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def build_candidate_sets(
    num_probs: list[tuple[int, float]],
    powerball: int,
    n_sets: int = 5,
    size: int = 6,
) -> list[dict[str, Any]]:
    """Produce *n_sets* diverse candidate lines from the probability vector.

    Greedy selection with a reuse penalty so later lines differ from earlier
    ones. Under a fair draw every line is equally (un)likely; the ordering
    only reflects the model's confidence, not an edge.
    """
    ranked = sorted(num_probs, key=lambda x: -x[1])
    penalty: Counter = Counter()
    sets: list[dict[str, Any]] = []
    for _ in range(n_sets):
        scored = sorted(ranked, key=lambda x: -(x[1] - 0.5 * penalty[x[0]]))
        line = sorted(n for n, _ in scored[:size])
        for n in line:
            penalty[n] += 1
        confidence = sum(p for n, p in num_probs if n in line)
        _pb_for_line = powerball if powerball is not None else random.randint(1, 14)
        sets.append({"numbers": line, "powerball": _pb_for_line, "confidence": confidence})
    return sets


def predict(
    draws: list[Any],
    model_data: dict[str, Any],
    top_n: int = 6,
    n_sets: int = 5,
) -> dict[str, Any]:
    """Predict the next draw's numbers, Powerball, and candidate sets."""
    main_model = model_data["main_model"]
    pb_model = model_data.get("pb_model")
    next_idx = len(draws)

    # Main numbers
    main_rows = build_features_for_draw(draws, next_idx, range(1, 41))
    if not main_rows:
        return {
            "numbers": [],
            "powerball": 0,
            "main_probs": {},
            "pb_prob": 0.0,
            "candidate_sets": [],
        }

    x_main = np.array([r["features"] for r in main_rows], dtype=np.float32)
    probs_main = main_model.predict_proba(x_main)[:, 1]
    num_probs = [(r["num"], float(probs_main[i])) for i, r in enumerate(main_rows)]
    num_probs.sort(key=lambda x: x[1], reverse=True)
    top = sorted(num_probs[:top_n], key=lambda x: x[0])

    # All probs for display
    all_probs = {r["num"]: float(probs_main[i]) for i, r in enumerate(main_rows)}

    # Powerball
    if pb_model is not None:
        pb_rows = build_features_for_draw(draws, next_idx, range(1, POWERBALL_MAX + 1))
        if pb_rows:
            x_pb = np.array([r["features"] for r in pb_rows], dtype=np.float32)
            probs_pb = pb_model.predict_proba(x_pb)[:, 1]
            pb_candidates = [(r["num"], float(probs_pb[i])) for i, r in enumerate(pb_rows)]
            pb_candidates.sort(key=lambda x: x[1], reverse=True)
            pb = pb_candidates[0][0]
            pb_prob = pb_candidates[0][1]
        else:
            pb = 0
            pb_prob = 0.0
    else:
        # No PB model (insufficient post-change draws).
        # Signal per-line random dip to build_candidate_sets.
        pb = None
        pb_prob = None

    return {
        "numbers": [n for n, _ in top],
        "powerball": pb,
        "main_probs": all_probs,
        "top_probs": dict(num_probs[:top_n]),
        "pb_prob": pb_prob,
        "candidate_sets": build_candidate_sets(num_probs, pb, n_sets=n_sets),
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def print_prediction(pred: dict[str, Any], top_n: int) -> None:
    """Pretty-print a prediction."""
    nums_str = ", ".join(f"{n:02d}" for n in pred["numbers"])
    print()
    print("  === XGBoost Prediction ===")
    print(f"  Numbers:    {nums_str}")
    if pred.get("powerball") is None:
        print("  Powerball:  (no PB model - random dip per line)")
    else:
        print(f"  Powerball:  {pred['powerball']}")
    print()
    print(f"  Top {top_n} number probabilities:")
    for n in pred["numbers"]:
        bar = "#" * int(pred["top_probs"].get(n, 0) * 40)
        print(f"    #{n:02d}  {pred['top_probs'].get(n, 0):.2%}  {bar}")
    if pred.get("pb_prob") is not None:
        print(f"    PB  {pred['pb_prob']:.2%}")
    else:
        print("    PB  (no PB model)")
    print()

    sets = pred.get("candidate_sets") or []
    if sets:
        print(f"  Candidate sets ({len(sets)} lines):")
        for i, s in enumerate(sets, 1):
            nums = ", ".join(f"{n:02d}" for n in s["numbers"])
            print(
                f"    {i}. {nums}  + PB {s['powerball']:02d}   "
                f"(confidence {s['confidence']:.4f})"
            )
        print("    Note: under a fair draw every line is equally (un)likely;")
        print("          the ordering reflects model confidence only.")
        print()

    if pred["main_probs"]:
        # Sum, odd/even, etc.
        s = sum(pred["numbers"])
        odd = sum(1 for n in pred["numbers"] if n % 2 == 1)
        even = 6 - odd
        has_adj = any(
            pred["numbers"][i + 1] - pred["numbers"][i] <= 2
            for i in range(len(pred["numbers"]) - 1)
        )
        print(f"  Sum:        {s}")
        print(f"  Odd/Even:   {odd}o / {even}e")
        print(f"  Adjacent:   {'Yes' if has_adj else 'No'}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ML-powered NZ Lotto Powerball predictor.",
    )
    parser.add_argument(
        "--model",
        default="model.pkl",
        help="Path to model.pkl (default: model.pkl)",
    )
    parser.add_argument(
        "--db",
        default="data/lotto.db",
        help="Path to the draws SQLite DB (default: data/lotto.db)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=6,
        help="Show top N numbers (default: 6)",
    )
    parser.add_argument(
        "--sets",
        type=int,
        default=5,
        help="Number of candidate sets to emit (default: 5)",
    )
    args = parser.parse_args()

    if args.top < 1 or args.top > 40:
        print("ERROR: --top must be between 1 and 40.")
        sys.exit(1)

    # Load model
    if not os.path.exists(args.model):
        print(f"ERROR: model not found at {args.model}")
        print("Run train_ml_model.py first, or specify --model.")
        sys.exit(1)

    print(f"Loading model from {args.model}...")
    with open(args.model, "rb") as f:
        model_data = pickle.load(f)
    print(
        f"  Model trained on {model_data.get('draws_used', '?')} draws"
        f" ({model_data.get('date_range', ('?', '?'))[0]}"
        f" to {model_data.get('date_range', ('?', '?'))[1]})"
    )
    test_auc = model_data.get("train_metrics", {}).get("main_test_auc", 0)
    print(f"  Test AUC: {test_auc:.4f}")

    # Load draws
    draws = load_draws(args.db)
    print(f"  Database has {len(draws)} draws")

    # Predict
    pred = predict(draws, model_data, top_n=args.top, n_sets=args.sets)
    print_prediction(pred, args.top)


if __name__ == "__main__":
    main()
