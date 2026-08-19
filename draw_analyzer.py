"""Barrier / draw bias analyser for Australian thoroughbred racing.

Queries the processed feature store, computes per-barrier performance
relative to the field, tests for statistically significant bias using
95 % confidence intervals, and caches results for downstream use.

Usage::

    python draw_analyzer.py                     # build full cache
    python draw_analyzer.py --track Flemington --distance 1200

Reference: *Forecasting Methods for Horseracing* ch.3, Figure 3.14.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT = Path(__file__).resolve().parent
_FEATURE_STORE = _PROJECT / "features" / "processed_races.parquet"
_CACHE_PATH = _PROJECT / "barrier_bias_cache.csv"
_MIN_RACES = 5  # minimum races per track/distance before analysis
POINTS_PER_LENGTH = 2.0  # from speed_figure_engine: 1 length ≈ 2 speed-figure pts

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_feature_store(path: Path | None = None) -> pd.DataFrame:
    """Return the processed feature-store DataFrame."""
    path = Path(path) if path else _FEATURE_STORE
    if not path.exists():
        raise FileNotFoundError(f"Feature store not found: {path}")
    return pd.read_parquet(path)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def analyze_barrier_bias(
    df: pd.DataFrame,
    track: str,
    distance: int,
    min_races: int = _MIN_RACES,
) -> pd.DataFrame:
    """Compute per-barrier bias statistics for a specific track/distance.

    Uses *speed_figure* rank within each race as a proxy for finish
    position.  Higher speed figure → lower (better) rank.

    Args:
        df: Full feature store DataFrame.
        track: Track name (must match the ``Track`` column).
        distance: Race distance in metres.
        min_races: Minimum number of races required for analysis.

    Returns:
        DataFrame with columns ``barrier, adv_lengths, ci_lower, ci_upper,
        n_runners, n_races, significant``, or an empty DataFrame if
        insufficient data.
    """
    mask = (df["Track"] == track) & (df["distance_m"] == distance)
    subset = df.loc[mask].copy()
    if subset.empty:
        log.warning("No data for %s %dm", track, distance)
        return pd.DataFrame()

    race_count = subset["race_id"].nunique()
    if race_count < min_races:
        log.info(
            "Skipping %s %dm — only %d race(s), need %d", track, distance, race_count, min_races
        )
        return pd.DataFrame()

    # ---- Rank horses within each race by speed_figure (proxy finish) -------
    subset["_finish_rank"] = subset.groupby("race_id")["speed_figure"].rank(
        ascending=False, method="average"
    )

    # ---- Convert rank to an "advantage" metric ----------------------------
    # A horse that is rank 1 gets large positive advantage;
    # a horse that is last gets negative.
    # We compute mean speed_figure per barrier vs field mean for the race,
    # then convert the delta to lengths.
    race_mean_fig = subset.groupby("race_id")["speed_figure"].transform("mean")
    subset["_fig_vs_field"] = subset["speed_figure"] - race_mean_fig
    # Convert to lengths: lengths = fig_delta / POINTS_PER_LENGTH
    subset["_lengths_vs_field"] = subset["_fig_vs_field"] / POINTS_PER_LENGTH

    # ---- Aggregate by barrier ---------------------------------------------
    barrier_groups = subset.groupby("barrier_num")
    rows: list[dict[str, Any]] = []

    for barrier, grp in barrier_groups:
        n = len(grp)
        if n < 2:
            continue  # need at least 2 data points for CI

        vals = grp["_lengths_vs_field"].values
        mean_adv = float(np.mean(vals))
        sem = stats.sem(vals) if n > 1 else 0.0
        dof = n - 1

        ci_lower, ci_upper = stats.t.interval(0.95, df=dof, loc=mean_adv, scale=sem)

        rows.append(
            {
                "track": track,
                "distance": distance,
                "barrier": int(barrier),
                "adv_lengths": round(mean_adv, 4),
                "ci_lower": round(float(ci_lower), 4),
                "ci_upper": round(float(ci_upper), 4),
                "n_runners": n,
                "n_races": race_count,
                "significant": ci_lower > 1.0,
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result.sort_values("barrier", inplace=True)
        result.reset_index(drop=True, inplace=True)

    return result


def build_bias_cache(
    df: pd.DataFrame | None = None,
    output_path: Path | None = None,
    min_races: int = _MIN_RACES,
) -> pd.DataFrame:
    """Analyse every track/distance combination and write the cache CSV.

    Returns the combined cache DataFrame.
    """
    if df is None:
        df = load_feature_store()
    output_path = Path(output_path) if output_path else _CACHE_PATH

    track_dist_pairs = (
        df.groupby(["Track", "distance_m"]).size().reset_index(name="count").drop(columns=["count"])
    )

    frames: list[pd.DataFrame] = []
    for _, row in track_dist_pairs.iterrows():
        track = str(row["Track"])
        distance = int(row["distance_m"])
        result = analyze_barrier_bias(df, track, distance, min_races)
        if not result.empty:
            frames.append(result)

    if not frames:
        log.warning("No track/distance combinations had enough data for analysis")
        return pd.DataFrame()

    cache = pd.concat(frames, ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache.to_csv(output_path, index=False)
    log.info("Wrote barrier bias cache (%d rows) to %s", len(cache), output_path)
    return cache


# ---------------------------------------------------------------------------
# Adjustment factor for downstream use
# ---------------------------------------------------------------------------


def get_barrier_adjustment(
    horse_df: pd.DataFrame,
    cache_df: pd.DataFrame | None = None,
    cache_path: Path | None = None,
) -> pd.Series:
    """Return a win-probability multiplier for each horse based on its draw.

    Args:
        horse_df: DataFrame with columns ``Track``, ``distance_m``, ``barrier_num``.
        cache_df: Pre-loaded bias cache.  Loaded from *cache_path* if None.
        cache_path: Path to ``barrier_bias_cache.csv``.

    Returns:
        Series of adjustment factors.  1.0 = no bias; >1.0 = favourable;
        <1.0 = unfavourable.  Horses whose track/distance/barrier is not
        in the cache receive 1.0.
    """
    if cache_df is None:
        path = Path(cache_path) if cache_path else _CACHE_PATH
        if not path.exists():
            log.warning("Barrier cache not found at %s — returning neutral adjustments", path)
            return pd.Series(1.0, index=horse_df.index, name="barrier_adj")
        cache_df = pd.read_csv(path)

    horse_df = horse_df.copy()
    horse_df["_idx"] = range(len(horse_df))

    merged = horse_df.merge(
        cache_df,
        how="left",
        left_on=["Track", "distance_m", "barrier_num"],
        right_on=["track", "distance", "barrier"],
    )

    # Convert advantage in lengths to a probability multiplier.
    # 1 length advantage ≈ 1.8–2.2 % win probability bump (empirical).
    # We use a sigmoid: multiplier = 1 + tanh(adv / scale)
    # For adv in [-3, +3] this gives multipliers ~[0.85, 1.15].
    def _lengths_to_multiplier(adv: float) -> float:
        if pd.isna(adv):
            return 1.0
        return round(float(1.0 + np.tanh(adv / 3.0) * 0.35), 4)

    merged["barrier_adj"] = merged["adv_lengths"].apply(_lengths_to_multiplier)
    result = merged.set_index("_idx").sort_index()["barrier_adj"]
    result.name = "barrier_adj"
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_significant_barriers(cache_path: Path | None = None) -> None:
    """Print a summary of significantly biased barriers to stdout."""
    path = Path(cache_path) if cache_path else _CACHE_PATH
    if not path.exists():
        print(f"No cache found at {path}")
        return

    cache = pd.read_csv(path)
    sig = cache[cache["significant"]]
    if sig.empty:
        print("No significantly biased barriers found.")
        return

    print("\nSignificantly biased barriers (CI entirely > +1.0 lengths):\n")
    print(
        f"{'Track':<25s} {'Dist':>5s} {'Bar':>4s} {'Adv':>8s} {'CI Low':>8s} {'CI High':>8s} {'N':>5s}"
    )
    print("-" * 75)
    for _, r in sig.iterrows():
        print(
            f"{r['track']:<25s} {r['distance']:>5d} {r['barrier']:>4d} "
            f"{r['adv_lengths']:>+8.2f} {r['ci_lower']:>8.2f} "
            f"{r['ci_upper']:>8.2f} {r['n_runners']:>5d}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Barrier / draw bias analyser")
    parser.add_argument(
        "--track",
        type=str,
        default=None,
        help="Analyse a specific track (default: all tracks)",
    )
    parser.add_argument(
        "--distance",
        type=int,
        default=None,
        help="Analyse a specific distance in metres",
    )
    parser.add_argument(
        "--min-races",
        type=int,
        default=_MIN_RACES,
        help=f"Minimum races per track/distance (default: {_MIN_RACES})",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=_CACHE_PATH,
        help="Path to barrier bias cache CSV",
    )
    args = parser.parse_args()

    df = load_feature_store()

    if args.track and args.distance:
        result = analyze_barrier_bias(df, args.track, args.distance, args.min_races)
        if result.empty:
            print(f"No data for {args.track} {args.distance}m")
            sys.exit(1)
        print(result.to_string(index=False))
    else:
        cache = build_bias_cache(df, args.cache, args.min_races)
        if cache.empty:
            sys.exit(1)
        print_significant_barriers(args.cache)


if __name__ == "__main__":
    main()
