#!/usr/bin/env python3
"""
Racing Model Training Pipeline.

Loads all available CSV race data, performs feature engineering,
trains an XGBoost (or GradientBoosting fallback) model to predict
finish positions, saves the model, and logs a training report.

Usage:
    python train_model.py
    python train_model.py --data-dir /path/to/csvs
    python train_model.py --target win_prob  # predict win probability instead of position
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ML imports — XGBoost preferred, sklearn fallback
try:
    import xgboost as xgb

    HAS_XGBOOST = True
    MODEL_LIB = "xgboost"
except ImportError:
    HAS_XGBOOST = False
    from sklearn.ensemble import GradientBoostingRegressor

    MODEL_LIB = "sklearn.GradientBoostingRegressor"

# Enriched-text → numeric feature extractors
from typing import Any

from features.enriched_features import extract_enriched_features
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import train_test_split

# Enrichment toggles from central config (imported early for config section)
from src.config import (
    ENRICHED_DATA_DIR,
    LIVE_ODDS_ENABLED,
    LIVE_ODDS_SOURCE,
    SECTIONAL_SCRAPING_ENABLED,
    USE_PDF_PARSING,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Data sources — all known CSV locations from recovered files
PROJECT_ROOT = Path(__file__).resolve().parent

# Data sources — override via --data-dir CLI flag or RACING_DATA_DIRS env var
_DEFAULT_DATA_DIRS = [
    str(PROJECT_ROOT / "data" / "raw"),
    str(PROJECT_ROOT / "data" / "races"),
]
if USE_PDF_PARSING:
    enriched = PROJECT_ROOT / ENRICHED_DATA_DIR
    if enriched.is_dir():
        # Prefer enriched CSVs when available; fall back to originals otherwise
        enriched_files = sorted(enriched.glob("*_enriched.csv"))
        if enriched_files:
            _DEFAULT_DATA_DIRS = [str(enriched)]
        else:
            _DEFAULT_DATA_DIRS.append(str(enriched))
_EXTRA_DATA_DIRS = [d for d in os.environ.get("RACING_DATA_DIRS", "").split(":") if d]
DATA_SOURCES = _DEFAULT_DATA_DIRS + _EXTRA_DATA_DIRS
MODEL_DIR = PROJECT_ROOT / "models"
LOG_DIR = PROJECT_ROOT / "logs"

# Columns to exclude from feature set
EXCLUDE_COLS = {
    "Num",
    "Horse Name",
    "HorseName",
    "Jockey",
    "Trainer",
    "Form Guide Url",
    "Horse Profile Url",
    "Jockey Profile Url",
    "Trainer Profile Url",
    "Finish Result (Updates after race)",
    "Date",
    "RaceID",
    "Race ID",
    "race_id",
    "race_name",
    "Track",
    "Race Name",
    "Predicted_Position",
    "Position",
    "Odds",
    "Last 5 Form",
    # Enriched text columns — feature-engineered separately
    "Last_10",
    "last_10",
    "Gear_Change",
    "gear_change",
    "Gear Changes",
    "Sectional_400",
    "sectional_400",
    "Sectional 400",
    "Sectional_800",
    "sectional_800",
    "Sectional 800",
    "Sectional_1200",
    "sectional_1200",
    "Sectional 1200",
    "Early Speed Rating",
    "Sustained Speed Rating",
    "Finishing Speed Rating",
}

# Percentage columns (values like 16.67 mean 16.67%, should be divided by 100)
PCT_COLS_PATTERNS = ["Strike Rate", "ROI", "Place Strike Rate"]

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"training_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("train_model")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def discover_csv_files(data_sources: list[str], log: logging.Logger) -> list[Path]:
    """Find all CSV files across configured data sources."""
    csv_files: list[Path] = []
    for src in data_sources:
        p = Path(src)
        if p.is_dir():
            found = list(p.glob("*.csv"))
            # Filter out prediction/bet/result/sample CSVs (different schemas)
            found = [
                f
                for f in found
                if not any(
                    kw in f.name.lower()
                    for kw in ["prediction", "result", "bet", "sample", "demo", "dummy", "test.csv"]
                )
            ]
            csv_files.extend(found)
            log.info(f"  {src}: {len(found)} CSV files")
        else:
            log.info(f"  {src}: not found (skipped)")
    return sorted(set(csv_files))


def load_all_data(csv_files: list[Path], log: logging.Logger) -> pd.DataFrame:
    """Load and concatenate all CSV files into a single DataFrame."""
    frames = []
    failed = 0
    for f in csv_files:
        try:
            df = pd.read_csv(f)
            # Add source tracking
            df["_source_file"] = f.name
            frames.append(df.copy())  # copy to avoid fragmentation
        except Exception as e:
            failed += 1
            log.debug(f"  Skipping {f.name}: {e}")

    if not frames:
        raise RuntimeError("No CSV files could be loaded")

    df = pd.concat(frames, ignore_index=True)
    log.info(f"  Loaded {len(frames)} files ({failed} failed), {len(df)} total rows")
    return df


def enrich_with_live_odds(df: pd.DataFrame, log: logging.Logger) -> pd.DataFrame:
    """Fetch live odds for each unique race URL and merge into the DataFrame.

    Requires a ``Form Guide Url`` column in *df* (present in enriched CSVs).
    When live odds are available, a ``Live_Odds`` column is added and
    ``Best Fixed Odds`` is backfilled where the existing value was null.
    """
    url_col = "Form Guide Url"
    from data_ingestion.scrapers.live_odds_scraper import update_race_odds

    if url_col not in df.columns:
        log.warning("  No '%s' column — skipping live odds enrichment", url_col)
        return df

    race_urls = df[url_col].dropna().unique()
    if not len(race_urls):
        log.warning("  No race URLs found — skipping live odds enrichment")
        return df

    log.info("  Fetching live odds for %d race(s) from '%s' ...", len(race_urls), LIVE_ODDS_SOURCE)
    enriched_frames: list[pd.DataFrame] = []
    ok = 0
    for url in race_urls:
        race_df = df[df[url_col] == url].copy()
        try:
            result = update_race_odds(race_df, url, name_col="Horse Name")
            enriched_frames.append(result)
            ok += 1
        except Exception as e:
            log.warning("  Live odds fetch failed for %s …: %s", url[:60], e)
            enriched_frames.append(race_df)

    result = pd.concat(enriched_frames, ignore_index=True)
    matched = result["Live_Odds"].notna().sum() if "Live_Odds" in result.columns else 0
    log.info(
        "  Live odds fetched for %d/%d race(s); matched %d / %d horses",
        ok,
        len(race_urls),
        matched,
        len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Cleaning & Feature Engineering
# ---------------------------------------------------------------------------


def clean_data(df: pd.DataFrame, log: logging.Logger) -> pd.DataFrame:
    """Minimal cleaning of the raw DataFrame."""
    initial = len(df)

    # Drop fully empty columns
    df = df.dropna(axis=1, how="all")

    # Drop rows where all key fields are NaN
    key_cols = [c for c in df.columns if c not in ("_source_file",)]
    df = df.dropna(subset=key_cols[:5], how="all")

    # Strip whitespace from string columns
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].str.strip()

    log.info(f"  Cleaned: {initial} → {len(df)} rows ({initial - len(df)} removed)")
    return df


def engineer_features(df: pd.DataFrame, log: logging.Logger) -> tuple[pd.DataFrame, list[str]]:
    """Engineer features from the raw CSV columns.

    Returns (feature_df, feature_name_list).
    """
    # Step 0: Extract numeric features from enriched text columns (Last_10,
    # Gear_Change, Sectional_*) BEFORE numeric coercion wipes them out.
    enriched_features = extract_enriched_features(df)

    # Force numeric conversion for all columns that look numeric
    for col in df.columns:
        if col in EXCLUDE_COLS or col == "_source_file":
            continue
        with contextlib.suppress(Exception):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Identify numeric columns after coercion
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    # Remove excluded columns
    feature_cols = [c for c in numeric_cols if c not in EXCLUDE_COLS]

    # Convert percentage columns from 0-100 scale to 0-1
    pct_cols = [c for c in feature_cols if any(p in c for p in PCT_COLS_PATTERNS)]
    for col in pct_cols:
        # If values are consistently > 1, they're in percentage form
        median_val = df[col].dropna().median() if not df[col].dropna().empty else 0
        if median_val > 1.0:
            df[col] = df[col] / 100.0

    # Fill remaining NaN with median (handle all-NaN columns)
    for col in feature_cols:
        if df[col].isna().all():
            df[col] = 0.0
        else:
            df[col] = df[col].fillna(df[col].median())

    # Final safety: ensure no NaN in feature matrix
    for col in feature_cols:
        if df[col].isna().any():
            df[col] = df[col].fillna(0.0)

    # Derived features
    derived = {}

    # Win/run ratios
    if "Career Wins" in df.columns and "Career Runs" in df.columns:
        derived["Derived_CareerWinRate"] = df["Career Wins"] / (df["Career Runs"] + 1)

    if "This Track Wins" in df.columns and "This Track Runs" in df.columns:
        derived["Derived_TrackWinRate"] = df["This Track Wins"] / (df["This Track Runs"] + 1)

    if "This Distance Wins" in df.columns and "This Distance Runs" in df.columns:
        derived["Derived_DistanceWinRate"] = df["This Distance Wins"] / (
            df["This Distance Runs"] + 1
        )

    # Weight advantage (lower = better)
    if "Weight Carried" in df.columns:
        derived["Derived_WeightAdvantage"] = 62.0 - df["Weight Carried"]

    # Barrier advantage (inside = better)
    if "Barrier" in df.columns:
        derived["Derived_BarrierScore"] = 1.0 - (df["Barrier"] - 1) / 23.0

    # Odds-based implied probability — prefer Live_Odds when available
    live_odds_col = "Live_Odds" if "Live_Odds" in df.columns else None
    fixed_odds_col = "Best Fixed Odds" if "Best Fixed Odds" in df.columns else None
    odds_col = live_odds_col or fixed_odds_col
    if odds_col:
        derived["Derived_ImpliedProb"] = 1.0 / df[odds_col].clip(lower=1.01)

    # Jockey + Trainer combined strike rate
    jockey_sr_cols = [c for c in df.columns if "Jockey" in c and "Strike Rate" in c and "100" in c]
    trainer_sr_cols = [
        c for c in df.columns if "Trainer" in c and "Strike Rate" in c and "100" in c
    ]
    if jockey_sr_cols and trainer_sr_cols:
        jsr = df[jockey_sr_cols[0]].fillna(0)
        tsr = df[trainer_sr_cols[0]].fillna(0)
        derived["Derived_StablePower"] = (jsr + tsr) / 2.0

    # Age factor: peak at age 5-6
    if "Age" in df.columns:
        age = df["Age"].clip(2, 12)
        derived["Derived_AgeScore"] = 1.0 - abs(age - 5.5) / 6.0

    # Enriched columns: extracted numeric features from Last_10 / Gear_Change / Sectional_*
    for name, series in enriched_features.items():
        derived[name] = series

    # Enriched columns: odds drift (live vs fixed)
    if "Live_Odds" in df.columns and "Best Fixed Odds" in df.columns:
        diff = df["Live_Odds"].fillna(0) - df["Best Fixed Odds"].fillna(0)
        derived["Derived_OddsDrift"] = diff.clip(-50, 50)

    # Add derived features to DataFrame in one batch
    derived_df = pd.DataFrame(
        {name: np.asarray(values, dtype=float) for name, values in derived.items()},
        index=df.index,
    )
    for name in derived:
        feature_cols.append(name)
    df = pd.concat([df, derived_df], axis=1)

    log.info(
        f"  Features: {len(feature_cols)} selected ({len(pct_cols)} percentage-normalised, "
        f"{len(derived)} derived)"
    )

    return df, feature_cols


# ---------------------------------------------------------------------------
# Target generation
# ---------------------------------------------------------------------------


def generate_target(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_mode: str = "position",
    log: logging.Logger | None = None,
) -> tuple[np.ndarray, str]:
    """Generate training target.

    If real race results (finish positions) are available in the raw CSV
    columns, they are used directly.  Otherwise a clear warning is emitted
    and the function returns None to halt training — synthetic targets
    produce misleading metrics and must not be used for production models.

    target_mode:
        "position" — predict finish position (1-12, lower is better)
        "win_prob" — predict win probability (0-1, higher is better)

    Real position columns (checked in order):
        - "Position"
        - "Finish Position"
        - "finish_position"
        - "Finish Result (Updates after race)"
    """
    # ---- Check for real finish positions ----------------------------------
    position_candidates = [
        "Position",
        "Finish Position",
        "finish_position",
        "Finish Result (Updates after race)",
    ]
    real_position_col = None
    for col in position_candidates:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            if vals.notna().sum() > len(df) * 0.5:  # >50% populated
                real_position_col = col
                break

    if real_position_col:
        positions = pd.to_numeric(df[real_position_col], errors="coerce").fillna(99)
        if target_mode == "win_prob":
            target = (positions == 1).astype(float).values
            target_name = "win_probability"
        else:
            target = positions.clip(1, 20).values.astype(float)
            target_name = "finish_position"
        if log:
            log.info(
                f"  Target: {target_name} from real column '{real_position_col}' "
                f"— range [{target.min():.0f}, {target.max():.0f}], "
                f"mean={target.mean():.2f}"
            )
        return target, target_name

    # ---- No real results available — warn and halt ------------------------
    msg = (
        "No real race results found in data. "
        "Synthetic targets produce misleading metrics. "
        "Expected one of: " + ", ".join(position_candidates) + ". "
        "Train with --synthetic-only to generate synthetic data for "
        "pipeline development only."
    )
    if log:
        log.error("  " + msg)
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------


def train_model(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    feature_names: list[str],
    log: logging.Logger,
) -> tuple[object, dict[str, Any]]:
    """Train XGBoost (or GradientBoosting fallback) model."""
    log.info(f"  Library: {MODEL_LIB}")

    if HAS_XGBOOST:
        model = xgb.XGBRegressor(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            reg_alpha=0.1,
            random_state=42,
            n_jobs=-1,
        )
    else:
        model = GradientBoostingRegressor(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )

    log.info(f"  Training on {len(x_train):,} samples, {x_train.shape[1]} features...")
    t0 = time.time()
    model.fit(x_train, y_train)
    elapsed = time.time() - t0
    log.info(f"  Training complete in {elapsed:.1f}s")

    # Predictions
    train_pred = model.predict(x_train)
    val_pred = model.predict(x_val)

    # Metrics
    metrics = {
        "library": MODEL_LIB,
        "train_samples": len(x_train),
        "val_samples": len(x_val),
        "n_features": x_train.shape[1],
        "n_estimators": 200,
        "training_time_sec": round(elapsed, 1),
        "train_mae": round(float(mean_absolute_error(y_train, train_pred)), 4),
        "val_mae": round(float(mean_absolute_error(y_val, val_pred)), 4),
        "train_mse": round(float(mean_squared_error(y_train, train_pred)), 4),
        "val_mse": round(float(mean_squared_error(y_val, val_pred)), 4),
        "train_r2": round(float(r2_score(y_train, train_pred)), 4),
        "val_r2": round(float(r2_score(y_val, val_pred)), 4),
    }

    # Feature importance
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
        top_indices = np.argsort(importances)[-20:][::-1]
        metrics["top_features"] = [
            {"feature": feature_names[i], "importance": round(float(importances[i]), 4)}
            for i in top_indices
        ]

    for k, v in metrics.items():
        if k != "top_features":
            log.info(f"  {k}: {v}")

    if "top_features" in metrics:
        log.info("  Top 5 features:")
        for f in metrics["top_features"][:5]:
            log.info(f"    {f['feature']:40s} {f['importance']:.4f}")

    return model, metrics


# ---------------------------------------------------------------------------
# Model persistence
# ---------------------------------------------------------------------------


def save_model(
    model: Any,
    metrics: dict[str, Any],
    feature_names: list[str],
    model_dir: Path,
    log: logging.Logger,
) -> None:
    """Save model, feature names, and metadata."""
    model_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save model
    import joblib

    model_path = model_dir / f"racing_model_{ts}.pkl"
    joblib.dump(model, model_path)
    log.info(f"  Model saved: {model_path}")

    # Save latest (symlink on Linux, copy on Windows)
    latest_path = model_dir / "racing_model_latest.pkl"
    if latest_path.exists():
        latest_path.unlink()
    try:
        latest_path.symlink_to(model_path.name)
        log.info(f"  Latest link: {latest_path}")
    except OSError:
        import shutil

        shutil.copy2(model_path, latest_path)
        log.info(f"  Latest copy: {latest_path}")

    # Save feature names
    meta_path = model_dir / f"model_metadata_{ts}.json"
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "feature_names": feature_names,
        "n_features": len(feature_names),
        "metrics": {k: v for k, v in metrics.items() if k != "top_features"},
        "top_features": metrics.get("top_features", []),
        "library": MODEL_LIB,
    }
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    log.info(f"  Metadata saved: {meta_path}")


# ---------------------------------------------------------------------------
# Training report
# ---------------------------------------------------------------------------


def write_training_report(
    metrics: dict[str, Any],
    feature_names: list[str],
    target_name: str,
    log_dir: Path,
    log: logging.Logger,
) -> None:
    """Write a Markdown training report to logs/."""
    log_dir.mkdir(parents=True, exist_ok=True)
    report_path = log_dir / "training_report.md"

    lines = [
        f"# Training Report — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Configuration",
        "",
        "| Parameter | Value |",
        "|-----------|-------|",
        f"| ML Library | {MODEL_LIB} |",
        f"| Target | {target_name} |",
        f"| Training samples | {metrics['train_samples']:,} |",
        f"| Validation samples | {metrics['val_samples']:,} |",
        f"| Features | {metrics['n_features']} |",
        f"| Estimators | {metrics['n_estimators']} |",
        f"| Training time | {metrics['training_time_sec']:.1f}s |",
        "",
        "## Performance",
        "",
        "| Metric | Train | Validation |",
        "|--------|-------|------------|",
        f"| MAE | {metrics['train_mae']:.4f} | {metrics['val_mae']:.4f} |",
        f"| MSE | {metrics['train_mse']:.4f} | {metrics['val_mse']:.4f} |",
        f"| R² | {metrics['train_r2']:.4f} | {metrics['val_r2']:.4f} |",
        "",
        "## Top 20 Feature Importance",
        "",
        "| Rank | Feature | Importance |",
        "|------|---------|------------|",
    ]

    if "top_features" in metrics:
        for i, f in enumerate(metrics["top_features"][:20], 1):
            lines.append(f"| {i} | {f['feature']} | {f['importance']:.4f} |")
    else:
        lines.append("| — | Feature importance not available | — |")

    lines += [
        "",
        "## Feature Summary",
        "",
        f"- **{len(feature_names)}** total features",
        f"- **{len([c for c in feature_names if c.startswith('Derived_')])}** derived features",
        f"- **{len([c for c in feature_names if 'Strike Rate' in c])}** strike-rate features",
        f"- **{len([c for c in feature_names if 'Jockey' in c])}** jockey features",
        f"- **{len([c for c in feature_names if 'Trainer' in c])}** trainer features",
        "",
        "## Notes",
        "",
        "- Target is **synthetic** — generated from domain-weighted features since post-race results are not available in the recovered data.",
        "- Replace `generate_target()` with actual `Finish Position` column when results become available.",
        "- Retrain daily/weekly as new race data arrives for best performance.",
    ]

    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    log.info(f"  Report written: {report_path}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def main(
    data_sources: list[str] | None = None,
    target_mode: str = "position",
) -> tuple[Any, dict[str, Any]]:
    """Run the full training pipeline."""
    if data_sources is None:
        data_sources = DATA_SOURCES

    log = setup_logging(LOG_DIR)

    log.info("=" * 60)
    log.info("  RACING MODEL TRAINING PIPELINE")
    log.info("=" * 60)
    log.info(f"  Target mode: {target_mode}")
    log.info(f"  ML Library:  {MODEL_LIB}")
    log.info(
        f"  PDF parsing: {'ON' if USE_PDF_PARSING else 'OFF'} "
        f"(enriched dir: {ENRICHED_DATA_DIR})"
    )
    log.info(f"  Live odds:   {'ON' if LIVE_ODDS_ENABLED else 'OFF'}")
    log.info(f"  Sectionals:  {'ON' if SECTIONAL_SCRAPING_ENABLED else 'OFF'}")
    if LIVE_ODDS_ENABLED:
        log.info("  Live odds enabled — call update_race_odds() per race URL before training")
    if SECTIONAL_SCRAPING_ENABLED:
        log.info("  Sectional scraping enabled — call scrape_sectionals() and merge per race")

    # 1. Discover CSV files
    log.info("\n[1/6] Discovering CSV files...")
    csv_files = discover_csv_files(data_sources, log)
    log.info(f"  Total CSV files found: {len(csv_files)}")

    # 2. Load data
    log.info("\n[2/6] Loading data...")
    df = load_all_data(csv_files, log)

    # ── Live odds enrichment (optional step between load and feature engineering)
    if LIVE_ODDS_ENABLED:
        log.info("\n[2b/6] Enriching with live odds...")
        df = enrich_with_live_odds(df, log)

    # 3. Clean and engineer features
    log.info("\n[3/6] Cleaning and engineering features...")
    df = clean_data(df, log)
    df, feature_names = engineer_features(df, log)

    # 4. Generate target
    log.info("\n[4/6] Generating target...")
    y, target_name = generate_target(df, feature_names, target_mode, log)

    # Extract feature matrix
    x = df[feature_names].values.astype(np.float32)

    # 5. Train model
    log.info("\n[5/6] Training model...")
    x_train, x_val, y_train, y_val = train_test_split(
        x,
        y,
        test_size=0.2,
        random_state=42,
    )

    model, metrics = train_model(x_train, y_train, x_val, y_val, feature_names, log)

    # 6. Save and report
    log.info("\n[6/6] Saving model and report...")
    save_model(model, metrics, feature_names, MODEL_DIR, log)
    write_training_report(metrics, feature_names, target_name, LOG_DIR, log)

    log.info("\n" + "=" * 60)
    log.info("  PIPELINE COMPLETE")
    log.info(f"  Model: {MODEL_DIR}/racing_model_latest.pkl")
    log.info(f"  Report: {LOG_DIR}/training_report.md")
    log.info("=" * 60)

    return model, metrics


# ---------------------------------------------------------------------------
# Cross-validation and calibration
# ---------------------------------------------------------------------------


def cross_validate_time_series(
    x: np.ndarray, y: np.ndarray, feature_names: list[str], log: logging.Logger, n_splits: int = 5
) -> tuple[list[dict[str, Any]], Any]:
    """5-fold time-series CV. Returns metrics list and final model."""
    import json

    from sklearn.model_selection import TimeSeriesSplit

    tscv = TimeSeriesSplit(n_splits=n_splits)
    metrics = []
    log.info("Starting %d-fold time-series cross-validation...", n_splits)

    for fold, (train_idx, val_idx) in enumerate(tscv.split(x), 1):
        x_tr, x_val = x[train_idx], x[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]
        model, fold_m = train_model(x_tr, y_tr, x_val, y_val, feature_names, log)
        metrics.append({**fold_m, "fold": fold, "samples": len(y_val)})
        log.info(
            "  Fold %d: val_mae=%.4f  train_mae=%.4f",
            fold,
            fold_m.get("val_mae", 0),
            fold_m.get("train_mae", 0),
        )

    out = Path("logs/cv_metrics.json")
    avg_mae = np.mean([m["val_mae"] for m in metrics])
    with open(out, "w") as f:
        json.dump({"folds": metrics, "mean_val_mae": round(float(avg_mae), 4)}, f, indent=2)
    log.info("CV metrics saved to %s", out)
    return metrics, model


def _plot_calibration(
    y_true: Any, y_pred: Any, log: logging.Logger
) -> None:  # y_* may be pandas Series
    """Save calibration curve to logs/calibration.png."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.calibration import calibration_curve

        frac_pos, mean_pred = calibration_curve(y_true > y_true.median(), y_pred, n_bins=10)
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot(mean_pred, frac_pos, "s-", label="Model")
        ax.plot([0, 1], [0, 1], "k--", label="Perfect")
        ax.set_xlabel("Mean Predicted Value")
        ax.set_ylabel("Fraction Above Median")
        ax.set_title("Calibration Curve")
        ax.legend()
        fig.savefig("logs/calibration.png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        log.info("Calibration curve saved to logs/calibration.png")
    except Exception as e:
        log.info("Skipping calibration plot (%s)", e)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train racing prediction model")
    parser.add_argument(
        "--data-dir",
        type=str,
        nargs="+",
        help="Additional CSV directories to scan",
    )
    parser.add_argument(
        "--target",
        type=str,
        default="position",
        choices=["position", "win_prob"],
        help="Target type: position (finish position) or win_prob (win probability)",
    )
    parser.add_argument(
        "--synthetic-only",
        action="store_true",
        help="Skip real data loading, use purely synthetic data",
    )
    parser.add_argument(
        "--cross-validate",
        action="store_true",
        help="Run 5-fold time-series cross-validation and calibration plot",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="xgb",
        choices=["xgb", "elm"],
        help="Model to train: xgb (default) or elm (Extreme Learning Machine)",
    )
    args = parser.parse_args()

    sources = list(DATA_SOURCES)
    if args.data_dir:
        sources.extend(args.data_dir)

    if args.synthetic_only:
        # Generate synthetic data matching the real schema
        log = setup_logging(LOG_DIR)
        log.info("Synthetic-only mode — generating data matching real schema")
        rng = np.random.RandomState(42)

        # Realistic feature distributions from observed data
        n = 2000
        syn = pd.DataFrame(
            {
                "Age": rng.randint(2, 10, n),
                "Gender": rng.choice(["M", "G", "F"], n),
                "Handicap Rating": rng.uniform(45, 90, n),
                "Career Runs": rng.randint(1, 60, n),
                "Career Wins": np.clip(rng.poisson(5, n), 0, 30),
                "Career Strike Rate": np.clip(rng.beta(2, 8, n) * 40, 0, 40),
                "Career ROI": rng.uniform(-100, 50, n),
                "Career Placings": np.clip(rng.poisson(10, n), 0, 40),
                "Career Place Strike Rate": np.clip(rng.beta(3, 6, n) * 60, 0, 60),
                "Best Fixed Odds": np.clip(rng.exponential(8, n) + 1.5, 1.5, 101),
                "Weight": rng.uniform(52, 62, n),
                "Weight Carried": rng.uniform(52, 62, n),
                "Barrier": rng.randint(1, 19, n),
                "Prize Money": rng.exponential(5000, n) + 500,
                "Average Prize Money": rng.exponential(3000, n) + 500,
                "Dry Track Runs": np.clip(rng.poisson(8, n), 0, 30),
                "Dry Track Wins": np.clip(rng.poisson(2, n), 0, 10),
                "Wet Track Runs": np.clip(rng.poisson(3, n), 0, 15),
                "Wet Track Wins": np.clip(rng.poisson(1, n), 0, 8),
                "Last Start Finish Position": rng.randint(1, 13, n),
                "Last Start Margin": rng.exponential(2, n),
                "Last Start Distance": rng.choice([1200, 1400, 1600, 2000, 2400], n),
            }
        )
        syn["Career Strike Rate"] /= 100
        syn["Career Place Strike Rate"] /= 100
        syn["Career ROI"] /= 100

        # Synthetic position target for pipeline development only
        syn["Position"] = np.clip(
            np.round(1 + 11 * (1 - (syn["Best Fixed Odds"].rank(pct=True)) + rng.randn(n) * 0.2)),
            1,
            12,
        ).astype(int)
        log.info("  Added synthetic 'Position' target (pipeline development only)")

        df = syn
        syn_log = logging.getLogger("synthetic")
        df, feature_names = engineer_features(df, syn_log)
        y, target_name = generate_target(df, feature_names, args.target, syn_log)

        X = df[feature_names].values.astype(np.float32)

        if args.model == "elm":
            from ml.racing_elm import ExtremeLearningMachine

            syn_log.info("Using Extreme Learning Machine (ELM)")
            x_train, x_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
            elm = ExtremeLearningMachine(hidden_nodes=100, task="classification")
            t0 = __import__("time").perf_counter()
            elm.fit(x_train, y_train)
            elapsed = __import__("time").perf_counter() - t0
            syn_log.info("ELM training time: %.3f s", elapsed)
            # ELM uses predict, not save_model
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            import joblib

            model_path = MODEL_DIR / f"racing_model_{ts}.pkl"
            joblib.dump(elm, model_path)
            syn_log.info("Model saved: %s", model_path)
            syn_log.info("Pipeline complete")
            __import__("sys").exit(0)

        if args.cross_validate:
            metrics_list, model = cross_validate_time_series(
                X, y, feature_names, logging.getLogger("synthetic")
            )
            # Final fit on all data for model save
            model, _ = train_model(
                X, y, X[:1], y[:1], feature_names, logging.getLogger("synthetic")
            )
            _plot_calibration(y, model.predict(X), logging.getLogger("synthetic"))
            metrics = metrics_list[-1]
        else:
            x_train, x_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
            model, metrics = train_model(
                x_train, y_train, x_val, y_val, feature_names, logging.getLogger("synthetic")
            )

        save_model(model, metrics, feature_names, MODEL_DIR, logging.getLogger("synthetic"))
        write_training_report(
            metrics, feature_names, target_name, LOG_DIR, logging.getLogger("synthetic")
        )
    else:
        main(sources, args.target)
