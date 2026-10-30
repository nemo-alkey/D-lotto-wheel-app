"""Train three baselines on a time-based split and report top-k accuracy.

Prompt pack: model architectures. Requires data/features.parquet (features.py).

Split: train 2008-01-01 .. 2022-12-31, test 2023-01-01 onward.
Baselines:
  a. frequency-only (static ranking from train counts)
  b. gradient-boosted tree (xgboost) scoring each number's hit probability
  c. small feed-forward NN (2 hidden layers x 64)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import section  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FEATURES = REPO_ROOT / "data" / "features.parquet"

FEATURE_COLS = [
    "number",
    "rolled_freq_10",
    "rolled_freq_50",
    "rolled_freq_200",
    "draws_since",
    "cooccur_score",
    "is_wednesday",
    "era_flag",
]
KS = [1, 3, 6, 10, 20]


def load_frame() -> pd.DataFrame:
    if not FEATURES.exists():
        return pd.DataFrame()
    return pd.read_parquet(FEATURES)


def train_xgb(x: pd.DataFrame, y: pd.Series, seed: int = 0):
    from xgboost import XGBClassifier

    model = XGBClassifier(
        n_estimators=120,
        max_depth=4,
        learning_rate=0.1,
        random_state=seed,
        n_jobs=1,
        eval_metric="logloss",
        verbosity=0,
    )
    model.fit(np.asarray(x), np.asarray(y))
    return model


def train_nn(x: pd.DataFrame, y: pd.Series, seed: int = 0):
    from sklearn.neural_network import MLPClassifier

    model = MLPClassifier(
        hidden_layer_sizes=(64, 64),
        max_iter=200,
        random_state=seed,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=10,
    )
    model.fit(np.asarray(x), np.asarray(y))
    return model


def topk_accuracy(frame: pd.DataFrame, score_col: str, ks: list[int]) -> dict[int, float]:
    """Mean fraction of the 6 true numbers covered by each draw's top-k."""
    out = {k: [] for k in ks}
    for _, grp in frame.groupby("draw_number"):
        grp = grp.sort_values("number")
        true = set(grp.loc[grp["hit"] == 1, "number"])
        ranked = grp.nlargest(max(ks), score_col)["number"].tolist()
        for k in ks:
            out[k].append(len(true & set(ranked[:k])) / 6.0)
    return {k: float(np.mean(v)) for k, v in out.items()}


def main() -> int:
    frame = load_frame()
    if frame.empty:
        print("ERROR: data/features.parquet missing. Run features.py first.")
        return 1

    train = frame[(frame["draw_date"] >= "2008-01-01") & (frame["draw_date"] < "2023-01-01")]
    test = frame[frame["draw_date"] >= "2023-01-01"]
    print(f"Train rows: {len(train)} ({train['draw_number'].nunique()} draws)")
    print(f"Test rows:  {len(test)} ({test['draw_number'].nunique()} draws)")
    if test.empty:
        print("ERROR: no test draws (2023+).")
        return 1

    x_tr, y_tr = train[FEATURE_COLS], train["hit"]
    x_te = test[FEATURE_COLS]

    # ---- (a) frequency-only baseline ----
    section("Baseline (a): frequency-only")
    freq = train.groupby("number")["hit"].sum()
    test = test.assign(score_freq=test["number"].map(freq))
    acc_freq = topk_accuracy(test, "score_freq", KS)
    print("Top-k accuracy (mean fraction of 6 numbers covered):")
    for k, v in acc_freq.items():
        print(f"  k={k:>2}: {v:.4f}")

    # ---- (b) xgboost ----
    section("Baseline (b): gradient-boosted tree (xgboost)")
    model_xgb = train_xgb(x_tr, y_tr)
    test = test.assign(score_xgb=model_xgb.predict_proba(x_te)[:, 1])
    acc_xgb = topk_accuracy(test, "score_xgb", KS)
    for k, v in acc_xgb.items():
        print(f"  k={k:>2}: {v:.4f}")

    # ---- (c) feed-forward NN ----
    section("Baseline (c): feed-forward NN (64x64)")
    model_nn = train_nn(x_tr, y_tr)
    test = test.assign(score_nn=model_nn.predict_proba(x_te)[:, 1])
    acc_nn = topk_accuracy(test, "score_nn", KS)
    for k, v in acc_nn.items():
        print(f"  k={k:>2}: {v:.4f}")

    # ---- summary ----
    section("Summary: top-k accuracy (k=1,3,6,10,20)")
    print(f"{'Model':>28}  " + "  ".join(f"k={k:<2}" for k in KS))
    print("-" * 60)
    for name, acc in [("frequency", acc_freq), ("xgboost", acc_xgb), ("nn", acc_nn)]:
        print(f"{name:>28}  " + "  ".join(f"{acc[k]:.4f}" for k in KS))
    print()
    print("Chance (uniform 6/40) for a random top-k is 6*k/40. All models")
    print("should sit near chance for a fair game; deviations are noise.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
