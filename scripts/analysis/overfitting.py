"""Cross-validation demo with early stopping for the feed-forward NN.

Prompt pack: overfitting. Uses the NN definition from architectures.py.

5-fold expanding time-series CV on the 2008-2022 train window. For each
fold it records the training loss curve and the held-out fold's log-loss,
plots train-vs-val per fold, and reports the fold with the largest gap.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import section, subsection  # noqa: E402

from architectures import FEATURE_COLS, load_frame, train_nn  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLOT_OUT = REPO_ROOT / "data" / "plots" / "overfitting_cv.png"


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import log_loss
    from sklearn.model_selection import TimeSeriesSplit

    frame = load_frame()
    if frame.empty:
        print("ERROR: data/features.parquet missing. Run features.py first.")
        return 1

    train = frame[(frame["draw_date"] >= "2008-01-01") & (frame["draw_date"] < "2023-01-01")]
    train = train.sort_values(["draw_date", "draw_number"])
    X = train[FEATURE_COLS].to_numpy()
    y = train["hit"].to_numpy()
    print(f"Train rows: {len(train)} ({train['draw_number'].nunique()} draws)")

    tscv = TimeSeriesSplit(n_splits=5)
    folds = list(tscv.split(X))

    section("5-fold time-series cross-validation (expanding window)")
    fig, ax = plt.subplots(figsize=(10, 5))
    gaps: list[tuple[int, float, float, float]] = []

    for fold, (tr_idx, va_idx) in enumerate(folds, 1):
        model = train_nn(
            pd.DataFrame(X[tr_idx], columns=FEATURE_COLS),
            pd.Series(y[tr_idx]),
        )
        train_loss = float(model.loss_curve_[-1])
        val_loss = float(log_loss(y[va_idx], model.predict_proba(X[va_idx])))
        gap = val_loss - train_loss
        gaps.append((fold, train_loss, val_loss, gap))

        ax.plot(model.loss_curve_, label=f"fold {fold} train", alpha=0.7)
        ax.axhline(val_loss, linestyle="--", alpha=0.5)
        print(f"  Fold {fold}: train rows={len(tr_idx)} val rows={len(va_idx)}  "
              f"train_loss={train_loss:.4f}  val_loss={val_loss:.4f}  gap={gap:+.4f}")

    worst = max(gaps, key=lambda g: g[3])
    ax.set_xlabel("epoch")
    ax.set_ylabel("binary cross-entropy")
    ax.set_title("NN train loss curves (dashed = held-out fold val loss)")
    ax.legend(fontsize=7, ncol=2)
    PLOT_OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOT_OUT, dpi=90, bbox_inches="tight")
    plt.close(fig)

    section("Summary")
    print(f"Plot: {PLOT_OUT}")
    print(f"Largest train-val gap: fold {worst[0]} "
          f"(train={worst[1]:.4f}, val={worst[2]:.4f}, gap={worst[3]:+.4f})")
    print()
    print("A persistent, large gap indicates the NN memorises training noise")
    print("(overfitting). For a fair lottery the val loss should hover near")
    print("the marginal entropy H(0.15) ~ 0.42 nats and never meaningfully")
    print("improve below it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
