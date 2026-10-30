"""Optuna hyperparameter search for the NN, saving the best model.

Prompt pack: hyperparameter tuning. Searches learning rate, hidden layers,
nodes, batch size and epochs via 3-fold time-series CV, then saves the best
model to models/nn_tuned.pkl and the study to reports/optuna/study_*.pkl.

Use --trials N to control the search budget (default 50).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import section  # noqa: E402
from architectures import FEATURE_COLS, load_frame  # noqa: E402

try:
    import optuna
except ImportError:
    print("ERROR: optuna required. python -m pip install optuna")
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STUDY_DIR = REPO_ROOT / "reports" / "optuna"
MODEL_OUT = REPO_ROOT / "models" / "nn_tuned.pkl"


def make_objective(x: np.ndarray, y: np.ndarray):
    from sklearn.metrics import log_loss
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.neural_network import MLPClassifier

    def objective(trial: optuna.Trial) -> float:
        lr = trial.suggest_float("learning_rate", 1e-4, 1e-1, log=True)
        n_layers = trial.suggest_int("layers", 1, 3)
        nodes = trial.suggest_int("nodes", 32, 128)
        batch = trial.suggest_categorical("batch", [64, 128, 256])
        epochs = trial.suggest_int("epochs", 50, 200)
        alpha = trial.suggest_float("alpha", 1e-5, 1e-1, log=True)

        losses = []
        for tr_idx, va_idx in TimeSeriesSplit(n_splits=3).split(x):
            model = MLPClassifier(
                hidden_layer_sizes=(nodes,) * n_layers,
                solver="sgd",
                learning_rate_init=lr,
                batch_size=batch,
                max_iter=epochs,
                alpha=alpha,
                early_stopping=True,
                validation_fraction=0.1,
                n_iter_no_change=5,
                random_state=0,
            )
            model.fit(x[tr_idx], y[tr_idx])
            losses.append(log_loss(y[va_idx], model.predict_proba(x[va_idx])))
        return float(np.mean(losses))

    return objective


def build_best_model(params: dict, x: np.ndarray, y: np.ndarray):
    from sklearn.neural_network import MLPClassifier

    model = MLPClassifier(
        hidden_layer_sizes=(params["nodes"],) * params["layers"],
        solver="sgd",
        learning_rate_init=params["learning_rate"],
        batch_size=params["batch"],
        max_iter=params["epochs"],
        alpha=params["alpha"],
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=5,
        random_state=0,
    )
    model.fit(x, y)
    return model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=50)
    args = parser.parse_args()

    frame = load_frame()
    if frame.empty:
        print("ERROR: data/features.parquet missing. Run features.py first.")
        return 1

    train = frame[(frame["draw_date"] >= "2008-01-01") & (frame["draw_date"] < "2023-01-01")]
    train = train.sort_values(["draw_date", "draw_number"])
    x = train[FEATURE_COLS].to_numpy()
    y = train["hit"].to_numpy()
    print(f"Train rows: {len(train)} ({train['draw_number'].nunique()} draws)")

    section(f"Optuna search ({args.trials} trials, 3-fold time-series CV)")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize")
    study.optimize(make_objective(x, y), n_trials=args.trials)

    print("Best params:")
    for k, v in study.best_params.items():
        print(f"  {k}: {v}")
    print(f"Best score (mean val log-loss): {study.best_value:.4f}")

    # persist study
    STUDY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    study_path = STUDY_DIR / f"study_{stamp}.pkl"
    joblib.dump(study, study_path)
    print(f"Study: {study_path}")

    # retrain best model on full train window and save
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    best = build_best_model(study.best_params, x, y)
    joblib.dump(best, MODEL_OUT)
    print(f"Best model: {MODEL_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
