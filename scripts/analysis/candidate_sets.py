"""Produce 5 candidate lines (6 numbers + 1 PB) from a trained model.

Prompt pack: candidate generation. Requires models/nn_tuned.pkl
(produced by optuna_tune.py); exits 1 if it is missing.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import load_draws, section, subsection  # noqa: E402
from architectures import FEATURE_COLS  # noqa: E402
from features import next_draw_frame  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_PATH = REPO_ROOT / "models" / "nn_tuned.pkl"


def build_candidate_sets() -> list[dict]:
    """Return 5 candidate dicts, each with keys:
    numbers (list[int]), pb (int), reasoning (str), confidence (float).
    """
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"models/nn_tuned.pkl missing. Run optuna_tune.py first."
        )

    model = joblib.load(MODEL_PATH)
    draws = load_draws()

    # ---- probability vector over the 40 main numbers for the next draw ----
    frame = next_draw_frame(draws)
    frame["prob"] = model.predict_proba(frame[FEATURE_COLS].to_numpy())[:, 1]
    frame["hot"] = frame["rolled_freq_200"]
    frame["overdue"] = frame["draws_since"]
    frame["pair"] = frame["cooccur_score"]

    def z(s: pd.Series) -> pd.Series:
        return (s - s.mean()) / (s.std() + 1e-9)

    frame["blend"] = z(frame["prob"]) + z(frame["hot"]) + z(frame["overdue"]) + z(frame["pair"])

    # ---- Powerball: era-aware frequency over post-change draws ----
    pb_freq = Counter(
        d["powerball"] for d in draws
        if d["rule_era"] == "post_2026_09_16" and d["powerball"] > 0
    )
    pb_rank = [p for p, _ in pb_freq.most_common()] or [1]
    while len(pb_rank) < 5:
        pb_rank.append(pb_rank[0])

    strategies = [
        ("Model consensus", "prob", "top numbers by the tuned model's hit probability"),
        ("Hot numbers", "hot", "most frequently drawn in the last 200 draws"),
        ("Overdue numbers", "overdue", "longest gap since last appearance (mean reversion)"),
        ("Pair affinity", "pair", "highest co-occurrence with the last drawn set"),
        ("Balanced blend", "blend", "z-score blend of model, hot, overdue and pair signals"),
    ]

    sets = []
    for i, (name, col, why) in enumerate(strategies):
        nums = frame.nlargest(6, col)["number"].astype(int).tolist()
        confidence = float(frame.set_index("number").loc[nums, "prob"].sum())
        sets.append({
            "name": name,
            "numbers": sorted(nums),
            "pb": pb_rank[i % len(pb_rank)],
            "reasoning": why,
            "confidence": confidence,
        })
    sets.sort(key=lambda s: -s["confidence"])
    return sets


def main() -> int:
    try:
        sets = build_candidate_sets()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    section("Candidate sets (ranked by combined model confidence)")
    for rank, s in enumerate(sets, 1):
        subsection(f"{rank}. {s['name']}")
        print(f"  Numbers:   {s['numbers']}")
        print(f"  Powerball: {s['pb']}")
        print(f"  Confidence: {s['confidence']:.4f}")
        print(f"  Why:       {s['reasoning']}")
    print()
    print("Note: all sets are ~equally (un)likely under a fair draw; the")
    print("ranking expresses model confidence, not an edge.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
