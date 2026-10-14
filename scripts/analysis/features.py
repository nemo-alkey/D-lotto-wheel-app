"""Build the (draw, number) feature matrix for the ML framings.

Prompt pack: ML feature engineering. Writes data/features.parquet.

One row per (draw, number) pair so a per-number classifier can consume it
directly. The era flag goes through era_features (never hand-derived).
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import main_number_draws, section  # noqa: E402

import era_features  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT = REPO_ROOT / "data" / "features.parquet"

NUM_POOL = 40


def build_feature_rows(draws: list[dict]) -> list[dict]:
    """Return one row dict per (draw, number)."""
    flags = era_features.era_flags(draws)
    freq10: Counter = Counter()
    freq50: Counter = Counter()
    freq200: Counter = Counter()
    recent: list[set[int]] = []
    last_seen = {n: -1 for n in range(1, NUM_POOL + 1)}
    cooc = [[0] * (NUM_POOL + 1) for _ in range(NUM_POOL + 1)]
    prev_nums: set[int] = set()

    rows: list[dict] = []
    for i, d in enumerate(draws):
        nums = set(d["numbers"])
        dt = date.fromisoformat(d["draw_date"])
        is_wed = 1 if dt.weekday() == 2 else 0
        era = flags[i]

        for n in range(1, NUM_POOL + 1):
            draws_since = i - last_seen[n] if last_seen[n] >= 0 else i + 1
            cooccur_score = sum(cooc[n][m] for m in prev_nums if m != n) / max(1, i)
            rows.append({
                "draw_number": d["draw_number"],
                "draw_date": d["draw_date"],
                "number": n,
                "rolled_freq_10": freq10.get(n, 0),
                "rolled_freq_50": freq50.get(n, 0),
                "rolled_freq_200": freq200.get(n, 0),
                "draws_since": draws_since,
                "cooccur_score": cooccur_score,
                "is_wednesday": is_wed,
                "era_flag": era,
                "hit": 1 if n in nums else 0,
            })

        # advance state with this draw
        for n in nums:
            freq10[n] += 1
            freq50[n] += 1
            freq200[n] += 1
            last_seen[n] = i
        for a in nums:
            for b in nums:
                if a < b:
                    cooc[a][b] += 1
                    cooc[b][a] += 1
        recent.append(nums)
        length = len(recent)
        if length > 10:
            for n in recent[length - 11]:
                freq10[n] -= 1
        if length > 50:
            for n in recent[length - 51]:
                freq50[n] -= 1
        if length > 200:
            for n in recent[length - 201]:
                freq200[n] -= 1
        prev_nums = nums

    return rows


def next_draw_frame(draws: list[dict]) -> "pd.DataFrame":
    """Feature rows (one per number, 40) for the hypothetical NEXT draw.

    Uses the final rolling state so a trained model can rank numbers for the
    upcoming draw. Requires pandas at call time.
    """
    import pandas as pd

    freq10: Counter = Counter()
    freq50: Counter = Counter()
    freq200: Counter = Counter()
    recent: list[set[int]] = []
    last_seen = {n: -1 for n in range(1, NUM_POOL + 1)}
    cooc = [[0] * (NUM_POOL + 1) for _ in range(NUM_POOL + 1)]
    prev_nums: set[int] = set()

    for i, d in enumerate(draws):
        nums = set(d["numbers"])
        for n in nums:
            freq10[n] += 1
            freq50[n] += 1
            freq200[n] += 1
            last_seen[n] = i
        for a in nums:
            for b in nums:
                if a < b:
                    cooc[a][b] += 1
                    cooc[b][a] += 1
        recent.append(nums)
        length = len(recent)
        if length > 10:
            for n in recent[length - 11]:
                freq10[n] -= 1
        if length > 50:
            for n in recent[length - 51]:
                freq50[n] -= 1
        if length > 200:
            for n in recent[length - 201]:
                freq200[n] -= 1
        prev_nums = nums

    last_date = date.fromisoformat(draws[-1]["draw_date"])
    next_date = last_date + timedelta(days=3 if last_date.weekday() == 5 else 4)
    is_wed = 1 if next_date.weekday() == 2 else 0
    n_draws = len(draws)

    rows = []
    for n in range(1, NUM_POOL + 1):
        rows.append({
            "number": n,
            "rolled_freq_10": freq10.get(n, 0),
            "rolled_freq_50": freq50.get(n, 0),
            "rolled_freq_200": freq200.get(n, 0),
            "draws_since": (n_draws - 1) - last_seen[n] if last_seen[n] >= 0 else n_draws,
            "cooccur_score": sum(cooc[n][m] for m in prev_nums if m != n) / max(1, n_draws - 1),
            "is_wednesday": is_wed,
            "era_flag": 1,
        })
    return pd.DataFrame(rows)


def main() -> int:
    import pandas as pd

    draws = main_number_draws()
    print(f"Loaded {len(draws)} draws")
    if not draws:
        print("ERROR: no draws.")
        return 1

    rows = build_feature_rows(draws)
    frame = pd.DataFrame(rows)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT, index=False)

    section("Feature matrix")
    print(f"Wrote: {OUT}")
    print(f"Shape: {frame.shape}")
    print(f"Columns: {list(frame.columns)}")
    print()
    print("Sample 5 rows:")
    print(frame.head(5).to_string(index=False))

    section("Sanity")
    print(f"Rows per draw (expect {NUM_POOL}): "
          f"{frame.groupby('draw_number').size().mean():.1f}")
    print(f"Hit rate (expect ~6/40={6 / NUM_POOL:.3f}): "
          f"{frame['hit'].mean():.4f}")
    print(f"Era flags present: {sorted(frame['era_flag'].unique().tolist())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
