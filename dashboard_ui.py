"""Streamlit dashboard for the Racing Platform.

Loads race data (preferring enriched CSVs when available) and displays
race cards with enriched fields (Last_10, Gear_Change, Reynolds_Rating),
live odds, and arbitrage opportunities.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from concepts.advanced.concept_16_gear_changes import gear_change_impact
from odds.rt_odds_aggregator import OddsAggregator, add_odds_to_dashboard

st.set_page_config(page_title="Racing Platform", layout="wide")
st.title("Racing Analytics Dashboard")

# ── Data loading ──────────────────────────────────────────────
RAW_DATA_PATH = "D:/Racing/racing_platform/Racing/Data/HorseRacing/data/raw/australian_racing"
ENRICHED_DATA_PATH = "D:/Racing/racing_platform/Racing/Platforms/racing_platform/data/enriched"


def _load_race_files(path: str) -> tuple[list[tuple[str, pd.DataFrame]], str]:
    """Read every CSV under *path*, returning (name, df) pairs."""
    csv_files = (
        sorted(f for f in os.listdir(path) if f.endswith(".csv")) if os.path.isdir(path) else []
    )
    races: list[tuple[str, pd.DataFrame]] = []
    for fname in csv_files:
        df = pd.read_csv(os.path.join(path, fname))
        races.append((fname, df))
    return races, path


uploaded_files = st.sidebar.file_uploader(
    "Upload race CSV(s)",
    accept_multiple_files=True,
    type=["csv"],
    help="Drop enriched CSVs here (Last_10, Gear_Change, etc.)",
)

per_race: list[tuple[str, pd.DataFrame]] = []
data_source: str | None = None

# `f` is reused below as both an UploadedFile loop var and a file handle.
f: Any

if uploaded_files:
    for f in uploaded_files:
        per_race.append((f.name, pd.read_csv(f)))
    data_source = f"{len(uploaded_files)} uploaded file(s)"
elif os.path.isdir(ENRICHED_DATA_PATH) and os.listdir(ENRICHED_DATA_PATH):
    per_race, data_source = _load_race_files(ENRICHED_DATA_PATH)
elif os.path.isdir(RAW_DATA_PATH):
    per_race, data_source = _load_race_files(RAW_DATA_PATH)
else:
    st.error(f"No CSV files found in {ENRICHED_DATA_PATH} or {RAW_DATA_PATH}")
    st.stop()

has_last10 = any("Last_10" in df.columns for _, df in per_race)
has_gear = any("Gear_Change" in df.columns for _, df in per_race)
has_reynolds = any("Reynolds_Rating" in df.columns for _, df in per_race)

# Concatenated version for odds processing
race_df = pd.concat([df for _, df in per_race], ignore_index=True)

# ── Sidebar status ────────────────────────────────────────────
st.sidebar.header("Platform Status")
st.sidebar.metric("CSV Files", len(per_race))
st.sidebar.metric("Total Runners", len(race_df))
st.sidebar.metric("Data Source", data_source or "unknown")
if has_last10:
    st.sidebar.success("Enriched fields detected")
else:
    st.sidebar.info("Basic (raw) data")

# ── Helpers ──────────────────────────────────────────────────


def _format_last10_html(last10: object) -> str:
    """Return HTML for a Last_10 form string — x in grey, top-3 in green."""
    if not isinstance(last10, str) or not last10.strip():
        return '<span style="color: #888;">—</span>'
    s = last10.strip()
    parts = []
    for ch in s:
        if ch.lower() == "x":
            parts.append(f'<span style="color: #999; font-weight:bold;">{ch}</span>')
        elif ch in ("1", "2", "3"):
            parts.append(f'<span style="color: #22c55e; font-weight:bold;">{ch}</span>')
        else:
            parts.append(f'<span style="color: #666;">{ch}</span>')
    return " ".join(parts)


def _gear_tag(gear_text: object) -> str:
    """Return a short HTML tag for a gear-change note with impact."""
    if not isinstance(gear_text, str) or not gear_text.strip():
        return '<span style="color: #888;">—</span>'
    s = gear_text.strip()
    impact = gear_change_impact(s)
    if abs(impact) < 0.005:
        colour = "#888"
        label = "neutral"
    elif impact > 0:
        colour = "#22c55e"
        label = f"+{impact:.0%}"
    else:
        colour = "#ef4444"
        label = f"{impact:.0%}"
    return f'<span style="color:{colour}; font-weight:bold; cursor:help;" title="Impact: {impact:+.0%}">{s}</span> <span style="color:{colour}; font-size:0.85em;">({label})</span>'


def _reynolds_bar_html(rating: object, width: int = 180) -> str:
    """Render a horizontal bar for a Reynolds_Rating (-1..+1 → 0..100 %)."""
    try:
        val = float(rating)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    pct = max(0.0, min(1.0, (val + 1.0) / 2.0))
    bar_colour = "#22c55e" if val >= 0 else "#ef4444"
    bg_colour = "#1a1a2e"
    return (
        f'<div style="display:inline-flex; align-items:center; gap:6px;">'
        f'<div style="width:{width}px; height:14px; background:{bg_colour}; '
        f'border-radius:7px; overflow:hidden;">'
        f'<div style="width:{pct * 100:.0f}%; height:100%; background:{bar_colour}; '
        f'border-radius:7px;"></div></div>'
        f'<span style="font-size:0.85em; color:#aaa;">{val:+.2f}</span></div>'
    )


def _name_col(df: pd.DataFrame) -> str:
    return "Horse Name" if "Horse Name" in df.columns else "Horse"


def _val(row: pd.Series, *keys: str) -> object:
    for k in keys:
        if k in row.index:
            v = row[k]
            if pd.notna(v):
                return v
    return None


# ── Tabs ─────────────────────────────────────────────────────

tab_races, tab_odds, tab_enriched, tab_bias = st.tabs(
    [
        "Races & Predictions",
        "Live Odds & Arbitrage",
        "Enriched Fields Summary",
        "Track Bias Analysis",
    ]
)

# ═══════════════════════════════════════════════════════════════
# TAB 1 — Races & Predictions
# ═══════════════════════════════════════════════════════════════

with tab_races:
    for fname, df in per_race:
        n_col = _name_col(df)

        with st.container():
            st.markdown(f"### Race — {Path(fname).stem}")
            for _, row in df.iterrows():
                horse = str(row.get(n_col, "?"))
                cols = st.columns([2.5, 1.8, 2.2, 1.5])

                # Col 0: horse name + optional Reynolds bar
                with cols[0]:
                    bar = ""
                    if has_reynolds:
                        bar_html = _reynolds_bar_html(
                            _val(row, "Reynolds_Rating", "reynolds_rating")
                        )
                        if bar_html:
                            bar = f"<br>{bar_html}"
                    st.markdown(
                        f"<div style='line-height:1.6;'><b>{horse}</b>{bar}</div>",
                        unsafe_allow_html=True,
                    )

                # Col 1: Recent form
                with cols[1]:
                    if has_last10:
                        l10 = _val(row, "Last_10", "last_10", "Last10")
                        html = _format_last10_html(l10)
                        st.markdown(
                            f"<div style='font-size:0.9em;'><span style='color:#888;'>Form:</span> "
                            f"{html}</div>",
                            unsafe_allow_html=True,
                        )

                # Col 2: Gear change
                with cols[2]:
                    if has_gear:
                        gc = _val(row, "Gear_Change", "gear_change", "GearChange")
                        html = _gear_tag(gc)
                        st.markdown(
                            f"<div style='font-size:0.9em;'><span style='color:#888;'>Gear:</span> "
                            f"{html}</div>",
                            unsafe_allow_html=True,
                        )

                # Col 3: quick stats
                with cols[3]:
                    barrier = _val(row, "Barrier", "Draw")
                    weight = _val(row, "Weight Carried", "Weight")
                    parts = []
                    if barrier is not None:
                        parts.append(f"Dr:{barrier}")
                    if weight is not None:
                        parts.append(f"Wt:{weight}")
                    if parts:
                        st.markdown(
                            f"<div style='font-size:0.85em; color:#888;'>"
                            f"{' | '.join(parts)}</div>",
                            unsafe_allow_html=True,
                        )

            # ── Per-race enriched detail table ──────────────
            race_cols = [n_col]
            if has_last10:
                race_cols.append("Last_10")
            if has_gear:
                race_cols.append("Gear_Change")
            if has_reynolds:
                race_cols.append("Reynolds_Rating")
            extras = [c for c in race_cols if c in df.columns]
            if len(extras) > 1:
                with st.expander("View raw data"):
                    st.dataframe(df[extras], width="stretch")

            st.divider()

# ═══════════════════════════════════════════════════════════════
# TAB 2 — Live Odds & Arbitrage
# ═══════════════════════════════════════════════════════════════

with tab_odds:
    horse_ids = [
        {
            "horse_id": str(row.get("Horse", row.get("Horse Name", f"h{i}"))),
            "horse_name": str(row.get("Horse", row.get("Horse Name", f"Runner {i}"))),
        }
        for i, (_, row) in enumerate(race_df.iterrows())
    ]

    if horse_ids:
        agg = OddsAggregator()
        race_odds = agg.fetch_race_odds(
            race_id="dashboard_race",
            horses=horse_ids,
            race_name="Current Raceday",
            meeting=Path(data_source or "unknown").name,
            use_mock=True,
            mock_seed=42,
        )
        arbs = agg.scan_arbitrage(race_odds)
        dash = add_odds_to_dashboard(race_odds, arbs)

        col1, col2, col3, col4 = st.columns(4)
        ms = dash["market_summary"]
        col1.metric("Runners", ms["runners"])
        col2.metric("Bookmakers", ", ".join(ms["bookmakers"]))
        col3.metric("Total Implied Prob", f"{ms['total_implied_prob']:.2%}")
        col4.metric("Overround", f"{ms['overround']:.2f}%")

        st.subheader("Best Available Prices")
        bp_df = dash["best_prices"]
        if not bp_df.empty:
            st.dataframe(bp_df, width="stretch")
        else:
            st.info("No odds data available.")

        st.subheader("Arbitrage Opportunities")
        arb_df = dash["arbitrage"]
        if not arb_df.empty:
            st.dataframe(arb_df, width="stretch")
            total_arbs = len(arb_df)
            max_profit = arb_df["Profit %"].max()
            st.success(
                f"Found {total_arbs} arbitrage "
                f"{'opportunity' if total_arbs == 1 else 'opportunities'} — "
                f"best return: {max_profit:.2f}%"
            )
        else:
            st.info("No arbitrage opportunities detected.")
    else:
        st.info("No horse data available for odds lookup.")

# ═══════════════════════════════════════════════════════════════
# TAB 3 — Enriched Fields Summary
# ═══════════════════════════════════════════════════════════════

with tab_enriched:
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Rows with Last_10", race_df["Last_10"].notna().sum() if "Last_10" in race_df.columns else 0
    )
    col2.metric(
        "Rows with Gear_Change",
        race_df["Gear_Change"].notna().sum() if "Gear_Change" in race_df.columns else 0,
    )
    col3.metric(
        "Rows with Reynolds_Rating",
        race_df["Reynolds_Rating"].notna().sum() if "Reynolds_Rating" in race_df.columns else 0,
    )

# ---------- Predictions Engine Integration ----------

# ═══════════════════════════════════════════════════════════════
# TAB 4 — Track Bias Analysis
# ═══════════════════════════════════════════════════════════════

with tab_bias:
    import plotly.express as px

    # Load barrier bias cache
    cache_path = Path("barrier_bias_cache.csv")
    if cache_path.exists():
        bias_df = pd.read_csv(cache_path)

        # Let user filter by track
        tracks = sorted(bias_df["track"].dropna().unique())
        selected_track = st.selectbox("Select Track", tracks, key="bias_track")

        track_data = bias_df[bias_df["track"] == selected_track]

        if not track_data.empty:
            distances = sorted(track_data["distance"].unique())
            selected_dist = st.selectbox("Select Distance (m)", distances, key="bias_dist")
            dist_data = track_data[track_data["distance"] == selected_dist]

            if not dist_data.empty:
                col1, col2 = st.columns([3, 2])

                with col1:
                    st.markdown(f"### Barrier Bias — {selected_track} {selected_dist}m")
                    fig = px.bar(
                        dist_data,
                        x="barrier",
                        y="adv_lengths",
                        title="Average Advantage (lengths) by Barrier",
                        labels={"barrier": "Barrier", "adv_lengths": "Advantage (lengths)"},
                        color="adv_lengths",
                        color_continuous_scale=["#f44336", "#ffeb3b", "#4caf50"],
                    )
                    # Add CI error bars
                    fig.update_traces(
                        error_y={
                            "type": "data",
                            "array": dist_data["ci_upper"] - dist_data["adv_lengths"],
                            "arrayminus": dist_data["adv_lengths"] - dist_data["ci_lower"],
                            "visible": True,
                        }
                    )
                    fig.add_hline(y=0, line_dash="dash", line_color="#666")
                    st.plotly_chart(fig, width="stretch")

                with col2:
                    st.markdown("### Barrier Details")
                    show_cols = [
                        "barrier",
                        "adv_lengths",
                        "ci_lower",
                        "ci_upper",
                        "n_runners",
                        "n_races",
                        "significant",
                    ]
                    display_df = dist_data[show_cols].copy()
                    display_df["significant"] = display_df["significant"].map(
                        {True: "✔", False: ""}
                    )
                    st.dataframe(display_df, width="stretch", hide_index=True)
            else:
                st.info(f"No data for {selected_track} at {selected_dist}m")
        else:
            st.warning(f"No data available for {selected_track}")
    else:
        st.warning("Barrier bias cache not found. Run `python draw_analyzer.py` to generate it.")
import streamlit as st
import yaml  # type: ignore[import-untyped]
from services.prediction_service import PredictionService

# Load config
with open("config/reynolds_config.yaml") as f:
    config = yaml.safe_load(f)

# Sidebar controls
st.sidebar.header("📊 Betting Configuration")
bankroll = st.sidebar.number_input(
    "Bankroll ($)", value=float(config.get("bankroll", 10000)), step=100.0
)
kelly_method = st.sidebar.selectbox(
    "Kelly Method",
    ["full", "half", "quarter"],
    index=["full", "half", "quarter"].index(config.get("kelly_method", "half")),
)
max_single = (
    st.sidebar.slider(
        "Max Single Bet (%)", 0.5, 10.0, float(config["risk"]["max_single_race_exposure"]) * 100
    )
    / 100.0
)
max_total = (
    st.sidebar.slider(
        "Max Total Exposure (%)", 0.5, 20.0, float(config["risk"]["max_total_exposure"]) * 100
    )
    / 100.0
)

refresh = st.sidebar.button("🔄 Refresh Predictions")

# Update config in memory
config["bankroll"] = bankroll
config["kelly_method"] = kelly_method
config["risk"]["max_single_race_exposure"] = max_single
config["risk"]["max_total_exposure"] = max_total

# Save config button
if st.sidebar.button("💾 Save Config"):
    with open("config/reynolds_config.yaml", "w") as f:
        yaml.dump(config, f)
    st.sidebar.success("Config saved.")

# ---------- Predictions Tab ----------
st.title("🎯 Predictions")

service = PredictionService(config)

# Caching: store predictions in session state
if "predictions_cache" not in st.session_state:
    st.session_state.predictions_cache = {}
if "predictions_config_hash" not in st.session_state:
    st.session_state.predictions_config_hash = None

config_hash = hash((bankroll, kelly_method, max_single, max_total))
if refresh or st.session_state.predictions_config_hash != config_hash:
    with st.spinner("Running prediction engine..."):
        predictions = service.run_predictions(bankroll)
        st.session_state.predictions_cache = predictions
        st.session_state.predictions_config_hash = config_hash
        st.success("Predictions updated.")
else:
    predictions = st.session_state.predictions_cache

# Render race cards
if predictions:
    for race_id, bets in predictions.items():
        with st.expander(f"🏇 {race_id}"):
            if not bets:
                st.write("No data for this race.")
                continue

            # Build display DataFrame
            rows = []
            for b in bets:
                rows.append(
                    {
                        "Horse": b["horse"],
                        "Win Prob": f"{b['prob']:.1%}",
                        "Fair Odds": f"{b['fair_odds']:.2f}",
                        "Live Odds": f"{b['live_odds']:.2f}",
                        "Kelly Stake": f"${b['kelly_stake']:.2f}",
                        "Value": "🔥 VALUE"
                        if (b.get("ev", 0) > 0 and b["live_odds"] / b["fair_odds"] > 1.2)
                        else "",
                    }
                )
            import pandas as pd

            df = pd.DataFrame(rows)
            st.dataframe(df, width="stretch")
else:
    st.info("No predictions available. Upload race CSV files or check your data folder.")
