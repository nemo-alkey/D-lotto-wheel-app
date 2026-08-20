#!/usr/bin/env python3
"""
ensemble_cv.py — Expanding-window time-series cross-validation for ensemble
weight calibration.

Replaces the simple walk-forward calibration in ensemble.py (softmax over
accumulated inverse Brier scores) with proper expanding-window CV that
optimizes the ensemble weights directly on out-of-sample loss.

Data format
-----------
``predictions_df`` is a pandas DataFrame with one row per draw (chronological
order — the row order IS the time order, nothing is ever shuffled) and:

- one column per predictor holding that predictor's probability/score for
  the draw (values in [0, 1]), and
- an ``actual`` column with the observed binary outcome (1/0). For
  hit-rate-style scores where the target is "perfect accuracy", use a
  column of ones (see update_ensemble_weights()).

Anti-leakage policy (CRITICAL for sequential lottery/financial data)
--------------------------------------------------------------------
- Fold k optimizes weights ONLY on rows [0 : i) and validates on
  rows [i : i+step). Validation rows are never touched during optimization.
- Windows expand from the start of history; i advances by ``step``.
- No shuffling, no random splitting, no future rows in any training set.
- The final production weights are refit on the FULL history — that is
  standard CV practice: the folds estimate out-of-sample performance, the
  refit produces the deployable weights.

Dependencies: numpy, pandas, scipy.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.optimize import minimize

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = Path("data/lotto.db")
DEFAULT_CONFIG_PATH = Path("config/ensemble_weights.json")
EPS = 1e-7  # probability clipping for log-loss


@dataclass
class CVResult:
    """Outcome of expanding_window_cv()."""

    weights: dict[str, float]  # optimal weights (refit on full history)
    cv_history: list[dict[str, Any]]  # per-fold dicts (scores + weights)
    fold_performance: pd.DataFrame  # plot-ready train/val score per fold
    mean_val_score: float
    uniform_mean_val_score: float
    metric: str
    folds: int


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _ensemble_score(p: np.ndarray, y: np.ndarray, w: np.ndarray, metric: str) -> float:
    """Mean Brier score or log-loss of the weighted-average ensemble."""
    ens = p @ w
    if metric == "log_loss":
        ens = np.clip(ens, EPS, 1.0 - EPS)
        return float(-np.mean(y * np.log(ens) + (1.0 - y) * np.log(1.0 - ens)))
    if metric == "brier":
        return float(np.mean((ens - y) ** 2))
    raise ValueError(f"Unknown metric: {metric!r} (use 'brier' or 'log_loss')")


def _optimize_weights(p: np.ndarray, y: np.ndarray, metric: str) -> np.ndarray:
    """Minimize the ensemble loss on the given rows.

    Constraints: weights non-negative and summing to 1 (SLSQP simplex).
    """
    k = p.shape[1]
    w0 = np.full(k, 1.0 / k)

    res = minimize(
        lambda w: _ensemble_score(p, y, w, metric),
        w0,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * k,
        constraints={"type": "eq", "fun": lambda w: w.sum() - 1.0},
        options={"maxiter": 500},
    )
    w = res.x if res.success and np.all(np.isfinite(res.x)) else w0
    w = np.clip(w, 0.0, 1.0)
    total = w.sum()
    return cast(np.ndarray, w / total) if total > 0 else w0


# ---------------------------------------------------------------------------
# Core CV
# ---------------------------------------------------------------------------
def expanding_window_cv(
    predictions_df: pd.DataFrame,
    min_train_size: int = 20,
    step: int = 5,
    actual_col: str = "actual",
    metric: str = "brier",
) -> CVResult:
    """Expanding-window time-series cross-validation over ensemble weights.

    Parameters
    ----------
    predictions_df : pd.DataFrame
        Chronological rows; one column per predictor (scores in [0, 1])
        plus the `actual_col` binary outcome column.
    min_train_size : int
        Rows in the first training window (default 20).
    step : int
        Validation window width / expansion step (default 5).
    actual_col : str
        Name of the outcome column (default "actual").
    metric : str
        "brier" or "log_loss".

    Returns
    -------
    CVResult
        ``weights`` (refit on all data), ``cv_history`` (per-fold dicts),
        and ``fold_performance`` (plot-ready DataFrame).
    """
    if actual_col not in predictions_df.columns:
        raise ValueError(f"Missing outcome column {actual_col!r}.")

    predictor_cols = [c for c in predictions_df.columns if c != actual_col]
    if len(predictor_cols) < 2:
        raise ValueError("Need at least 2 predictor columns to ensemble.")

    n = len(predictions_df)
    if n < min_train_size + 1:
        raise ValueError(
            f"Not enough rows: {n} (need at least min_train_size + 1 = "
            f"{min_train_size + 1})."
        )

    y_all = predictions_df[actual_col].to_numpy(dtype=float)
    p_all = predictions_df[predictor_cols].to_numpy(dtype=float)

    uniform_w = np.full(len(predictor_cols), 1.0 / len(predictor_cols))
    cv_history: list[dict[str, Any]] = []

    # --- Folds: train [0:i], validate [i:i+step], expand i by step ---
    fold = 0
    i = min_train_size
    while i < n:
        val_end = min(i + step, n)

        # Anti-leakage: optimize strictly on rows before i
        w = _optimize_weights(p_all[:i], y_all[:i], metric)

        train_score = _ensemble_score(p_all[:i], y_all[:i], w, metric)
        val_score = _ensemble_score(p_all[i:val_end], y_all[i:val_end], w, metric)
        uniform_val_score = _ensemble_score(
            p_all[i:val_end], y_all[i:val_end], uniform_w, metric
        )

        cv_history.append(
            {
                "fold": fold,
                "train_start": 0,
                "train_end": i,  # exclusive — last train row is i-1
                "val_start": i,
                "val_end": val_end,  # exclusive
                "train_size": i,
                "val_size": val_end - i,
                "train_score": train_score,
                "val_score": val_score,
                "uniform_val_score": uniform_val_score,
                "weights": dict(zip(predictor_cols, w.round(6).tolist(), strict=False)),
            }
        )
        fold += 1
        i += step

    # --- Final production weights: refit on the full history ---
    final_w = _optimize_weights(p_all, y_all, metric)
    weights = {
        name: round(float(w), 6)
        for name, w in zip(predictor_cols, final_w, strict=False)
    }

    fold_performance = pd.DataFrame(cv_history)
    mean_val = float(fold_performance["val_score"].mean())
    uniform_mean_val = float(fold_performance["uniform_val_score"].mean())

    return CVResult(
        weights=weights,
        cv_history=cv_history,
        fold_performance=fold_performance,
        mean_val_score=mean_val,
        uniform_mean_val_score=uniform_mean_val,
        metric=metric,
        folds=fold,
    )


# ---------------------------------------------------------------------------
# Database integration
# ---------------------------------------------------------------------------
def load_predictions_frame(
    db_path: Path | str = DEFAULT_DB_PATH,
    n_draws: int = 100,
) -> pd.DataFrame:
    """Build a predictions_df from the prediction_records table.

    Each predictor's per-draw score is its hit rate
    (|recommended ∩ actual| / |actual|), in [0, 1]. The ``actual`` column
    is all ones: the target is perfect accuracy, so the squared-loss
    objective is (1 − Σ wᵢ·scoreᵢ)² — a Brier-type loss that maximizes
    weighted hit rate while the quadratic term mildly diversifies across
    correlated predictors.

    Only draws where EVERY predictor has a scored record are kept, so the
    matrix has no gaps (no imputation, no lookahead).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT draw_date, predictor_name, recommended_numbers, "
            "actual_drawn_numbers FROM prediction_records "
            "WHERE actual_drawn_numbers IS NOT NULL "
            "ORDER BY draw_date ASC"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise ValueError(
            "No scored prediction records found (prediction_records with "
            "non-null actual_drawn_numbers)."
        )

    records = []
    for draw_date, name, rec_json, act_json in rows:
        recommended = set(json.loads(rec_json))
        actual = set(json.loads(act_json))
        if not actual:
            continue
        records.append(
            {
                "draw_date": draw_date,
                "predictor": name,
                "score": len(recommended & actual) / len(actual),
            }
        )

    frame = pd.DataFrame(records)
    pivot = frame.pivot_table(
        index="draw_date", columns="predictor", values="score", aggfunc="mean"
    ).sort_index()
    pivot = pivot.dropna()  # only draws scored by every predictor
    if n_draws and len(pivot) > n_draws:
        pivot = pivot.iloc[-n_draws:]
    pivot["actual"] = 1.0
    return pivot.reset_index(drop=True)


def update_ensemble_weights(
    n_draws: int = 100,
    db_path: Path | str = DEFAULT_DB_PATH,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    min_train_size: int = 20,
    step: int = 5,
    metric: str = "brier",
) -> dict[str, Any]:
    """Read recent predictions, run expanding-window CV, persist weights.

    Writes config/ensemble_weights.json with the optimal weights plus the
    CV summary, so ensemble.py (or any consumer) can load calibrated
    weights instead of the walk-forward heuristic.

    Returns
    -------
    dict
        The persisted config payload.
    """
    predictions_df = load_predictions_frame(db_path=db_path, n_draws=n_draws)
    result = expanding_window_cv(
        predictions_df, min_train_size=min_train_size, step=step, metric=metric
    )

    payload = {
        "updated_at": datetime.now().isoformat(),
        "source": "ensemble_cv.expanding_window_cv",
        "n_draws_used": int(len(predictions_df)),
        "metric": metric,
        "min_train_size": min_train_size,
        "step": step,
        "weights": result.weights,
        "cv": {
            "folds": result.folds,
            "mean_val_score": round(result.mean_val_score, 6),
            "uniform_mean_val_score": round(result.uniform_mean_val_score, 6),
            "improvement_vs_uniform": round(
                result.uniform_mean_val_score - result.mean_val_score, 6
            ),
        },
    }

    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2))
    return payload


# ---------------------------------------------------------------------------
# Unit tests (pytest) + self-test
# ---------------------------------------------------------------------------
def _make_synthetic(n: int = 80, seed: int = 42) -> pd.DataFrame:
    """One informative predictor, one noisy, one anti-informative."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, size=n).astype(float)
    good = np.clip(y + rng.normal(0, 0.05, n), 0.0, 1.0)  # tracks actual
    noise = rng.uniform(0.0, 1.0, n)  # pure noise
    bad = np.clip(1.0 - y + rng.normal(0, 0.2, n), 0.0, 1.0)  # anti-correlated
    return pd.DataFrame(
        {
            "good": good,
            "noise": noise,
            "bad": bad,
            "actual": y,
        }
    )


def test_weights_sum_to_one() -> None:
    result = expanding_window_cv(_make_synthetic(), min_train_size=20, step=5)
    assert abs(sum(result.weights.values()) - 1.0) < 1e-6
    assert all(w >= 0.0 for w in result.weights.values())


def test_no_future_leakage() -> None:
    """Fold k trains only on [0:i): appending future rows must not change it."""
    df = _make_synthetic(n=80)
    full = expanding_window_cv(df, min_train_size=20, step=5)
    cut = expanding_window_cv(df.iloc[:60], min_train_size=20, step=5)
    for fold_full, fold_cut in zip(full.cv_history, cut.cv_history, strict=False):
        for name, w in fold_cut["weights"].items():
            assert abs(fold_full["weights"][name] - w) < 1e-6, (
                f"Fold {fold_cut['fold']} weight for {name} changed when "
                "future data was appended — leakage!"
            )
        assert fold_full["train_end"] <= fold_full["val_start"]


def test_beats_uniform_weighting() -> None:
    """With one clearly-informative predictor, CV must beat uniform weights."""
    result = expanding_window_cv(_make_synthetic(), min_train_size=20, step=5)
    assert result.mean_val_score < result.uniform_mean_val_score
    assert result.weights["good"] > result.weights["bad"]


def test_log_loss_metric_runs() -> None:
    result = expanding_window_cv(
        _make_synthetic(), min_train_size=20, step=5, metric="log_loss"
    )
    assert abs(sum(result.weights.values()) - 1.0) < 1e-6
    assert result.folds > 0


if __name__ == "__main__":
    print("Running synthetic-data self-test...")
    test_weights_sum_to_one()
    test_no_future_leakage()
    test_beats_uniform_weighting()
    test_log_loss_metric_runs()
    print("All tests passed.\n")

    result = expanding_window_cv(_make_synthetic(), min_train_size=20, step=5)
    print(f"Folds: {result.folds}")
    print(f"Mean val brier (optimized): {result.mean_val_score:.4f}")
    print(f"Mean val brier (uniform):   {result.uniform_mean_val_score:.4f}")
    print(f"Optimal weights: {result.weights}")
    print("\nFold performance (plot-ready):")
    print(
        result.fold_performance[
            [
                "fold",
                "train_size",
                "val_size",
                "train_score",
                "val_score",
                "uniform_val_score",
            ]
        ].to_string(index=False)
    )
