#!/usr/bin/env python3

import contextlib
import io
import os
import sqlite3
import sys
from collections import Counter
from typing import Any, cast

import matplotlib
import pandas as pd
import streamlit as st

matplotlib.use("Agg")  # non-interactive backend for Streamlit
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

try:
    from analysis_bonus_pairs import (
        compute_cooccurrence_matrix,
        get_top_pairs_for_bonus,
        get_top_triplets,
    )
    from backtest import (
        backtest_bonus_impact,
        generate_backtest_summary,
        simulate_bonus_ev,
    )
    from lotto_wheels import (
        WHEELS,
        bandit_recommendation,
        bayesian_posterior,
        block_analysis,
        check_all_wheels,
        get_bonus_stats,
        load_draws,
        numerical_attraction,
        positive_negative_split,
        sum_range,
    )
    from predictions import BonusBayesian, bonus_gap_prediction
    from prize_calculator import (
        calculate_lotto_only_prize,
        fetch_payouts,
    )
    from rotation_scheduler import (
        bayesian_posterior,  # noqa: F811 — intentionally shadows the
        # lotto_wheels import above; later pages use rotation_scheduler's
        # variant (recency-weighted). Preserved for behavior compatibility.
        bonus_bayesian_predictor,
        build_rotation,
    )
    from rotation_scheduler import (
        load_draws as load_rotation_draws,
    )
    from wheel_generator import generate_abbreviated_wheel
except ImportError as e:
    st.error(f"Could not import: {e}")
    st.stop()

st.set_page_config(page_title="NZ Lotto Powerball Dashboard", layout="wide")

# --- Schema version check (Alembic) ---
# Warn (via logs) when the database is behind the latest migration.
try:
    from migrate import check_schema_version

    check_schema_version()
except Exception:
    pass  # never block the dashboard on a version-check failure

# ---------------------------------------------------------------------------
# Refresh Data helper
# ---------------------------------------------------------------------------
if "draws_cache" not in st.session_state:
    st.session_state["draws_cache"] = None


def refresh_data() -> None:
    """Clear cached draws and trigger a rerun."""
    st.session_state["draws_cache"] = None
    st.cache_data.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Custom CSS — mobile-first responsive, scrollable tables, compact layout
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
    /* Responsive base */
    .block-container { padding-top: 1.5rem; padding-left: 1rem; padding-right: 1rem; }
    @media (min-width: 1024px) {
        .block-container { padding-left: 3rem; padding-right: 3rem; }
    }
    .main-header { font-size: 1.4rem; }
    .section-header { font-size: 1.15rem; margin-top: 0.5rem; }
    @media (max-width: 640px) {
        .main-header { font-size: 1.1rem !important; }
        .section-header { font-size: 0.95rem !important; }
        div[data-testid="stMetricValue"] { font-size: 1.0rem !important; }
        .wheel-card { font-size: 0.8rem; padding: 0.3rem !important; }
        div[data-testid="column"] { min-width: 140px; }
        section[data-testid="stSidebar"] { min-width: 200px; }
        section[data-testid="stSidebar"] > div { padding: 0.5rem; }
    }

    /* Scrollable tables */
    div[data-testid="stDataFrame"] > div { overflow-x: auto; }
    div[data-testid="stDataFrame"] table { min-width: 320px; }
    div[data-testid="stDataEditor"] > div { overflow-x: auto; }

    /* Sticky sidebar sections */
    section[data-testid="stSidebar"] > div { padding-top: 0.5rem; }

    /* Chart containers fill available width */
    .stChart > div, .stPlotlyChart > div { width: 100%; }

    /* Expander styling */
    .stExpander details summary { font-weight: 600; }

    /* Last-draw cards */
    .draw-card {
        border: 1px solid #ddd;
        border-radius: 6px;
        padding: 0.4rem 0.6rem;
        margin-bottom: 0.4rem;
        font-size: 0.8rem;
        line-height: 1.4;
    }
    .draw-card strong { color: #1a5276; }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    '<h1 class="main-header">NZ Lotto Powerball Wheel Dashboard</h1>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Load draws (with optional cache-busting)
# ---------------------------------------------------------------------------
if st.session_state["draws_cache"] is None:
    st.session_state["draws_cache"] = load_draws()
draws = cast(list[tuple[list[int], int, int, str]], st.session_state["draws_cache"])

# ---------------------------------------------------------------------------
# Sidebar — DB info + last 3 draws + navigation + wheel selector + refresh
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Database Info")
    if draws:
        col_a, col_b = st.columns(2)
        col_a.metric("Total Draws", len(draws))
        col_b.metric("Draw Range", f"{draws[0][3][:4]}-{draws[-1][3][:4]}")
        st.caption(f"{draws[0][3]} to {draws[-1][3]}")
    else:
        st.warning("No draws loaded.")

    # ---- Last 3 draws ----
    if draws:
        st.markdown("### Last 3 Draws")
        for nums, pb, bonus, date in reversed(draws[-3:]):
            nums_str = ", ".join(f"{n:02d}" for n in nums)
            bonus_str = f" &nbsp;|&nbsp; Bonus {bonus:02d}" if bonus else ""
            st.markdown(
                f"<div class='draw-card'>"
                f"<strong>{date}</strong><br>"
                f"{nums_str}{bonus_str} &nbsp;|&nbsp; PB {pb}"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # ---- Theme Toggle ----
    if "dark_mode" not in st.session_state:
        st.session_state["dark_mode"] = False

    dark_mode = st.toggle(
        "🌙 Dark Mode",
        value=st.session_state["dark_mode"],
        key="dark_mode_toggle",
        help="Toggle dark/light theme for the dashboard.",
    )
    if dark_mode != st.session_state["dark_mode"]:
        st.session_state["dark_mode"] = dark_mode

    if st.session_state["dark_mode"]:
        st.markdown(
            """
        <style>
        body, .stApp { background-color: #1e1e1e; color: #e0e0e0; }
        .stDataFrame, .stTable { color: #e0e0e0; }
        .stMarkdown { color: #e0e0e0; }
        </style>
        """,
            unsafe_allow_html=True,
        )

    st.divider()

    # ---- Game Mode (persists across tabs) ----
    if "game_mode" not in st.session_state:
        st.session_state["game_mode"] = "powerball"

    standard_mode = st.toggle(
        "Standard Lotto Mode",
        value=st.session_state["game_mode"] == "standard",
        key="game_mode_toggle",
        help="Off = Powerball Mode (default). On = Standard Lotto Mode "
        "(4 divisions, no Powerball, no bonus upgrades).",
    )
    st.session_state["game_mode"] = "standard" if standard_mode else "powerball"

    if standard_mode:
        st.markdown(
            "<span style='background:#1a7f37;color:white;border-radius:12px;"
            "padding:0.25rem 0.7rem;font-size:0.85rem;'>"
            "🎫 Standard Lotto Mode</span>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<span style='background:#b26a00;color:white;border-radius:12px;"
            "padding:0.25rem 0.7rem;font-size:0.85rem;'>"
            "🎱 Powerball Mode</span>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ---- Cache Management ----
    with st.expander("Cache Management"):
        if st.button("🧹 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.toast("Cache cleared!", icon=":material/check:")
            st.rerun()
        st.caption("Clears all cached data (predictions, backtests, etc.).")

    st.divider()

    st.markdown("### Navigation")
    page = st.radio(
        "Go to",
        [
            "Wheels & Tickets",
            "Statistical Report",
            "Frequency Chart",
            "Check Draw",
            "Check Latest Draw",
            "Strike Check",
            "Custom Wheel Builder",
            "Bonus Ball Analysis",
            "🎱 Bonus Impact",
            "🎫 Standard Lotto",
            "Predictions",
            "EV Simulation",
            "Bonus–Main Co‑occurrence",
            "Rotation Scheduler",
            "Backtest Results",
            "Multi-Draw Backtest",
            "Block Analysis",
            "🧱 Albert Blocks",
            "➕➖ Pos/Neg",
            "🧲 Attraction Profile",
            "Wheel Explorer",
            "📚 Bluskov Library",
            "Live Monitor",
            "Ticket Wizard",
            "International Lotteries",
            "💰 Arbitrage",
            "⚛️ Quantum Wheel",
            "Data Import",
            "Pipeline Status",
            "ML Predictor",
            "📊 Predictor Leaderboard",
            "👥 Syndicates",
            "Export",
            "🔔 System Health",
        ],
        label_visibility="collapsed",
    )

    # ---- Global date range filter (used by Bonus Ball Analysis) ----
    st.divider()
    st.markdown("### Date Range Filter")
    date_start = st.text_input(
        "Start date (YYYY-MM-DD)",
        value="",
        key="bonus_date_start",
        placeholder="e.g. 2024-01-01",
    )
    date_end = st.text_input(
        "End date (YYYY-MM-DD)",
        value="",
        key="bonus_date_end",
        placeholder="e.g. 2024-12-31",
    )

    st.divider()

    st.markdown("### Wheel Selector")
    wheel_names = list(WHEELS.keys())
    selected_wheel = st.selectbox("Wheel", wheel_names, label_visibility="collapsed")

    if st.button("Show Tickets & Cost", use_container_width=True):
        st.session_state["show_tickets"] = selected_wheel

    st.divider()

    # ---- Refresh button ----
    st.markdown("### Actions")
    if st.button("Refresh Data", use_container_width=True, type="primary"):
        refresh_data()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def wheel_guarantee(name: str) -> str:
    guarantees = {
        "single1": "4-win if 4 of your 10 numbers are drawn",
        "single2": "4-win if 4 of your 10 numbers are drawn",
        "double": "Two 4-wins if 4 of your 10 numbers are drawn",
        "five-if-six": "5-win if all 6 numbers are within your 11 numbers",
        "jackpot7": "Jackpot (6-win) if all 6 numbers are within your 7 numbers",
    }
    return guarantees.get(name, "See documentation")


def pool_of(wheel: str) -> list[int]:
    tickets, _ = WHEELS[wheel]
    pool: set[int] = set()
    for t in tickets:
        pool.update(t)
    return sorted(pool)


def get_bonus_freq(
    conn: sqlite3.Connection, start_date: str | None = None, end_date: str | None = None
) -> pd.DataFrame:
    """Return a DataFrame of bonus ball frequencies from the draws table.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to lotto.db.
    start_date : str or None
        Optional lower-bound date filter (inclusive, YYYY-MM-DD).
    end_date : str or None
        Optional upper-bound date filter (inclusive, YYYY-MM-DD).

    Returns
    -------
    pd.DataFrame
        Columns: bonus_number, count, freq_pct.
    """
    query = "SELECT bonus FROM draws"
    params = []
    conditions = []
    if start_date is not None and start_date.strip():
        conditions.append("draw_date >= ?")
        params.append(start_date.strip())
    if end_date is not None and end_date.strip():
        conditions.append("draw_date <= ?")
        params.append(end_date.strip())
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY draw_date ASC"

    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()

    counter: Counter[int] = Counter()
    for (bonus,) in rows:
        counter[bonus] += 1

    total = sum(counter.values())
    if total == 0:
        return pd.DataFrame(columns=["bonus_number", "count", "freq_pct"])

    data = [
        (n, counter.get(n, 0), counter.get(n, 0) / total * 100) for n in range(1, 41)
    ]
    return pd.DataFrame(data, columns=["bonus_number", "count", "freq_pct"])


# =========================================================================
# PAGE: Wheels & Tickets
# =========================================================================
if page == "Wheels & Tickets":
    st.markdown(
        '<h2 class="section-header">Wheels &amp; Tickets</h2>', unsafe_allow_html=True
    )

    # --- Overview cards — responsive grid ---
    # Compute compliance scores for all pre-built wheels
    wheel_scores = {}
    try:
        conn_ws = sqlite3.connect("lotto.db")
        from albert_analysis import classify_numbers
        from block_analysis import compute_block_ranges
        from compliance_scorer import score_wheel
        from sum_analysis import dynamic_sum_range

        albert_ws = classify_numbers(conn_ws, window_draws=20)
        albert_ws["block_ranges"] = compute_block_ranges(draws, window_draws=30)
        albert_ws["sum_range"] = dynamic_sum_range(conn_ws, window_draws=30)
        for name, (tickets, _pb) in WHEELS.items():
            wheel_scores[name] = score_wheel(tickets, albert_ws)
    except Exception:
        pass
    finally:
        if "conn_ws" in dir():
            conn_ws.close()

    overview_data = []
    for name, (tickets, pb) in WHEELS.items():
        p = pool_of(name)
        overview_data.append(
            {
                "Wheel": name,
                "Tickets": len(tickets),
                "Pool": len(p),
                "PB": pb,
                "Guarantee": wheel_guarantee(name),
                "Score": wheel_scores.get(name),
            }
        )

    cols_per_row = 3
    rows = [
        overview_data[i : i + cols_per_row]
        for i in range(0, len(overview_data), cols_per_row)
    ]
    for row in rows:
        cols = st.columns(len(row), gap="small")
        for i, info in enumerate(row):
            with cols[i]:
                score_html = ""
                if info["Score"] is not None:
                    s = cast(Any, info["Score"])
                    badge = "🟢" if s >= 80 else ("🟡" if s >= 60 else "🔴")
                    score_html = f"<div>{badge} Lotto Score: {s:.0f}/100</div>"

                st.markdown(
                    f"""
                <div class="wheel-card" style="border:1px solid #ccc;border-radius:8px;padding:0.5rem;text-align:center;">
                    <div style="font-weight:600">{info['Wheel']}</div>
                    <div>Tickets: {info['Tickets']}</div>
                    <div>Pool: {info['Pool']} numbers</div>
                    <div>PB: {info['PB']}</div>
                    <div style="font-size:0.8rem;margin-top:4px">{info['Guarantee']}</div>
                    {score_html}
                </div>
                """,
                    unsafe_allow_html=True,
                )

    st.divider()

    # --- Detailed wheel view ---
    if "show_tickets" in st.session_state:
        wheel = st.session_state["show_tickets"]
        tickets, pb = WHEELS[wheel]
        cost = len(tickets) * 1.5

        st.markdown(
            f'<h3 class="section-header">{wheel.upper()}</h3>', unsafe_allow_html=True
        )

        info_cols = st.columns([2, 2, 2], gap="medium")
        info_cols[0].metric("Tickets", len(tickets))
        info_cols[1].metric("Powerball", pb)
        info_cols[2].metric("Cost", f"${cost:.2f}")

        st.write(f"**Guarantee:** {wheel_guarantee(wheel)}")

        tickets_data = [
            {
                "Ticket": i + 1,
                "Main Numbers": ", ".join(f"{x:02d}" for x in sorted(comb)),
            }
            for i, comb in enumerate(tickets)
        ]
        st.data_editor(
            pd.DataFrame(tickets_data),
            width="stretch",
            hide_index=True,
            disabled=True,
            use_container_width=True,
        )

        with st.expander("Pool numbers used by this wheel"):
            st.write(", ".join(str(n) for n in pool_of(wheel)))
    else:
        st.info("Select a wheel in the sidebar and click **Show Tickets & Cost**.")


# =========================================================================
# PAGE: Statistical Report — each section in its own expander
# =========================================================================
elif page == "Statistical Report":
    st.markdown(
        '<h2 class="section-header">Statistical Report</h2>', unsafe_allow_html=True
    )

    if not draws:
        st.warning("No draws in database.")
    else:
        # Compute all stats once
        pos, neg, freq = positive_negative_split(draws)
        ranges = block_analysis(draws)
        low, high = sum_range(draws)
        adj = numerical_attraction(draws)
        bayes = bayesian_posterior(draws)
        top_bayes = sorted(bayes.items(), key=lambda x: x[1], reverse=True)[:10]
        bandit = bandit_recommendation(draws)

        # --- Positive / Negative Split ---
        with st.expander("Positive / Negative Split", expanded=True):
            left, right = st.columns(2)
            left.markdown(f"**Positive (freq > threshold)** — {len(pos)} numbers")
            left.write(f"`{sorted(pos)}`" if pos else "None")
            right.markdown(f"**Negative (freq ≤ threshold)** — {len(neg)} numbers")
            right.write(f"`{sorted(neg)}`" if neg else "None")

        # --- Block Analysis ---
        with st.expander("Block Analysis (positional ranges)"):
            rows_b = []
            for i, cats in ranges.items():
                rows_b.append({"Position": f"#{i+1}", **cats})
            st.data_editor(
                pd.DataFrame(rows_b).set_index("Position"),
                width="stretch",
                disabled=True,
                use_container_width=True,
            )

        # --- Sum Range ---
        with st.expander("Sum Range (trimmed extremes)"):
            st.metric("Typical sum range", f"{low} – {high}")

        # --- Numerical Attraction ---
        with st.expander("Numerical Attraction"):
            st.markdown(
                f"**{adj*100:.1f}%** of draws contain adjacent numbers (gap ≤ 2)"
            )

        # --- Bayesian Posterior ---
        with st.expander("Bayesian Top 10"):
            bayes_df = pd.DataFrame(
                [{"Number": n, "Probability": f"{p:.4%}"} for n, p in top_bayes]
            )
            st.data_editor(
                bayes_df,
                width="stretch",
                hide_index=True,
                disabled=True,
                use_container_width=True,
            )

            # Bar visualisation
            max_prob = top_bayes[0][1] if top_bayes else 1
            bars = "\n".join(
                f"#{n:02d} {'█' * round(p/max_prob*20)}{p:.2%}" for n, p in top_bayes
            )
            st.code(bars, language="text")

        # --- Thompson Sampling ---
        with st.expander("Thompson Sampling Top 6"):
            st.markdown(f"Recommended numbers: **{bandit}**")
            st.caption("Multi-armed bandit with Beta(α, β) per number")


# =========================================================================
# PAGE: Frequency Chart
# =========================================================================
elif page == "Frequency Chart":
    st.markdown(
        '<h2 class="section-header">Frequency Chart</h2>', unsafe_allow_html=True
    )

    if not draws:
        st.warning("No draws in database.")
    else:
        # Count main numbers across all draws
        main_counter: Counter[int] = Counter()
        pb_counter: Counter[int] = Counter()
        for nums, pb, _bonus, _date in draws:
            main_counter.update(nums)
            pb_counter[pb] += 1

        # Build full arrays (include zeros for numbers never drawn)
        main_freq = np.array([main_counter.get(n, 0) for n in range(1, 41)])
        pb_freq = np.array([pb_counter.get(n, 0) for n in range(1, 11)])

        # Top 5 indices
        top5_main = np.argsort(main_freq)[-5:][::-1]
        top5_pb = np.argsort(pb_freq)[-5:][::-1]

        # ---- Main numbers chart ----
        st.markdown("### Main Numbers (1–40)")

        fig1, ax1 = plt.subplots(figsize=(11, 4.5), constrained_layout=True)
        colours1 = np.where(
            np.arange(40) == top5_main[0],
            "#e74c3c",
            np.where(np.isin(np.arange(40), top5_main), "#f39c12", "#3498db"),
        )

        ax1.bar(
            np.arange(1, 41),
            main_freq,
            color=colours1,
            edgecolor="white",
            linewidth=0.3,
        )
        ax1.set_xlabel("Main Number")
        ax1.set_ylabel("Frequency (number of draws)")
        ax1.set_title("Occurrence Frequency of Main Numbers Across All Draws")
        ax1.set_xticks(range(1, 41, 2))
        ax1.set_xticks(range(1, 41), minor=True)
        ax1.set_xlim(0.5, 40.5)

        # Annotate top 5
        for rank, idx in enumerate(top5_main, 1):
            n = idx + 1
            ax1.annotate(
                f"#{rank}: {int(main_freq[idx])}",
                (n, main_freq[idx]),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                fontsize=7,
                fontweight="bold",
                color="#c0392b",
            )

        st.pyplot(fig1)
        plt.close(fig1)

        # Top 5 summary
        top5_main_info = ", ".join(f"#{n+1} ({int(main_freq[n])})" for n in top5_main)
        st.caption(f"**Top 5 main numbers:** {top5_main_info}")

        st.divider()

        # ---- Powerball chart ----
        st.markdown("### Powerball (1–10)")

        fig2, ax2 = plt.subplots(figsize=(7, 3.5), constrained_layout=True)
        colours2 = np.where(
            np.arange(10) == top5_pb[0],
            "#e74c3c",
            np.where(np.isin(np.arange(10), top5_pb), "#f39c12", "#27ae60"),
        )

        ax2.bar(
            np.arange(1, 11), pb_freq, color=colours2, edgecolor="white", linewidth=0.5
        )
        ax2.set_xlabel("Powerball Number")
        ax2.set_ylabel("Frequency (number of draws)")
        ax2.set_title("Occurrence Frequency of Powerball Numbers Across All Draws")
        ax2.set_xticks(range(1, 11))
        ax2.set_xlim(0.5, 10.5)

        for rank, idx in enumerate(top5_pb, 1):
            n = idx + 1
            ax2.annotate(
                f"#{rank}: {int(pb_freq[idx])}",
                (n, pb_freq[idx]),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                fontweight="bold",
                color="#c0392b",
            )

        st.pyplot(fig2)
        plt.close(fig2)

        top5_pb_info = ", ".join(f"#{n+1} ({int(pb_freq[n])})" for n in top5_pb)
        st.caption(f"**Top 5 Powerballs:** {top5_pb_info}")

        # Optional raw data expander
        with st.expander("View raw frequency table"):
            main_df = pd.DataFrame(
                {
                    "Number": range(1, 41),
                    "Count": main_freq,
                    "Percentage": main_freq / main_freq.sum() * 100,
                }
            )
            pb_df = pd.DataFrame(
                {
                    "Powerball": range(1, 11),
                    "Count": pb_freq,
                    "Percentage": pb_freq / pb_freq.sum() * 100,
                }
            )
            left_tab, right_tab = st.columns(2)
            with left_tab:
                st.data_editor(
                    main_df.sort_values("Count", ascending=False).reset_index(
                        drop=True
                    ),
                    width="stretch",
                    hide_index=True,
                    disabled=True,
                    use_container_width=True,
                )
            with right_tab:
                st.data_editor(
                    pb_df.sort_values("Count", ascending=False).reset_index(drop=True),
                    width="stretch",
                    hide_index=True,
                    disabled=True,
                    use_container_width=True,
                )


# =========================================================================
# PAGE: Check Draw
# =========================================================================
elif page == "Check Draw":
    st.markdown('<h2 class="section-header">Check Draw</h2>', unsafe_allow_html=True)
    st.markdown("See how many winning tickets a wheel produces for a given draw.")

    col1, col2 = st.columns([3, 1], gap="medium")
    with col1:
        draw_input = st.text_input(
            "Draw numbers (comma-separated)", "11,12,17,22,28,32"
        )
    with col2:
        pb_input = st.number_input("Powerball", min_value=1, max_value=10, value=3)

    wheel_to_check = st.selectbox(
        "Wheel", wheel_names, key="check_wheel", label_visibility="collapsed"
    )

    if st.button("Check Draw", use_container_width=True):
        try:
            nums = [int(x.strip()) for x in draw_input.split(",")]
            err = None
            if len(nums) != 6:
                err = "Enter exactly 6 numbers."
            elif len(set(nums)) != 6:
                err = "Duplicate numbers detected."
            elif any(n < 1 or n > 40 for n in nums):
                err = "Numbers must be between 1 and 40."
            if err:
                st.error(err)
            else:
                draw_set = set(nums)
                tickets, wheel_pb = WHEELS[wheel_to_check]
                pool = pool_of(wheel_to_check)

                match_data = []
                for i, comb in enumerate(tickets, 1):
                    match_count = len(draw_set.intersection(comb))
                    if match_count >= 3:
                        match_data.append(
                            {
                                "Ticket": i,
                                "Main Numbers": ", ".join(
                                    f"{x:02d}" for x in sorted(comb)
                                ),
                                "Matches": match_count,
                            }
                        )

                st.markdown(
                    f"**Pool overlap:** {len(draw_set & set(pool))} / 6 "
                    f"| **Wheel PB:** {wheel_pb} "
                    f"| **Draw PB:** {pb_input}"
                )

                if match_data:
                    st.success(f"**{len(match_data)}** ticket(s) with 3+ matches")
                    st.data_editor(
                        pd.DataFrame(match_data),
                        width="stretch",
                        hide_index=True,
                        disabled=True,
                        use_container_width=True,
                    )
                else:
                    st.info("No winning tickets (need 3+ main matches from the wheel).")
        except Exception as e:
            st.error(f"Error: {e}")


# =========================================================================
# PAGE: Check Latest Draw
# =========================================================================
elif page == "Check Latest Draw":
    st.markdown(
        '<h2 class="section-header">Check Latest Draw</h2>', unsafe_allow_html=True
    )

    # Cached function: latest draw from DB, checking API for newer
    try:
        from settings import settings as _st_cache

        _CACHE_TTL = _st_cache.cache_ttl_seconds
    except ImportError:
        _CACHE_TTL = 3600

    @st.cache_data(ttl=_CACHE_TTL)
    def get_latest_draw_info() -> tuple[Any, Any, Any, Any, bool]:
        """Return (draw_numbers, pb, bonus, draw_date, is_live_source) for the latest draw.

        Checks the MyLotto API first for the newest draw not yet in the DB.
        Falls back to the last draw in the local DB.
        """
        try:
            payouts = fetch_payouts()
            if payouts and payouts.get("draw_date"):
                api_date = payouts["draw_date"]
                # Check if we have this date in the DB
                for nums, pb, bonus, date in draws:
                    if date == api_date:
                        return nums, pb, bonus, date, True
                # New draw found via API — can't return numbers without the draw itself
                # The API only gives us payouts, not the draw numbers
                pass
        except Exception:
            pass

        # Fall back to latest from DB
        if draws:
            nums, pb, bonus, date = draws[-1]
            return nums, pb, bonus, date, False
        return None, None, None, None, False

    @st.cache_data(ttl=_CACHE_TTL)
    def cached_check_all_wheels(*args: Any, **kwargs: Any) -> Any:
        return check_all_wheels(*args, **kwargs)

    # Fetch latest draw info
    draw_nums, draw_pb, draw_bonus, draw_date, is_live = get_latest_draw_info()

    if draw_nums is None:
        st.warning("No draws available.")
    else:
        # --- Select any recent draw ---
        recent_draws = draws[-50:]
        draw_options = {
            f"{date}  —  {', '.join(f'{n:02d}' for n in nums)}  |  Bonus {b:02d}  |  PB {pb}": (
                nums,
                pb,
                b,
                date,
            )
            for nums, pb, b, date in reversed(recent_draws)
        }
        default_key = next(iter(draw_options))
        selected_label = st.selectbox(
            "Select a draw to check",
            list(draw_options.keys()),
            index=0,
            key="latest_draw_selector",
        )
        draw_nums, draw_pb, draw_bonus, draw_date = draw_options[selected_label]
        draw_set = set(draw_nums)
        is_live = False  # mark as DB-sourced for non-latest

        # --- Draw info header ---
        source_tag = "API" if is_live else "Database"
        nums_str = ", ".join(f"{n:02d}" for n in draw_nums)

        info_cols = st.columns([2, 1, 1, 1])
        info_cols[0].markdown(f"**Draw Date:** {draw_date}")
        info_cols[1].markdown(f"**Numbers:** {nums_str}")
        info_cols[2].markdown(f"**Bonus:** {draw_bonus}")
        info_cols[3].markdown(f"**Powerball:** {draw_pb}")
        st.caption(f"Source: {source_tag}")

        # --- Bonus match toggle ---
        bonus_matched = st.checkbox(
            "Bonus ball matched?",
            value=False,
            key="bonus_match_toggle",
            help="When checked, the draw's bonus ball is treated as matched for all "
            "tickets (triggers Div 2/4/6 upgrade rules). Upgraded divisions "
            "are marked with *.",
        )

        st.divider()

        # --- Compute results ---
        with st.spinner("Checking all wheels..."):
            results = cached_check_all_wheels(
                tuple(draw_nums),
                draw_pb,
                draw_bonus,
                draw_date,
                bonus_matched=bonus_matched,
            )

        # --- Compute Lotto-only results ---
        def compute_lotto_only(
            tickets: Any, draw_set: set[int], draw_bonus: int, bonus_flag: bool
        ) -> list[dict[str, Any]]:
            results = []
            for name in ["single1", "single2", "double", "five-if-six", "jackpot7"]:
                tkts, w_pb = WHEELS[name]
                pool: set[int] = set()
                for t in tkts:
                    pool.update(t)
                winning = 0
                total = 0.0
                div_hits: dict[str, int] = {}
                for ticket in tkts:
                    matches = len(set(ticket) & draw_set)
                    ticket_bonus = (draw_bonus in set(ticket)) if bonus_flag else False
                    info = calculate_lotto_only_prize(matches, ticket_bonus)
                    if info["division"] is not None:
                        winning += 1
                        total += info["prize"]
                        lbl = info["division_label"]
                        if ticket_bonus and info["division"] in (2, 4, 6):
                            lbl += "*"
                        div_hits[lbl] = div_hits.get(lbl, 0) + 1
                results.append(
                    {
                        "Wheel": name,
                        "Bonus Coverage": len(pool),
                        "Tickets": len(tkts),
                        "Pool": len(pool),
                        "Winning Tickets": winning,
                        "Total Prize": total,
                        "Division Breakdown": ", ".join(
                            f"{k}: {v}" for k, v in sorted(div_hits.items())
                        )
                        if div_hits
                        else "None",
                    }
                )
            return results

        lotto_results = compute_lotto_only(
            WHEELS, set(draw_nums), draw_bonus, bonus_matched
        )

        # --- Tabs: Powerball vs Lotto Only ---
        tab_pb, tab_lotto = st.tabs(
            ["Powerball (with PB)", "Lotto Only (no Powerball)"]
        )

        def _render_results_table(
            results: list[dict[str, Any]], tab_container: Any
        ) -> None:
            if results:
                df = pd.DataFrame(results)
                df["Total Prize"] = df["Total Prize"].apply(lambda x: f"${x:,.2f}")

                tab_container.data_editor(
                    df,
                    width="stretch",
                    hide_index=True,
                    disabled=True,
                    use_container_width=True,
                    column_config={
                        "Wheel": st.column_config.TextColumn("Wheel", width="small"),
                        "Bonus Coverage": st.column_config.NumberColumn(
                            "Bonus Cov.", width="small"
                        ),
                        "Tickets": st.column_config.NumberColumn(
                            "Tickets", width="small"
                        ),
                        "Pool": st.column_config.NumberColumn("Pool", width="small"),
                        "Pool Overlap": st.column_config.TextColumn(
                            "Overlap", width="small"
                        ),
                        "Wheel PB": st.column_config.NumberColumn(
                            "Wheel PB", width="small"
                        ),
                        "Winning Tickets": st.column_config.NumberColumn(
                            "Winners", width="small"
                        ),
                        "Total Prize": st.column_config.TextColumn(
                            "Total Prize", width="medium"
                        ),
                    },
                )

                best = max(results, key=lambda r: r["Total Prize"])
                if best["Total Prize"] > 0:
                    tab_container.success(
                        f"**Best wheel:** {best['Wheel']} — "
                        f"{best['Winning Tickets']} winning tickets, "
                        f"${best['Total Prize']:,.2f} total"
                    )

                tab_container.divider()
                tab_container.markdown("### Per-Wheel Details")
                for r in results:
                    with tab_container.expander(
                        f"{r['Wheel']} — {r['Winning Tickets']} winners, ${r['Total Prize']:,.2f}"
                    ):
                        tab_container.markdown(
                            f"**Tickets:** {r['Tickets']} | "
                            f"**Pool:** {r['Pool']} numbers | "
                            f"**Bonus Coverage:** {r.get('Bonus Coverage', 'N/A')}"
                        )
                        if r["Division Breakdown"] != "None":
                            tab_container.markdown(
                                f"**Divisions hit:** {r['Division Breakdown']}"
                            )

        if results:
            with tab_pb:
                _render_results_table(results, st)

        if lotto_results:
            with tab_lotto:
                _render_results_table(lotto_results, st)

        # --- Refresh button ---
        st.divider()
        if st.button("🔄 Refresh (check API for new draw)", use_container_width=True):
            st.cache_data.clear()
            st.rerun()


# =========================================================================
# PAGE: Strike Check
# =========================================================================
elif page == "Strike Check":
    from prize_calculator import calculate_strike_prize, count_exact_matches

    st.markdown(
        '<h2 class="section-header">Lotto Strike Check</h2>', unsafe_allow_html=True
    )
    st.markdown(
        "Lotto **Strike** uses the **first 4 winning numbers in exact order**. "
        "Enter your 4 numbers below to see which Strike division you would win."
    )

    # --- Input: 4 numbers in order ---
    st.markdown("### Your Strike Numbers")
    cols = st.columns(4)
    strike_nums: list[int] = []
    for i, col in enumerate(cols):
        with col:
            n = st.number_input(
                f"Ball {i + 1}",
                min_value=1,
                max_value=40,
                value=1,
                step=1,
                key=f"strike_n{i}",
            )
            strike_nums.append(n)

    # --- Fetch latest draw ---
    if not draws:
        st.warning("No draw data loaded.")
    else:
        latest = draws[-1]
        draw_nums = latest[0]  # list of 6 ints
        draw_date = latest[3]  # str date
        bonus = latest[2]  # int
        pb = latest[1]  # int

        draw_first4 = list(draw_nums[:4])

        # Show latest draw
        st.divider()
        st.markdown("### Latest Draw")
        st.markdown(
            f"**Date:** {draw_date} &nbsp;|&nbsp; "
            f"**Numbers:** {', '.join(f'{n:02d}' for n in draw_nums)} &nbsp;|&nbsp; "
            f"**Bonus:** {bonus:02d} &nbsp;|&nbsp; **PB:** {pb}"
        )

        # Show the first 4 numbers (Strike-relevant)
        st.markdown(
            f"**Strike numbers (first 4):** "
            f"{' → '.join(f'{n:02d}' for n in draw_first4)}"
        )

        # --- Compare ---
        st.divider()
        exact = count_exact_matches(strike_nums, draw_first4)
        result = calculate_strike_prize(exact)

        # Display comparison
        comp_cols = st.columns(4)
        for i, col in enumerate(comp_cols):
            player_val = strike_nums[i]
            draw_val = draw_first4[i]
            match = player_val == draw_val
            # Only show as match if all previous positions also matched
            if i > 0:
                prev_matches = all(strike_nums[j] == draw_first4[j] for j in range(i))
                if not prev_matches:
                    match = False

            with col:
                bg = "#d4edda" if match else "#f8d7da"
                fg = "#155724" if match else "#721c24"
                st.markdown(
                    f"<div style='text-align:center; background:{bg}; color:{fg}; "
                    f"padding:0.6rem; border-radius:6px; margin:0.2rem;'>"
                    f"<small>Ball {i + 1}</small><br>"
                    f"<b style='font-size:1.2rem;'>{player_val:02d}</b>"
                    f"<br><small>vs {draw_val:02d}</small>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        st.caption(
            "🟢 Green = match &nbsp;|&nbsp; 🔴 Red = no match (stops checking after first mismatch)"
        )

        # --- Result ---
        st.divider()
        st.markdown("### Result")

        if result["division"] is None:
            st.warning(
                "No Strike win — 0 exact matches.  (You need at least Ball 1 to match.)"
            )
        else:
            st.success(f"**{result['division_label']}** — {exact} exact match(es)")
            st.metric(
                label="Estimated Prize",
                value=f"${result['prize']:,.2f}",
                help="Based on estimated Strike pool.  Actual prize depends on draw sales and number of winners.",
            )
            st.caption(
                "Note: Strike prizes are estimated.  Div 1–3 shares come from "
                "the Strike pool (~65% / 20% / 15%).  Div 4 is a fixed bonus selection."
            )

        # --- Division reference ---
        with st.expander("Strike Division Reference", expanded=False):
            st.markdown("""
            | Division | Name | Matches | Prize Type |
            |----------|------|---------|------------|
            | Div 1 | Strike Four | All 4 numbers in exact order | Pool share (~65%) |
            | Div 2 | Strike Three | First 3 numbers in exact order | Pool share (~20%) |
            | Div 3 | Strike Two | First 2 numbers in exact order | Pool share (~15%) |
            | Div 4 | Strike One | First number in exact order | Fixed ($1.00 bonus selection) |

            **Important:** Strike checks numbers in exact order from the first position.
            If Ball 1 doesn't match, you cannot win any Strike division.
            """)

        # --- Load API data if available ---
        st.divider()
        with st.expander("View as JSON (API response)", expanded=False):
            import json

            st.json(
                {
                    "draw_date": draw_date,
                    "draw_first4": draw_first4,
                    "player_numbers": strike_nums,
                    "exact_matches": exact,
                    "strike_division": result["division"],
                    "division_label": result["division_label"],
                    "prize": result["prize"],
                    "is_estimated": result["is_estimated"],
                }
            )


# =========================================================================
# PAGE: Custom Wheel Builder
# =========================================================================
elif page == "Custom Wheel Builder":
    st.markdown(
        '<h2 class="section-header">Custom Wheel Builder</h2>', unsafe_allow_html=True
    )
    st.markdown(
        "Create your own abbreviated wheel by entering a pool of numbers "
        "and choosing a coverage guarantee."
    )

    with st.expander("What is an abbreviated wheel?", expanded=False):
        st.markdown("""
        An **abbreviated (covering) wheel** lets you play a large set of numbers
        without buying every possible combination. If the right subset of your
        numbers is drawn, the wheel *guarantees* at least one ticket reaches a
        certain prize division.

        - **"4 if 4"** — if 4 of your numbers are drawn, you're guaranteed a 4‑match ticket.
        - **"4 if 5"** — if 5 are drawn, you're guaranteed a 4‑match ticket.
        - **"5 if 6"** — if all 6 are drawn, you're guaranteed a 5‑match ticket.
        """)

    col_left, col_right = st.columns([2, 1], gap="medium")

    with col_left:
        numbers_input = st.text_area(
            "Your numbers (comma or space separated, 6–20 numbers)",
            placeholder="e.g. 9, 11, 12, 14, 17, 18, 28, 38, 39, 40",
            height=100,
        )

    with col_right:
        guarantee = st.selectbox(
            "Guarantee",
            [
                "3 if 3",
                "3 if 4",
                "3 if 5",
                "3 if 6",
                "4 if 4",
                "4 if 5",
                "4 if 6",
                "5 if 5",
                "5 if 6",
            ],
            index=4,  # "4 if 4" is default
        )

    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        max_tix = st.number_input(
            "Max tickets",
            min_value=10,
            max_value=500,
            value=200,
            step=10,
        )

    # --- Include / Exclude numbers ---
    with st.expander("🔢 Include / Exclude Numbers"):
        include_nums = st.multiselect(
            "Include Numbers",
            list(range(1, 41)),
            key="include_nums_wheel",
            help="These numbers will be forced into the pool.",
        )
        exclude_nums = st.multiselect(
            "Exclude Numbers",
            list(range(1, 41)),
            key="exclude_nums_wheel",
            help="These numbers will be removed from the pool.",
        )
        overlap = set(include_nums) & set(exclude_nums)
        if overlap:
            st.error(
                f"Cannot include and exclude the same number(s): {sorted(overlap)}"
            )

    # --- Albert Recommended Pool ---
    use_albert = st.checkbox(
        "Use Albert Recommended Pool",
        value=False,
        key="use_albert_pool",
        help="Auto-select 10 numbers using Emil Albert's Positive/Negative "
        "classification over the last 20 draws (60% positive, 40% negative).",
    )
    if use_albert:
        from albert_analysis import get_recommended_pool

        conn_albert = sqlite3.connect("lotto.db")
        try:
            rec_pool: list[int] | None = get_recommended_pool(
                conn_albert,
                window_draws=20,
                target_pool_size=10,
                exclude_numbers=exclude_nums if exclude_nums else None,
            )
        finally:
            conn_albert.close()
    else:
        rec_pool = None

    # --- Albert Sum Range enforcement ---
    enforce_sum = st.checkbox(
        "Enforce Albert Sum Range",
        value=False,
        key="enforce_sum_range",
        help="Filters out generated tickets whose sum falls outside the "
        "central 90% of the last 30 draw sums (5% outliers trimmed "
        "from each tail).",
    )
    sum_range_param = None
    if enforce_sum:
        if draws:
            from sum_validator import calculate_dynamic_sum_range

            sum_range_param = calculate_dynamic_sum_range(
                [list(nums) for nums, _pb, _b, _d in draws], window=30
            )
            st.caption(
                f"Active sum range: **{sum_range_param[0]}–{sum_range_param[1]}** "
                f"(central 90% of the last 30 draws)"
            )
        else:
            st.warning("No draws loaded — sum-range enforcement skipped.")

    # --- Albert Block constraints (set on the 🧱 Albert Blocks page) ---
    block_constraints = st.session_state.get("block_constraints")
    if block_constraints:
        bc_col, bc_clear = st.columns([5, 1])
        bc_col.caption(
            f"🧱 Block constraints active — prefer "
            f"**{block_constraints['preferred_numbers']}**, avoid "
            f"**{block_constraints['avoid_numbers'] or 'none'}**."
        )
        if bc_clear.button("Clear", key="clear_block_constraints"):
            st.session_state.pop("block_constraints", None)
            st.rerun()

    generate_clicked = col_b.button(
        "Generate Wheel",
        type="primary",
        use_container_width=True,
    )

    # --- Auto-Optimize (GA) ---
    ga_quick = st.checkbox(
        "⚡ Quick Mode (faster, less optimal)",
        value=False,
        key="ga_quick_mode",
        help="Runs only 5,000 simulations per fitness evaluation instead of 50,000.",
    )
    optimize_clicked = st.button(
        "🧬 Auto‑Optimize (GA)",
        type="secondary",
        use_container_width=True,
        key="ga_optimize_btn",
        help="Evolve wheel parameters using a genetic algorithm to maximise expected value.",
    )

    if optimize_clicked:
        with st.spinner("Running genetic algorithm..."):
            conn_ga = sqlite3.connect("lotto.db")
            try:
                from ga_optimizer import WheelOptimizerGA

                ga = WheelOptimizerGA(
                    conn_ga, population_size=30, generations=10, quick=ga_quick
                )
                ga_result = ga.evolve()
            finally:
                conn_ga.close()

        mode_note = " (Quick Mode — 5,000 sims)" if ga_quick else ""
        st.success(
            f"✅ Optimised! Best EV: ${ga_result['best_fitness']:.4f}{mode_note}"
        )
        best = ga_result["best_individual"]
        st.markdown("**Optimised Parameters:**")
        st.json(best)

        # --- Fitness curve ---
        if ga_result["history"]:
            import plotly.graph_objects as go

            gens = [h["generation"] for h in ga_result["history"]]
            bests = [h["best_fitness"] for h in ga_result["history"]]
            avgs = [h["avg_fitness"] for h in ga_result["history"]]
            fig_ga = go.Figure()
            fig_ga.add_trace(
                go.Scatter(x=gens, y=bests, mode="lines+markers", name="Best")
            )
            fig_ga.add_trace(
                go.Scatter(x=gens, y=avgs, mode="lines+markers", name="Average")
            )
            fig_ga.update_layout(
                title="GA Fitness Over Generations",
                xaxis_title="Generation",
                yaxis_title="EV ($)",
                height=300,
            )
            st.plotly_chart(fig_ga, use_container_width=True)

        # Auto-fill the pool with Albert-recommended numbers at the optimised pool size
        from albert_analysis import get_recommended_pool

        conn_pool = sqlite3.connect("lotto.db")
        try:
            opt_pool = get_recommended_pool(
                conn_pool, window_draws=20, target_pool_size=best["pool_size"]
            )
        finally:
            conn_pool.close()
        st.info(
            f"Suggested pool ({len(opt_pool)} numbers): {', '.join(str(n) for n in opt_pool)}"
        )

    if generate_clicked:
        # Parse numbers — use Albert pool if enabled and text area is empty
        if use_albert and rec_pool:
            raw = numbers_input.strip()
            if not raw:
                raw = ", ".join(str(n) for n in rec_pool)
                numbers_input = raw  # update the text area display
        else:
            raw = numbers_input.strip()

        if not raw:
            st.warning("Enter at least 6 numbers (1–40).")
            st.stop()

        parts = raw.replace(",", " ").split()
        try:
            nums = [int(x) for x in parts]
        except ValueError:
            st.error("All values must be integers.")
            st.stop()

        # Validate
        err = None
        if len(nums) < 6:
            err = f"Enter at least 6 numbers (got {len(nums)})."
        elif len(nums) > 40:
            err = f"At most 40 numbers allowed (got {len(nums)})."
        elif len(set(nums)) != len(nums):
            err = "Duplicate numbers detected."
        elif any(n < 1 or n > 40 for n in nums):
            err = "All numbers must be between 1 and 40."

        if err:
            st.error(err)
            st.stop()

        # Generate — merge Albert block constraints (prefer hot zones,
        # strip cold numbers) with the user's own include/exclude choices
        prefer_merge = list(rec_pool) if (use_albert and rec_pool) else []
        exclude_merge = list(exclude_nums) if exclude_nums else []
        if block_constraints:
            prefer_merge.extend(block_constraints["preferred_numbers"])
            prefer_set = set(prefer_merge)
            exclude_merge.extend(
                n for n in block_constraints["avoid_numbers"] if n not in prefer_set
            )
        with st.spinner("Generating wheel…"):
            tickets, guarantee_desc = generate_abbreviated_wheel(
                nums,
                guarantee,
                max_tickets=max_tix,
                prefer_numbers=prefer_merge or None,
                include_numbers=include_nums if include_nums else None,
                exclude_numbers=exclude_merge or None,
                sum_range=sum_range_param,
                verbose=False,
            )

        if not tickets:
            st.warning(guarantee_desc)
            st.stop()

        # Results
        st.success(f"**{len(tickets)}** tickets generated")

        overview_cols = st.columns([2, 2, 2, 2], gap="medium")
        overview_cols[0].metric("Tickets", len(tickets))
        overview_cols[1].metric("Cost", f"${len(tickets) * 1.50:.2f}")
        overview_cols[2].metric("Pool size", f"{len(set(nums))} numbers")
        overview_cols[3].metric("Guarantee", guarantee)

        st.info(guarantee_desc)

        # --- Bonus hot-zone coverage ---
        try:
            from wheel_generator import bonus_hotzone_coverage

            conn_hz = sqlite3.connect("lotto.db")
            try:
                hz_pct, hz_hot, hz_hits = bonus_hotzone_coverage(tickets, conn_hz)
            finally:
                conn_hz.close()
            if hz_hot:
                hz_cols = st.columns([1, 3], gap="medium")
                hz_cols[0].metric("Bonus Hot-Zone Coverage", f"{hz_pct:.1f}%")
                hz_cols[1].caption(
                    f"Hot zone (top {len(hz_hot)} bonus numbers, last 50 draws): "
                    f"{hz_hot} — your pool hits: {hz_hits or 'none'}"
                )
            else:
                st.caption("Bonus hot-zone coverage unavailable (no bonus data).")
        except Exception:
            pass  # metric is informational only

        # Ticket table
        ticket_data = [
            {
                "Ticket": i + 1,
                "Main Numbers": ", ".join(f"{x:02d}" for x in sorted(t)),
            }
            for i, t in enumerate(tickets)
        ]
        st.data_editor(
            pd.DataFrame(ticket_data),
            width="stretch",
            hide_index=True,
            disabled=True,
            use_container_width=True,
        )

        # --- Lotto Code Compliance Score ---
        try:
            conn_score = sqlite3.connect("lotto.db")
            from albert_analysis import classify_numbers
            from block_analysis import compute_block_ranges
            from compliance_scorer import get_score_breakdown, score_wheel
            from sum_analysis import dynamic_sum_range

            albert_state = classify_numbers(conn_score, window_draws=20)
            block_ranges = compute_block_ranges(draws, window_draws=30)
            sum_rng = dynamic_sum_range(conn_score, window_draws=30)
            albert_state["block_ranges"] = block_ranges
            albert_state["sum_range"] = sum_rng

            breakdown = get_score_breakdown(tickets, albert_state)
            total = breakdown["total_score"]
            color_emoji = "🟢" if total >= 80 else ("🟡" if total >= 60 else "🔴")

            st.markdown(f"### {color_emoji} Lotto Code Score: **{total}/100**")
            with st.expander("Score Breakdown"):
                st.markdown(
                    f"- **Pos/Neg Balance (40%):** {breakdown['pos_neg']:.1f}\n"
                    f"- **Block Compliance (30%):** {breakdown['block_compliance']:.1f}\n"
                    f"- **Sum Validity (20%):** {breakdown['sum_validity']:.1f}\n"
                    f"- **Numerical Attraction (10%):** {breakdown['numerical_attraction']:.1f}"
                )
        finally:
            if "conn_score" in dir():
                conn_score.close()

        with st.expander("Pool numbers used"):
            st.write(", ".join(str(n) for n in sorted(set(nums))))

        # Export
        csv_data = pd.DataFrame(
            {
                "Main Numbers": [
                    ", ".join(f"{x:02d}" for x in sorted(t)) for t in tickets
                ],
                "Powerball": ["—"] * len(tickets),
            }
        )
        csv_string = csv_data.to_csv(index=False)
        st.download_button(
            "Download CSV",
            csv_string,
            f"custom_{guarantee.replace(' ', '_')}_{len(tickets)}tickets.csv",
            "text/csv",
            use_container_width=True,
        )


# =========================================================================
# PAGE: Bonus Ball Analysis
# =========================================================================
elif page == "Bonus Ball Analysis":
    st.markdown(
        '<h2 class="section-header">Bonus Ball Analysis</h2>', unsafe_allow_html=True
    )

    # Resolve optional date filters from sidebar text inputs
    start_filter = st.session_state.get("bonus_date_start", "").strip() or None
    end_filter = st.session_state.get("bonus_date_end", "").strip() or None

    conn = sqlite3.connect("lotto.db")
    try:
        df = get_bonus_freq(conn, start_date=start_filter, end_date=end_filter)
    finally:
        conn.close()

    if df.empty:
        st.warning("No bonus ball data found for the selected date range.")
    else:
        total_draws = df["count"].sum()
        expected = total_draws / 40.0
        mean_val = df["count"].mean()
        std_val = df["count"].std(ddof=0)  # population std

        # --- Display toggle ---
        display_mode = st.radio(
            "Display mode",
            ["Counts", "Percentages"],
            horizontal=True,
            key="bonus_display_mode",
        )

        if display_mode == "Percentages":
            y_values = df["freq_pct"].values
            y_label = "Frequency (%)"
            expected_y = 100.0 / 40.0  # 2.5%
            # For colour thresholds in percentage mode, convert mean/std to pct
            mean_pct = df["freq_pct"].mean()
            std_pct = df["freq_pct"].std(ddof=0)
            upper_threshold = mean_pct + 0.5 * std_pct
            lower_threshold = mean_pct - 0.5 * std_pct
        else:
            y_values = df["count"].values
            y_label = "Count"
            expected_y = expected
            upper_threshold = mean_val + 0.5 * std_val
            lower_threshold = mean_val - 0.5 * std_val

        # --- Colour logic ---
        colours = []
        for v in y_values:
            if v > upper_threshold:
                colours.append("#e74c3c")  # red
            elif v < lower_threshold:
                colours.append("#2980b9")  # blue
            else:
                colours.append("#95a5a6")  # grey

        # --- Bar chart ---
        fig, ax = plt.subplots(figsize=(12, 5), constrained_layout=True)
        ax.bar(
            df["bonus_number"],
            y_values,
            color=colours,
            edgecolor="white",
            linewidth=0.3,
        )
        ax.axhline(
            y=expected_y,
            color="red",
            linestyle="--",
            linewidth=1.2,
            label=f"Expected ({expected_y:.2f})",
        )
        ax.set_xlabel("Bonus Ball Number")
        ax.set_ylabel(y_label)
        ax.set_title(
            f"Bonus Ball Frequency — {total_draws} draws"
            + (
                f" ({start_filter} to {end_filter})"
                if start_filter or end_filter
                else ""
            )
        )
        ax.set_xticks(range(1, 41, 2))
        ax.set_xticks(range(1, 41), minor=True)
        ax.set_xlim(0.5, 40.5)
        ax.legend(loc="upper right", fontsize=8)

        st.pyplot(fig)
        plt.close(fig)

        # --- Legend ---
        st.caption(
            f"Red: above mean + 0.5σ  |  Blue: below mean − 0.5σ  |  "
            f"Grey: within ±0.5σ  |  Mean: {mean_val:.2f}  |  σ: {std_val:.2f}"
        )

        # --- Download CSV ---
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()
        st.download_button(
            label="Download Bonus Frequency CSV",
            data=csv_data,
            file_name="bonus_frequency.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.divider()

        # --- Prediction Model selector ---
        st.markdown("### Prediction Model")
        pred_model = st.radio(
            "Model",
            ["Basic Bayesian", "Hierarchical Bayesian"],
            horizontal=True,
            key="bonus_pred_model",
        )

        # Build (date, bonus) pairs for hierarchical model
        bonus_draw_pairs = []
        for _nums, _pb, bonus, date in draws:
            if bonus and 1 <= bonus <= 40:
                bonus_draw_pairs.append((date, bonus))

        if pred_model == "Hierarchical Bayesian" and bonus_draw_pairs:
            from predictions import HierarchicalBonusPredictor

            halo = st.slider(
                "Recency half‑life (days)",
                min_value=30,
                max_value=365,
                value=90,
                step=15,
                key="bonus_halflife",
            )
            hmodel = HierarchicalBonusPredictor(
                bonus_draw_pairs, recency_halflife_days=halo
            )
            hmodel.fit()

            if hmodel.posterior_mean:
                top_k = hmodel.predict_top_k(k=40)  # get all 40 for bar chart

                st.markdown("#### Hierarchical Posterior Probabilities (±1σ)")
                import plotly.graph_objects as go

                bonus_nums = [t[0] for t in top_k]
                means = [t[1] for t in top_k]
                stds = [t[2] for t in top_k]
                lower = [max(0, m - s) for m, s in zip(means, stds, strict=False)]
                upper = [m + s for m, s in zip(means, stds, strict=False)]

                fig = go.Figure()
                cast(Any, fig).add_trace(
                    go.Bar(
                        x=bonus_nums,
                        y=means,
                        error_y={
                            "type": "data",
                            "symmetric": False,
                            "array": [
                                u - m for u, m in zip(upper, means, strict=False)
                            ],
                            "arrayminus": [
                                m - lo for m, lo in zip(means, lower, strict=False)
                            ],
                        },
                        marker_color="#3498db",
                        name="Posterior mean ±1σ",
                    )
                )
                cast(Any, fig).update_layout(
                    title=f"Hierarchical Bayesian Posterior — ½‑life={halo}d",
                    xaxis_title="Bonus Ball Number",
                    yaxis_title="Posterior Probability",
                    xaxis={"tickmode": "linear", "tick0": 1, "dtick": 2},
                    height=400,
                )
                st.plotly_chart(fig, use_container_width=True)

                # Top-5 table
                top5 = hmodel.predict_top_k(k=5)
                top5_df = pd.DataFrame(top5, columns=["Bonus #", "Mean", "Std"])
                top5_df["Mean"] = top5_df["Mean"].apply(lambda x: f"{x:.4%}")
                top5_df["Std"] = top5_df["Std"].apply(lambda x: f"{x:.4%}")
                top5_df.index = cast(Any, range(1, 6))
                top5_df.index.name = "Rank"
                st.table(top5_df)
                st.caption(
                    f"Posterior sum: {sum(hmodel.posterior_mean.values()):.6f} "
                    "(should be ~1.0). Higher weight on recent draws."
                )

        elif pred_model == "Basic Bayesian" and bonus_draw_pairs:
            from predictions import BonusBayesian

            bb = [b for _date, b in bonus_draw_pairs]
            bmodel = BonusBayesian(bb, alpha=1.0)
            top_k_basic = bmodel.predict_top_k(k=5)

            st.markdown("#### Basic Bayesian — Top 5 Predictions")
            result_df = pd.DataFrame(
                top_k_basic, columns=["Bonus Number", "Probability"]
            )
            result_df["Probability"] = result_df["Probability"].apply(
                lambda x: f"{x:.4%}"
            )
            result_df.index = cast(Any, range(1, 6))
            result_df.index.name = "Rank"
            st.table(result_df)
            st.caption(
                "Dirichlet-Multinomial posterior with α=1.0 prior. "
                "All draws weighted equally."
            )

        st.divider()

        # --- Detailed stats table ---
        st.markdown("### Bonus Ball Statistics Table")

        col_refresh, _col_pad = st.columns([1, 4])
        if col_refresh.button("🔄 Refresh Stats", key="bonus_stats_refresh"):
            st.session_state.pop("bonus_stats_cache", None)
            st.rerun()

        # Cache the stats computation keyed by filters + refresh flag
        cache_key = f"bonus_stats_{start_filter}_{end_filter}"
        if (
            "bonus_stats_cache" not in st.session_state
            or st.session_state.get("bonus_stats_key") != cache_key
        ):
            conn2 = sqlite3.connect("lotto.db")
            try:
                stats_list = get_bonus_stats(
                    conn2, start_date=start_filter, end_date=end_filter
                )
            finally:
                conn2.close()
            st.session_state["bonus_stats_cache"] = stats_list
            st.session_state["bonus_stats_key"] = cache_key
        else:
            stats_list = st.session_state["bonus_stats_cache"]

        if stats_list:
            stats_df = pd.DataFrame(stats_list)
            stats_df = stats_df.set_index("number")

            # Highlight rows where |z_score| > 2.0
            def highlight_z(row: pd.Series) -> list[str]:
                if (
                    isinstance(row.get("z_score"), int | float)
                    and abs(row["z_score"]) > 2.0
                ):
                    return [
                        "background-color: #ffe0e0; font-weight: bold; color: #c0392b"
                    ] * len(row)
                return [""] * len(row)

            styled = stats_df.style.apply(highlight_z, axis=1)

            st.dataframe(
                styled,
                use_container_width=True,
                height=600,
                column_config={
                    "count": st.column_config.NumberColumn("Count", width="small"),
                    "frequency": st.column_config.NumberColumn(
                        "Freq %", format="%.2f%%", width="small"
                    ),
                    "last_drawn": st.column_config.TextColumn(
                        "Last Drawn", width="small"
                    ),
                    "gap": st.column_config.TextColumn("Gap", width="small"),
                    "z_score": st.column_config.NumberColumn(
                        "Z-Score", format="%.2f", width="small"
                    ),
                },
            )
            st.caption("Rows with |z-score| > 2.0 are highlighted in red.")


# =========================================================================
# PAGE: Predictions
# =========================================================================
elif page == "Predictions":
    st.markdown('<h2 class="section-header">Predictions</h2>', unsafe_allow_html=True)

    predict_mode = st.selectbox(
        "Predict Bonus",
        ["Bayesian", "Gap Method", "Ensemble"],
        key="predict_bonus_mode",
    )

    if st.button("Run Prediction", use_container_width=True, type="primary"):
        if not draws:
            st.warning("No draw data loaded.")
        else:
            if predict_mode == "Bayesian":
                # Collect all bonus balls from loaded draws
                bonus_balls = [
                    bonus
                    for _, _, bonus, _ in draws
                    if bonus is not None and 1 <= bonus <= 40
                ]
                if not bonus_balls:
                    st.warning("No bonus ball data available.")
                else:
                    model = BonusBayesian(bonus_balls, alpha=1.0)
                    top_k_bb = model.predict_top_k(k=5)

                    st.markdown("### Bonus Bayesian — Top 5 Predictions")
                    result_df = pd.DataFrame(
                        top_k_bb, columns=["Bonus Number", "Posterior Probability"]
                    )
                    result_df["Posterior Probability"] = result_df[
                        "Posterior Probability"
                    ].apply(lambda x: f"{x:.4%}")
                    result_df.index = cast(Any, range(1, len(result_df) + 1))
                    result_df.index.name = "Rank"
                    st.table(result_df)

                    st.caption(
                        "Dirichlet-Multinomial posterior with α=1.0 prior. "
                        "Higher probability → more likely to be drawn."
                    )

                    st.session_state["last_prediction"] = {
                        "mode": "Bayesian Bonus",
                        "rows": [(int(n), float(p)) for n, p in top_k_bb],
                    }

            elif predict_mode == "Gap Method":
                conn = sqlite3.connect("lotto.db")
                try:
                    top_k_gap = bonus_gap_prediction(conn, k=5)
                finally:
                    conn.close()

                if not top_k_gap:
                    st.warning("No bonus ball data available in database.")
                else:
                    st.markdown("### Gap Method — Top 5 Predictions")
                    result_df = pd.DataFrame(
                        top_k_gap, columns=["Bonus Number", "Combined Score"]
                    )
                    result_df["Combined Score"] = result_df["Combined Score"].apply(
                        lambda x: f"{x:.4f}"
                    )
                    result_df.index = cast(Any, range(1, len(result_df) + 1))
                    result_df.index.name = "Rank"
                    st.table(result_df)

                    st.caption(
                        "Combined = 0.5 × gap_zscore + 0.5 × frequency_zscore. "
                        "Lower score → more 'due'."
                    )

                    st.session_state["last_prediction"] = {
                        "mode": "Gap Bonus",
                        "rows": [(int(n), float(s)) for n, s in top_k_gap],
                    }

            elif predict_mode == "Ensemble":
                conn = sqlite3.connect("lotto.db")
                try:
                    from ensemble import EnsemblePredictor

                    ep = EnsemblePredictor(conn)
                    ep.fit_weights(validation_draws=10)
                    preds = ep.predict_all(main_top=20, bonus_top=5, pb_top=3)
                finally:
                    conn.close()

                st.markdown("### Ensemble Predictions")

                # --- Weights chart ---
                if ep.weight_history:
                    st.markdown("#### Sub‑Predictor Weights Over Time")
                    import plotly.graph_objects as go

                    fig_w = go.Figure()
                    for method in ep.method_names:
                        vals = [w.get(method, 0) for w in ep.weight_history]
                        fig_w.add_trace(
                            go.Scatter(
                                y=vals,
                                mode="lines+markers",
                                name=method,
                            )
                        )
                    fig_w.update_layout(
                        title="Walk‑Forward Weight Calibration",
                        xaxis_title="Validation Draw",
                        yaxis_title="Weight",
                        height=300,
                    )
                    st.plotly_chart(fig_w, use_container_width=True)

                # --- Main numbers ---
                st.markdown("#### Top 20 Main Numbers")
                main_df = pd.DataFrame(
                    preds["main"], columns=["Number", "Ensemble Prob"]
                )
                main_df["Ensemble Prob"] = main_df["Ensemble Prob"].apply(
                    lambda x: f"{x:.4%}"
                )
                main_df.index = cast(Any, range(1, len(main_df) + 1))
                main_df.index.name = "Rank"
                st.dataframe(main_df, use_container_width=True)

                # --- Bonus ---
                if preds["bonus"]:
                    st.markdown("#### Top 5 Bonus Balls")
                    bonus_df = pd.DataFrame(
                        preds["bonus"], columns=["Bonus #", "Probability"]
                    )
                    bonus_df["Probability"] = bonus_df["Probability"].apply(
                        lambda x: f"{x:.4%}"
                    )
                    bonus_df.index = cast(Any, range(1, 6))
                    bonus_df.index.name = "Rank"
                    st.table(bonus_df)

                # --- Powerball ---
                st.markdown("#### Top 3 Powerballs")
                pb_df = pd.DataFrame(preds["powerball"], columns=["PB", "Probability"])
                pb_df["Probability"] = pb_df["Probability"].apply(lambda x: f"{x:.4%}")
                pb_df.index = cast(Any, range(1, 4))
                pb_df.index.name = "Rank"
                st.table(pb_df)

                # --- Current weights ---
                st.caption(
                    "Current weights: "
                    + ", ".join(
                        f"{m}={w:.3f}" for m, w in preds["ensemble_weights"].items()
                    )
                )

                st.session_state["last_prediction"] = {
                    "mode": "Ensemble Main",
                    "rows": [(int(n), float(p)) for n, p in preds["main"]],
                }

    # ---- CSV export of the current prediction run ----
    last_pred = st.session_state.get("last_prediction")
    if last_pred:
        import datetime as _dt

        df_dl = pd.DataFrame(last_pred["rows"], columns=["Number", "Probability"])
        df_dl.index = cast(Any, range(1, len(df_dl) + 1))
        df_dl.index.name = "Rank"
        csv = df_dl.to_csv()
        fname = f"predictions_{_dt.datetime.now().strftime('%Y-%m-%d_%H%M')}.csv"
        st.download_button(
            f"⬇️ Download Predictions CSV ({last_pred['mode']})",
            csv,
            fname,
            "text/csv",
            use_container_width=True,
        )

    # ---- SHAP feature importance (XGBoost) ----
    with st.expander("🧠 SHAP Feature Importance (XGBoost)"):
        shap_path = "data/plots/shap_summary.png"
        if st.button("Generate SHAP Summary Plot", key="shap_gen_btn"):
            if not draws:
                st.warning("No draw data loaded.")
            else:
                with st.spinner("Training XGBoost and computing SHAP values…"):
                    from predictions import XGBoostPredictor

                    xgb_model = XGBoostPredictor(draws).fit(window_draws=200)
                    saved = xgb_model.save_shap_summary_plot(shap_path)
                if saved:
                    st.success(f"SHAP summary plot saved to `{saved}`.")
                else:
                    st.info(
                        "SHAP plot unavailable — requires the `shap` package "
                        "and enough draw history (6+ draws)."
                    )
        if os.path.exists(shap_path):
            st.image(shap_path, caption="SHAP summary — global feature importance")


# =========================================================================
# PAGE: EV Simulation
# =========================================================================
elif page == "EV Simulation":
    st.markdown(
        '<h2 class="section-header">EV Simulation — Bonus Premium</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Monte Carlo simulation that estimates the expected value premium "
        "of matching the bonus ball across all tickets in a wheel."
    )

    sim_wheel = st.selectbox(
        "Select wheel",
        wheel_names,
        key="ev_sim_wheel",
    )

    col_sims, col_btn = st.columns([2, 1])
    with col_sims:
        num_sims = st.number_input(
            "Number of simulations",
            min_value=10_000,
            max_value=5_000_000,
            value=100_000,
            step=10_000,
            format="%d",
            key="ev_num_sims",
        )
    with col_btn:
        st.write("")  # spacer
        run_sim = st.button("Run Simulation", type="primary", use_container_width=True)

    if run_sim:
        with st.spinner(f"Running {num_sims:,} simulations..."):
            results = simulate_bonus_ev(sim_wheel, num_sims=num_sims)

        st.divider()

        # --- Metrics row ---
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("EV with Bonus", f"${results['ev_with_bonus']:,.4f}")
        c2.metric("EV without Bonus", f"${results['ev_without_bonus']:,.4f}")
        c3.metric(
            "Bonus Premium",
            f"{results['bonus_premium_percent']:+.2f}%",
            delta=f"{results['bonus_premium_percent']:+.2f}%",
        )
        c4.metric("Tickets Upgraded", f"{results['upgrade_count']:,}")

        st.divider()

        # --- Bar chart ---
        import matplotlib.pyplot as plt
        import numpy as np

        fig, ax = plt.subplots(figsize=(6, 4), constrained_layout=True)
        categories = ["Without Bonus", "With Bonus"]
        values = [results["ev_without_bonus"], results["ev_with_bonus"]]
        colours = ["#95a5a6", "#27ae60"]
        ev_bars = ax.bar(
            categories, values, color=colours, edgecolor="white", linewidth=0.5
        )
        ax.set_ylabel("Expected Value ($)")
        ax.set_title(f"EV Comparison — {sim_wheel} ({num_sims:,} sims)")

        # Annotate bars
        for bar, val in zip(ev_bars, values, strict=False):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.01,
                f"${val:,.4f}",
                ha="center",
                fontsize=10,
                fontweight="bold",
            )

        # Add premium annotation
        mid_x = 0.5
        mid_y = max(values) * 1.05
        ax.annotate(
            f"+{results['bonus_premium_percent']:.2f}%",
            xy=(mid_x, mid_y),
            fontsize=12,
            fontweight="bold",
            color="#27ae60",
            ha="center",
        )

        st.pyplot(fig)
        plt.close(fig)


# =========================================================================
# PAGE: Bonus–Main Co‑occurrence
# =========================================================================
elif page == "Bonus–Main Co‑occurrence":
    st.markdown(
        '<h2 class="section-header">Bonus–Main Co‑occurrence</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Analyse which main numbers most frequently appear alongside each bonus ball."
    )

    # --- Date range from sidebar ---
    start_filter = st.session_state.get("bonus_date_start", "").strip() or None
    end_filter = st.session_state.get("bonus_date_end", "").strip() or None

    @st.cache_data(ttl=_CACHE_TTL)  # type: ignore[used-before-def]  # defined in the "Check Latest Draw" page branch; Streamlit branches are mutually exclusive
    def _load_cooccurrence(_start: Any, _end: Any) -> Any:
        """Load co-occurrence data from lotto.db with optional date filter."""
        conn = sqlite3.connect("lotto.db")
        try:
            # Build a filtered connection view — we filter at query level
            # by passing dates through to the functions
            matrix = compute_cooccurrence_matrix(conn, min_support=1)
            triplets = get_top_triplets(conn, top_n=20)
            # We'll cache the full matrix and re-filter in display logic
            return matrix, triplets
        finally:
            conn.close()

    if st.button("Load Co‑occurrence Data", use_container_width=True, type="primary"):
        with st.spinner("Computing co-occurrence matrix..."):
            matrix, triplets = _load_cooccurrence(start_filter, end_filter)

        if matrix.empty:
            st.warning("No co-occurrence data found.")
        else:
            st.success(
                f"Matrix computed: {matrix.shape[0]} bonus × {matrix.shape[1]} main numbers."
            )

            # ---- Heatmap ----
            st.markdown("### Co‑occurrence Heatmap")
            st.markdown(
                "*Bonus balls (Y) vs Main numbers (X). Darker = more frequent.*"
            )

            import matplotlib.pyplot as plt
            import numpy as np

            fig, ax = plt.subplots(figsize=(14, 10), constrained_layout=True)
            data = matrix.values.astype(float)
            # Log-scale for better visibility of small counts
            data_log = np.log1p(data)

            im = ax.imshow(
                data_log,
                aspect="auto",
                cmap="YlOrRd",
                origin="lower",
                extent=cast(tuple[float, float, float, float], [0.5, 40.5, 0.5, 40.5]),
            )
            ax.set_xlabel("Main Number")
            ax.set_ylabel("Bonus Ball Number")
            ax.set_title("Bonus–Main Co‑occurrence (log₁₀ scale)")
            ax.set_xticks(range(1, 41, 2))
            ax.set_xticks(range(1, 41), minor=True)
            ax.set_yticks(range(1, 41, 2))
            ax.set_yticks(range(1, 41), minor=True)

            cbar = fig.colorbar(im, ax=ax, shrink=0.8)
            cbar.set_label("log(count + 1)")

            st.pyplot(fig)
            plt.close(fig)

            st.divider()

            # ---- Bonus-specific top pairs ----
            st.markdown("### Top Main Numbers per Bonus Ball")
            selected_bonus = st.selectbox(
                "Select bonus ball",
                list(range(1, 41)),
                key="cooccur_bonus_select",
            )

            if st.button("Show Top Pairs", key="cooccur_pairs_btn"):
                conn = sqlite3.connect("lotto.db")
                try:
                    pairs = get_top_pairs_for_bonus(conn, selected_bonus, top_k=3)
                finally:
                    conn.close()

                if pairs:
                    pairs_df = pd.DataFrame(
                        pairs, columns=["Main Number", "Co‑occurrence Count"]
                    )
                    pairs_df.index = cast(Any, range(1, len(pairs_df) + 1))
                    pairs_df.index.name = "Rank"
                    st.table(pairs_df)
                else:
                    st.info(f"No co-occurrence data for bonus ball {selected_bonus}.")

            st.divider()

            # ---- Top triplets ----
            st.markdown("### Top 10 Bonus–Main–Main Triplets")
            if triplets:
                trip_df = pd.DataFrame(
                    triplets, columns=["Bonus", "Main 1", "Main 2", "Count"]
                )
                trip_df.index = cast(Any, range(1, min(len(trip_df), 10) + 1))
                trip_df.index.name = "Rank"
                st.table(trip_df.head(10))
            else:
                st.info("No triplet data available.")


# =========================================================================
# PAGE: Rotation Scheduler
# =========================================================================
elif page == "Rotation Scheduler":
    st.markdown(
        '<h2 class="section-header">Rotation Scheduler</h2>', unsafe_allow_html=True
    )
    st.markdown(
        "Generate a Bayesian rotation plan for NZ Lotto Powerball. "
        "Each period swaps out the weakest number for the next-best candidate."
    )

    include_bonus = st.checkbox(
        "Include Bonus Rotation", value=False, key="rot_include_bonus"
    )

    if st.button("Generate Rotation Plan", use_container_width=True, type="primary"):
        with st.spinner("Loading draws and computing..."):
            try:
                rotation_draws = load_rotation_draws()
            except SystemExit:
                st.error("Rotation database not found. Run update_draws.py first.")
                st.stop()

            # cast: two different bayesian_posterior imports share the name;
            # the rotation_scheduler variant (bound last) accepts these draws
            posterior = bayesian_posterior(cast(Any, rotation_draws))
            schedule = build_rotation(posterior)

            bonus_picks = None
            if include_bonus:
                bonus_picks = bonus_bayesian_predictor(rotation_draws, k=3)

        st.success(f"Generated {len(schedule)} periods ({len(schedule) * 2} draws)")

        # Build table rows
        rot_rows = []
        prev_set = None
        for i, nums in enumerate(schedule, 1):
            rot_row = {
                "Period": i,
                "Numbers": ", ".join(f"{n:02d}" for n in nums),
            }
            if prev_set:
                dropped = prev_set - set(nums)
                added = set(nums) - prev_set
                rot_row["Change"] = ""
                if dropped:
                    rot_row["Change"] += f"−{min(dropped):02d}"
                if added:
                    rot_row["Change"] += f"+{min(added):02d}"
            else:
                rot_row["Change"] = "—"

            if bonus_picks:
                pk = bonus_picks[min(i - 1, len(bonus_picks) - 1)]
                rot_row["Bonus Picks"] = f"#{pk[0]:02d} ({pk[1]:.1%})"

            rot_rows.append(rot_row)
            prev_set = set(nums)

        df = pd.DataFrame(rot_rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(f"Powerball: {3} | Pool size: 11 | Prior α: 1.0")


# =========================================================================
# PAGE: Backtest Results
# =========================================================================
elif page == "Backtest Results":
    st.markdown(
        '<h2 class="section-header">Backtest — Bonus Impact</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Analyse how the bonus ball affects historical prize outcomes for a wheel."
    )

    bt_wheel = st.selectbox("Select wheel", wheel_names, key="bt_wheel")

    col_bt, _bt_pad = st.columns([1, 3])

    # Clear cache button
    col_clr, _clr_pad = st.columns([1, 3])
    if col_clr.button(
        "Clear Backtest Cache", use_container_width=True, key="clear_bt_cache"
    ):
        st.cache_data.clear()
        st.toast("Backtest cache cleared!", icon=":material/check:")

    if col_bt.button("Run Backtest", type="primary", use_container_width=True):
        with st.spinner(f"Running backtest on {bt_wheel}..."):

            @st.cache_data(
                ttl=_CACHE_TTL,  # type: ignore[used-before-def]  # defined in the "Check Latest Draw" page branch; Streamlit branches are mutually exclusive
                hash_funcs={dict: lambda d: str(sorted(d.items()))},
            )
            def _cached_backtest(wheel_name: str, nd: int | None) -> Any:
                return backtest_bonus_impact(wheel_name, nd)

            data = _cached_backtest(bt_wheel, None)

        if "error" in data:
            st.error(data["error"])
        else:
            # --- Metrics ---
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "Total Prize (with bonus)", f"${data['total_prize_with_bonus']:,.2f}"
            )
            c2.metric(
                "Total Prize (no bonus)", f"${data['total_prize_without_bonus']:,.2f}"
            )
            c3.metric(
                "Bonus Premium",
                f"{data['bonus_premium_percent']:+.2f}%",
                delta=f"{data['bonus_premium_percent']:+.2f}%",
            )
            st.caption(
                f"Draws tested: {data['draws_tested']}  |  "
                f"Upgraded tickets: {data['upgraded_tickets']}  |  "
                f"Value added: ${data['bonus_added_value']:,.2f}"
            )

            # --- Upgrade breakdown bar chart ---
            breakdown = data.get("upgrade_breakdown", {})
            if breakdown:
                st.divider()
                st.markdown("### Upgrade Breakdown")

                import matplotlib.pyplot as plt
                import numpy as np

                labels = sorted(breakdown)
                values = [breakdown[k] for k in labels]

                fig, ax = plt.subplots(figsize=(8, 4), constrained_layout=True)
                # cast: matplotlib colormaps are registered dynamically; the
                # stubs don't expose them as attributes of plt.cm
                colours = cast(Any, plt.cm).RdYlGn(np.linspace(0.2, 0.8, len(labels)))
                div_bars = ax.bar(
                    labels, values, color=colours, edgecolor="white", linewidth=0.5
                )
                ax.set_xlabel("Division Upgrade")
                ax.set_ylabel("Ticket Count")
                ax.set_title(
                    f"Bonus Upgrade Breakdown — {bt_wheel} ({data['draws_tested']} draws)"
                )

                for bar, val in zip(div_bars, values, strict=False):
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(values) * 0.02,
                        str(val),
                        ha="center",
                        fontsize=9,
                        fontweight="bold",
                    )

                st.pyplot(fig)
                plt.close(fig)
            else:
                st.info("No bonus upgrades detected in this backtest.")

    # --- Multi-wheel comparison ---
    st.divider()
    st.markdown("### Multi‑Wheel Comparison (with Confidence Intervals)")
    st.markdown("Bootstrap 95% CI + paired t‑test vs best method.")

    if st.button(
        "Run Multi‑Wheel Comparison",
        type="primary",
        use_container_width=True,
        key="multi_bt",
    ):
        with st.spinner("Running backtests for all wheels..."):
            summary = generate_backtest_summary(n_bootstrap=1000)

        if summary:
            df = pd.DataFrame(summary)
            df["Mean"] = df["mean_score"].apply(lambda x: f"${x:,.2f}")
            df["95% CI"] = df.apply(
                lambda r: f"[${r['ci_lower']:,.2f}, ${r['ci_upper']:,.2f}]", axis=1
            )
            df["p-value"] = df["p_value"].apply(
                lambda p: f"{p:.4f}" if p < 1.0 else "— (best)"
            )

            # --- Plotly bar chart with error bars ---
            import plotly.graph_objects as go

            fig_bt = go.Figure()
            for _, r in df.iterrows():
                color = (
                    "#27ae60" if r["significant"] or r["p_value"] >= 1.0 else "#95a5a6"
                )
                fig_bt.add_trace(
                    go.Bar(
                        x=[r["method"]],
                        y=[r["mean_score"]],
                        error_y={
                            "type": "data",
                            "symmetric": False,
                            "array": [r["ci_upper"] - r["mean_score"]],
                            "arrayminus": [r["mean_score"] - r["ci_lower"]],
                        },
                        marker_color=color,
                        name=r["method"],
                        text=f"${r['mean_score']:,.2f}",
                        textposition="outside",
                    )
                )
            fig_bt.update_layout(
                title="Mean Prize per Draw — 95% Bootstrap CI",
                yaxis_title="Prize ($)",
                showlegend=False,
                height=400,
            )
            st.plotly_chart(fig_bt, use_container_width=True)

            # --- Stats table ---
            st.markdown("#### Statistical Summary")
            st.dataframe(
                df[["method", "Mean", "95% CI", "p-value"]],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "🟢 Green bars = significantly different from best method (p < 0.05)."
            )
        else:
            st.warning("Could not generate comparison — no draw data available.")


# =========================================================================
# PAGE: Multi-Draw Backtest
# =========================================================================
elif page == "Multi-Draw Backtest":
    from backtest import run_multi_draw_backtest

    st.markdown(
        '<h2 class="section-header">Multi-Draw Backtest — Jackpot Rollover</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Simulates consecutive draws with realistic **jackpot rollover**. "
        "When Div 1 has no winner, the prize pool rolls to the next draw. "
        "After 10 consecutive no-Div1 draws, a **must-win** draw is forced."
    )

    # --- Controls ---
    col1, col2, col3 = st.columns(3)
    with col1:
        mw_wheel = st.selectbox("Wheel", list(WHEELS.keys()), key="mw_wheel")
    with col2:
        mw_nd = st.slider("Number of draws", 5, 50, 10, 5, key="mw_nd")
    with col3:
        mw_start = st.number_input(
            "Start draw index",
            min_value=0,
            max_value=max(0, len(draws) - mw_nd),
            value=max(0, len(draws) - mw_nd),
            step=1,
            key="mw_start",
        )

    mw_turnover = st.number_input(
        "Turnover per draw (NZD)",
        min_value=100_000,
        max_value=100_000_000,
        value=2_500_000,
        step=500_000,
        format="%d",
        key="mw_turnover",
    )

    col1_btn, col2_btn = st.columns([3, 1])
    with col1_btn:
        run_clicked = st.button(
            "Run Multi-Draw Backtest", type="primary", use_container_width=True
        )
    with col2_btn:
        if st.button("Clear Cache", use_container_width=True, key="clear_md_cache"):
            st.cache_data.clear()
            st.toast("Multi-draw cache cleared!")

    if run_clicked:
        with st.spinner(f"Running {mw_nd}-draw backtest with jackpot rollover..."):
            result = run_multi_draw_backtest(
                mw_wheel,
                start_draw_id=mw_start,
                num_draws=mw_nd,
                base_turnover=float(mw_turnover),
            )

        if "error" in result:
            st.error(result["error"])
        else:
            # --- Summary cards ---
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Total Cost", f"${result['total_cost']:,.0f}")
            c2.metric("Total Prize", f"${result['total_prize']:,.0f}")
            c3.metric("Net", f"${result['net']:,.0f}")
            c4.metric("ROI", f"{result['roi_pct']:+.1f}%")
            c5.metric("Jackpot Events", result["jackpot_occurrences"])

            c6, c7, c8 = st.columns(3)
            c6.metric("Forced Distributions", result["forced_distributions"])
            c7.metric("Final Jackpot", f"${result['final_carried_jackpot']:,.0f}")
            c8.metric("Final Streak", result["final_consecutive_no_div1"])

            st.divider()

            # --- Draw-by-draw table ---
            st.markdown("### Draw-by-Draw Results")
            draw_rows = []
            for rec in result["draw_records"]:
                nums_str = ", ".join(f"{n:02d}" for n in rec["draw_numbers"])
                draw_rows.append(
                    {
                        "Draw": rec["draw_index"],
                        "Date": rec["draw_date"],
                        "Numbers": nums_str,
                        "PB": rec["draw_pb"],
                        "Div1 Wins": rec["div1_winners"],
                        "Prize": f"${rec['draw_prize']:,.2f}",
                        "Jackpot": f"${rec['jackpot_carried']:,.0f}",
                        "Streak": rec["consecutive_no_div1"],
                        "Forced": "⚡" if rec["forced_distribution"] else "",
                        "Div1/winner": f"${rec['per_winner_div1']:,.0f}"
                        if rec["per_winner_div1"] > 0
                        else "—",
                    }
                )
            import pandas as pd

            df_mw = pd.DataFrame(draw_rows)
            st.dataframe(df_mw, use_container_width=True, hide_index=True)

            # --- Jackpot growth chart ---
            st.divider()
            st.markdown("### Jackpot Growth Over Draws")
            jp_values = [r["jackpot_carried"] for r in result["draw_records"]]
            jp_draws = list(range(1, len(jp_values) + 1))

            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 3.5))
            ax.fill_between(jp_draws, jp_values, alpha=0.25, color="#e74c3c")
            ax.plot(
                jp_draws,
                jp_values,
                marker="o",
                color="#c0392b",
                linewidth=2,
                markersize=6,
            )
            ax.set_xlabel("Draw Number")
            ax.set_ylabel("Carried Jackpot ($)")
            ax.set_title(f"Jackpot Growth — {result['wheel']} wheel")
            from matplotlib.ticker import FuncFormatter

            ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
            ax.grid(True, alpha=0.3)
            st.pyplot(fig)
            plt.close(fig)

            st.caption(
                "The jackpot grows when Div 1 has no winner. "
                "After 10 consecutive draws without a Div 1 winner, "
                "a must-win draw is forced and the jackpot cascades to lower divisions."
            )


# =========================================================================
# PAGE: Block Analysis
# =========================================================================
elif page == "Block Analysis":
    st.markdown(
        '<h2 class="section-header">Block Analysis — Positional Ranges</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Analyses the 6 positional slots (1st–6th, sorted) across the last N draws "
        "to show which bucket (1-10, 11-20, 21-30, 31-40) each position most "
        "frequently falls into."
    )

    window = st.slider(
        "Window draws",
        min_value=10,
        max_value=200,
        value=30,
        step=10,
        key="block_window",
    )
    min_pos = st.slider(
        "Min positions to match",
        min_value=2,
        max_value=6,
        value=4,
        key="block_min_pos",
    )

    if not draws:
        st.warning("No draw data loaded.")
    else:
        from block_analysis import (
            build_position_heatmap_data,
            compute_block_ranges,
            validate_positional_ranges,
        )

        pos_ranges = compute_block_ranges(draws, window_draws=window)

        if pos_ranges:
            # --- Heatmap ---
            z_data, x_labels, y_labels = build_position_heatmap_data(
                draws, window_draws=window
            )

            import plotly.graph_objects as go

            fig = go.Figure(
                data=go.Heatmap(
                    z=z_data,
                    x=x_labels,
                    y=y_labels,
                    colorscale="YlOrRd",
                    text=[[f"{v:.1%}" for v in row] for row in z_data],
                    texttemplate="%{text}",
                    textfont={"size": 11},
                    colorbar={"title": "Fraction"},
                )
            )
            cast(Any, fig).update_layout(
                title=f"Positional Block Heatmap — Last {window} Draws",
                xaxis_title="Number Bucket",
                yaxis_title="Position (sorted)",
                height=380,
            )
            st.plotly_chart(fig, use_container_width=True)

            # --- Summary table ---
            st.markdown("### Optimal Buckets per Position")
            bucket_rows = []
            for slot in sorted(pos_ranges, key=int):
                r = pos_ranges[slot]
                bucket_rows.append(
                    {
                        "Position": r["position"],
                        "Optimal Bucket": r["optimal_label"],
                        "Confidence": f"{r['confidence']:.1%}",
                    }
                )
            st.dataframe(
                pd.DataFrame(bucket_rows), use_container_width=True, hide_index=True
            )

            # --- Historical validation ---
            st.divider()
            st.markdown(f"### Historical Compliance (min {min_pos} positions)")
            recent = draws[-window:] if len(draws) > window else draws
            passing = 0
            total = len(recent)
            for nums, _pb2, _bonus2, _date2 in recent:
                if validate_positional_ranges(
                    sorted(nums), pos_ranges, min_positions=min_pos
                ):
                    passing += 1
            pct = passing / total * 100 if total > 0 else 0
            st.metric(
                f"Draws passing ≥{min_pos} positions",
                f"{passing}/{total}",
                delta=f"{pct:.1f}%",
            )
            if pct >= 80:
                st.success("Achieved ≥80% compliance — positional filter is reliable.")
            else:
                st.warning("Below 80% compliance — consider lowering min_positions.")


# =========================================================================
# PAGE: 🧱 Albert Blocks
# =========================================================================
elif page == "🧱 Albert Blocks":
    st.markdown(
        '<h2 class="section-header">🧱 Albert Blocks — Hot Zones</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Emil Albert splits the 40-number pool into five blocks of eight "
        "(1-8, 9-16, 17-24, 25-32, 33-40) and observed that within each block, "
        "recent hits cluster in a narrow **hot zone** of 3-4 numbers. This page "
        "finds those zones empirically from recent draws and can push the "
        "resulting constraints into the wheel generator."
    )

    lookback = st.slider(
        "Lookback draws",
        min_value=10,
        max_value=200,
        value=30,
        step=10,
        key="albert_blocks_lookback",
    )

    if not draws:
        st.warning("No draw data loaded.")
    else:
        from block_targeting import (
            analyze_block_distribution,
            generate_block_constraints,
            score_wheel_blocks,
        )

        # cast: analyze_block_distribution's stub types info values as object
        analysis = cast(
            Any,
            analyze_block_distribution(
                [list(nums) for nums, _pb, _b, _d in draws], lookback=lookback
            ),
        )

        # --- Heatmap of per-number frequencies (★ marks hot-zone numbers) ---
        import plotly.graph_objects as go

        z_data, text_data, y_labels = [], [], []
        for block_id, blk_info in analysis.items():
            lo, hi = blk_info["range"]
            zone = set(blk_info["hot_zone"])
            row, text_row = [], []
            for n in range(lo, hi + 1):
                f = blk_info["number_freq"].get(n, 0)
                row.append(f)
                text_row.append(f"{'★' if n in zone else ''}{n}: {f}")
            z_data.append(row)
            text_data.append(text_row)
            y_labels.append(f"Block {block_id} ({lo}-{hi})")

        fig = go.Figure(
            data=go.Heatmap(
                z=z_data,
                x=[str(i) for i in range(1, 9)],
                y=y_labels,
                colorscale="YlOrRd",
                text=text_data,
                texttemplate="%{text}",
                textfont={"size": 11},
                colorbar={"title": "Hits"},
            )
        )
        cast(Any, fig).update_layout(
            title=f"Block Frequencies — Last {lookback} Draws (★ = hot zone)",
            xaxis_title="Position within block",
            yaxis_title="Block",
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- Hot zones per block (red badges) ---
        st.markdown("### Hot Zones per Block")
        hz_cols = st.columns(5)
        for col, (block_id, blk_info) in zip(hz_cols, analysis.items(), strict=False):
            lo, hi = blk_info["range"]
            badges = " ".join(
                '<span style="background-color:#e74c3c;color:white;'
                'border-radius:4px;padding:2px 6px;margin:1px;">'
                f"{n}</span>"
                for n in blk_info["hot_zone"]
            )
            col.markdown(
                f"**Block {block_id}** ({lo}–{hi})<br>{badges}<br>"
                f"<small>freq {blk_info['frequency']} · "
                f"{blk_info['coverage_pct']}% of block hits<br>"
                f"avg {blk_info['avg_per_draw']}/draw</small>",
                unsafe_allow_html=True,
            )

        # --- Score a wheel against the hot zones ---
        st.divider()
        score_input = st.text_input(
            "Score a wheel against the hot zones",
            key="albert_blocks_score_input",
            placeholder="e.g. 3, 10, 18, 25, 33, 40",
        )
        if score_input.strip():
            try:
                wheel_nums = [int(x) for x in score_input.replace(",", " ").split()]
                score, rec = score_wheel_blocks(wheel_nums, analysis)
                st.metric("Block score", f"{score:.2f}")
                st.info(rec)
            except ValueError:
                st.error("Enter valid integers between 1 and 40.")

        # --- Apply constraints to the wheel generator ---
        st.divider()
        if st.button(
            "Apply Block Constraints",
            type="primary",
            key="apply_block_constraints",
            help="Stores hot-zone numbers as preferred and numbers absent for "
            "the whole lookback as excluded; applied on Wheels & Tickets.",
        ):
            st.session_state["block_constraints"] = generate_block_constraints(analysis)
            st.success(
                "Constraints saved — they will be applied next time you "
                "generate a wheel on the Wheels & Tickets page."
            )

        existing = st.session_state.get("block_constraints")
        if existing:
            st.caption(
                f"Active constraints — min per block: {existing['min_per_block']}, "
                f"preferred: {existing['preferred_numbers']}, "
                f"avoid: {existing['avoid_numbers'] or 'none'}"
            )


# =========================================================================
# PAGE: ➕➖ Pos/Neg
# =========================================================================
elif page == "➕➖ Pos/Neg":
    st.markdown(
        '<h2 class="section-header">➕➖ Positive / Negative Tracker</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Albert's auto-tagger ranks all 40 numbers by frequency over the last "
        "30 draws: **Positive** (hot) = top 33%, **Negative** (cold) = bottom 33%, "
        "**Neutral** = the middle. When 3+ numbers swap polarity between "
        "rebalances, a **distribution shift** is flagged — time to rebuild wheels."
    )

    if not draws:
        st.warning("No draw data loaded.")
    else:
        from pos_neg_tracker import (
            SHIFT_THRESHOLD,
            classify_pos_neg,
            shift_timeline,
        )

        draw_lists = [list(nums) for nums, _pb, _b, _d in draws]
        cls = classify_pos_neg(draw_lists)

        def _pn_badges(nums: Any, color: str) -> str:
            return " ".join(
                f'<span style="background-color:{color};color:white;'
                f'border-radius:4px;padding:2px 6px;margin:1px;">{n}</span>'
                for n in nums
            )

        pos_col, neu_col, neg_col = st.columns(3)
        pos_col.markdown(
            f"**Positive (hot)** — {len(cls['positive'])}<br>"
            + _pn_badges(cls["positive"], "#27ae60"),
            unsafe_allow_html=True,
        )
        neu_col.markdown(
            f"**Neutral** — {len(cls['neutral'])}<br>"
            + _pn_badges(cls["neutral"], "#95a5a6"),
            unsafe_allow_html=True,
        )
        neg_col.markdown(
            f"**Negative (cold)** — {len(cls['negative'])}<br>"
            + _pn_badges(cls["negative"], "#e74c3c"),
            unsafe_allow_html=True,
        )

        # --- Shift timeline ---
        st.divider()
        st.markdown("### Shift Timeline")
        st.caption(
            "Polarity crossings (Positive↔Negative) between consecutive "
            "30-draw windows, replayed over the loaded history."
        )
        timeline = shift_timeline(draw_lists)
        if timeline:
            tl_df = pd.DataFrame(timeline).set_index("draw_index")
            st.line_chart(tl_df)
        else:
            st.info("Not enough draws to build a timeline (need 31+).")

        # --- Alert banner ---
        latest_count = timeline[-1]["shift_count"] if timeline else 0
        if latest_count >= SHIFT_THRESHOLD:
            st.error(
                f"⚠️ **Distribution shift detected after the latest draw** — "
                f"{latest_count} numbers crossed Positive↔Negative "
                f"(threshold {SHIFT_THRESHOLD}). Regenerate your wheels."
            )
        else:
            st.success(
                f"No distribution shift in the latest draw "
                f"({latest_count} crossings, threshold {SHIFT_THRESHOLD})."
            )

        # --- Last alert persisted by the scheduler ---
        try:
            conn_pn = sqlite3.connect("lotto.db")
            try:
                last_alert = conn_pn.execute(
                    "SELECT alert_message, timestamp FROM pos_neg_history "
                    "WHERE alert_message IS NOT NULL ORDER BY id DESC LIMIT 1"
                ).fetchone()
            finally:
                conn_pn.close()
            if last_alert:
                st.warning(f"Last scheduler alert ({last_alert[1]}): {last_alert[0]}")
        except sqlite3.OperationalError:
            pass  # pos_neg_history not created yet


# =========================================================================
# PAGE: 💰 Arbitrage
# =========================================================================
elif page == "💰 Arbitrage":
    st.markdown(
        '<h2 class="section-header">💰 Lottery Arbitrage — EV Scanner</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Every game's EV rises with the jackpot while the odds stay fixed. "
        "This page scans international lotteries and flags games whose current "
        "jackpot exceeds their **rollover threshold** (the break-even jackpot). "
        "Jackpots come from APIVerve when an API key is configured, otherwise "
        "from the manual values in `config/jackpot_thresholds.json`."
    )

    tax_adjusted = st.checkbox(
        "Tax-adjusted EV (lump-sum discount + federal/state tax)",
        value=False,
        key="arb_tax_adjusted",
        help="Applies each game's lump_sum_ratio and tax rates from the config. "
        "For US Powerball this moves the break-even from ~$490M to ~$1.1B.",
    )

    from arbitrage import (
        load_game_configs,
        probability_tree,
        scan_opportunities,
    )

    results = scan_opportunities(tax_adjusted=tax_adjusted)

    if not results:
        st.warning("No games configured — check config/jackpot_thresholds.json.")
    else:
        game_rows = []
        for r in results:
            game_rows.append(
                {
                    "Game": r["game_name"],
                    "Jackpot": r["current_jackpot"],
                    "Source": r["jackpot_source"],
                    "Threshold": r["rollover_threshold"],
                    "Ticket $": r["ticket_price_usd"],
                    "EV": r["ev"],
                    "EV per $": r["ev_per_dollar"],
                    "Call": r["recommendation"],
                }
            )
        df = pd.DataFrame(game_rows)

        def _highlight_play(row: pd.Series) -> list[str]:
            color = "background-color: #14532d; color: #86efac" if row["EV"] > 0 else ""
            return [color] * len(row)

        st.dataframe(
            df.style.apply(_highlight_play, axis=1).format(
                {
                    "Jackpot": "{:,.0f}",
                    "Threshold": "{:,.0f}",
                    "Ticket $": "{:.2f}",
                    "EV": "{:+.3f}",
                    "EV per $": "{:+.3f}",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("Green rows are EV-positive at the current jackpot.")

        # --- Detailed math for one game ---
        st.divider()
        game_names = {r["game_name"]: r["game_code"] for r in results}
        selected_name = st.selectbox(
            "Show detailed math for", list(game_names), key="arb_game_select"
        )
        code = game_names[selected_name]
        result = next(r for r in results if r["game_code"] == code)
        cfg = load_game_configs()[code]

        tax_rate = 0.0
        lump = 1.0
        if tax_adjusted:
            tax_rate = float(cfg.get("federal_tax", 0)) + float(cfg.get("state_tax", 0))
            lump = float(cfg.get("lump_sum_ratio", 1.0))

        m1, m2, m3 = st.columns(3)
        m1.metric("Current jackpot", f"{result['current_jackpot']:,.0f}")
        m2.metric("Rollover threshold", f"{result['rollover_threshold']:,.0f}")
        m3.metric("EV per dollar", f"{result['ev_per_dollar']:+.3f}")

        st.markdown("#### Probability tree")
        tree = probability_tree(
            cfg, result["current_jackpot"], tax_rate=tax_rate, lump_sum_ratio=lump
        )
        tree_df = pd.DataFrame(tree).rename(
            columns={
                "division": "Div",
                "match": "Match",
                "probability": "Probability",
                "one_in": "1 in …",
                "prize": "Prize",
                "ev_contribution": "EV contribution",
            }
        )
        st.dataframe(
            tree_df.style.format(
                {
                    "Probability": "{:.3e}",
                    "1 in …": "{:,.0f}",
                    "Prize": "{:,.0f}",
                    "EV contribution": "{:+.6f}",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            f"EV = Σ(probability × prize) − ticket price "
            f"({result['ticket_price_usd']:.2f}) = {result['ev']:+.4f} "
            f"→ **{result['recommendation']}**"
        )


# =========================================================================
# PAGE: ⚛️ Quantum Wheel
# =========================================================================
elif page == "⚛️ Quantum Wheel":
    st.markdown(
        '<h2 class="section-header">⚛️ Quantum Wheel — Simulated Quantum Annealing</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Optimises a wheel with **simulated quantum annealing** (classical "
        "simulation, not a real quantum computer): a transverse field Γ(t) "
        "decays over iterations, letting the search tunnel between local "
        "minima before settling. Energy = −(pair coverage + attraction "
        "alignment) + λ × (block + sum violations)."
    )

    from quantum_selector import (
        _wheel_pair_coverage,
        benchmark_quantum_vs_ga,
        build_attraction_profile,
        quantum_anneal_wheel,
        wheel_energy,
    )

    q_col1, q_col2 = st.columns(2)
    with q_col1:
        q_iterations = st.slider(
            "Iterations", 1_000, 50_000, 10_000, 1_000, key="q_iterations"
        )
        q_gamma = st.slider(
            "Initial Γ (transverse field)", 0.5, 5.0, 2.0, 0.1, key="q_gamma"
        )
    with q_col2:
        q_cooling = st.slider(
            "Cooling rate",
            0.9990,
            0.99999,
            0.9995,
            0.00001,
            format="%.5f",
            key="q_cooling",
        )
        q_tickets = st.slider("Tickets", 4, 30, 10, 1, key="q_tickets")

    # --- Optional constraints from draw history ---
    use_constraints = st.checkbox(
        "Apply Albert constraints (attraction, blocks, sum range)",
        value=True,
        key="q_use_constraints",
        help="Builds the attraction profile, block constraints, and dynamic "
        "sum range from the loaded draw history.",
    )

    attraction_profile = block_constraints_q = sum_range_q = None
    if use_constraints:
        if draws and len(draws) >= 10:
            draw_lists_q = [list(nums) for nums, _pb, _b, _d in draws]
            from block_targeting import (
                analyze_block_distribution,
                generate_block_constraints,
            )
            from sum_validator import calculate_dynamic_sum_range

            attraction_profile = build_attraction_profile(draw_lists_q)
            block_constraints_q = generate_block_constraints(
                analyze_block_distribution(draw_lists_q)
            )
            sum_range_q = calculate_dynamic_sum_range(draw_lists_q)
            st.caption(
                f"Constraints active — {len(attraction_profile)} hot pairs, "
                f"sum range {sum_range_q[0]}–{sum_range_q[1]}."
            )
        else:
            st.info("Need 10+ loaded draws for constraints — running unconstrained.")

    if st.button(
        "Generate Quantum Wheel",
        type="primary",
        use_container_width=True,
        key="q_generate",
    ):
        with st.spinner(f"Annealing {q_iterations:,} iterations..."):
            wheel = quantum_anneal_wheel(
                num_tickets=q_tickets,
                iterations=q_iterations,
                initial_gamma=q_gamma,
                cooling_rate=q_cooling,
                attraction_profile=attraction_profile,
                block_constraints=block_constraints_q,
                sum_range=sum_range_q,
            )
        st.session_state["quantum_wheel"] = wheel

    q_wheel = st.session_state.get("quantum_wheel")
    if q_wheel:
        energy = wheel_energy(
            q_wheel, 40, attraction_profile, block_constraints_q, sum_range_q
        )
        coverage = _wheel_pair_coverage(q_wheel, 40) * 100
        s1, s2, s3 = st.columns(3)
        s1.metric("Tickets", len(q_wheel))
        s2.metric("Pair coverage", f"{coverage:.1f}%")
        s3.metric("Energy", f"{energy:.4f}")

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Ticket": i + 1,
                        "Numbers": ", ".join(f"{n:02d}" for n in t),
                        "Sum": sum(t),
                    }
                    for i, t in enumerate(q_wheel)
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    # --- Side-by-side GA comparison ---
    st.divider()
    st.markdown("### ⚛️ vs 🧬 Benchmark")
    st.caption(
        "Runs the quantum annealer and the GA optimizer (quick mode) on the "
        "same constraints, scored with the same energy model. Results are "
        "appended to data/benchmarks/quantum_vs_ga.json."
    )
    if st.button(
        "Run Quantum vs GA Benchmark", use_container_width=True, key="q_benchmark"
    ):
        with st.spinner("Running both optimizers (GA uses quick Monte Carlo)..."):
            report = benchmark_quantum_vs_ga(
                iterations=min(q_iterations, 5000),
                num_tickets=q_tickets,
                ga_population=6,
                ga_generations=3,
            )
        st.session_state["q_benchmark"] = report

    report = cast(Any, st.session_state.get("q_benchmark"))
    if report:
        qc, gc = st.columns(2)
        qc.markdown("#### ⚛️ Quantum")
        qc.metric("Energy", report["quantum"]["best_energy"])
        qc.caption(
            f"{report['quantum']['tickets']} tickets · "
            f"{report['quantum']['pair_coverage_pct']}% coverage · "
            f"{report['quantum']['execution_time_s']}s"
        )
        gc.markdown("#### 🧬 Genetic Algorithm")
        if report["ga"].get("error"):
            gc.warning(f"GA failed: {report['ga']['error']}")
        else:
            gc.metric("Energy", report["ga"]["best_energy"])
            gc.caption(
                f"{report['ga']['tickets']} tickets · "
                f"{report['ga']['pair_coverage_pct']}% coverage · "
                f"{report['ga']['execution_time_s']}s · "
                f"EV fitness ${report['ga']['best_ev_fitness']:.4f}"
            )
        winner = (
            "⚛️ Quantum"
            if (
                report["ga"]["best_energy"] is None
                or report["quantum"]["best_energy"] <= report["ga"]["best_energy"]
            )
            else "🧬 GA"
        )
        st.success(f"Lower energy: **{winner}**")


# =========================================================================
# PAGE: 📚 Bluskov Library
# =========================================================================
elif page == "📚 Bluskov Library":
    st.markdown(
        '<h2 class="section-header">📚 Bluskov Wheel Library</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Browse published Bluskov systems, pick the mathematically minimal "
        "wheel for your guarantee, and select it for play. Selected wheels "
        "are substituted with your numbers and saved to `user_selected_wheels`."
    )

    from wheel_explorer import (
        GUARANTEE_TYPES,
        export_csv,
        filter_wheels,
        format_print,
        get_recommended,
        is_minimal,
        save_selection,
    )

    # --- Sidebar filters ---
    st.sidebar.markdown("### 📚 Library Filters")
    pool_range = st.sidebar.slider("Pool size", 6, 20, (6, 20), key="bl_pool")
    guarantee_label = st.sidebar.selectbox(
        "Guarantee type", ["All"] + list(GUARANTEE_TYPES), key="bl_guarantee"
    )
    ticket_range = st.sidebar.slider("Ticket count", 1, 100, (1, 100), key="bl_tickets")
    search = st.sidebar.text_input(
        "Search (system # or description)", key="bl_search", placeholder="e.g. 88"
    )

    matches = filter_wheels(
        pool_range=pool_range,
        guarantee_label=None if guarantee_label == "All" else guarantee_label,
        ticket_range=ticket_range,
        search=search,
    )

    # --- Auto-select the minimal system for the chosen guarantee ---
    recommended_keys = set()
    if guarantee_label != "All":
        for size in range(pool_range[0], pool_range[1] + 1):
            rec = get_recommended(guarantee_label, size)
            if rec:
                recommended_keys.add(rec["key"])
        recs = [w for w in matches if w["key"] in recommended_keys and w["ready"]]
        if recs:
            best = min(recs, key=lambda w: w["tickets"])
            st.info(
                f"💡 Recommended: **System #{best['system_number']}** — "
                f"{best['numbers']} numbers, {best['tickets']} tickets "
                f"({best['guarantee']}). Mathematically minimal for this guarantee."
            )
    else:
        st.caption(
            "Pick a guarantee type in the sidebar to get an auto-recommendation."
        )

    if not matches:
        st.warning("No wheels match the current filters.")
    else:
        for w in matches:
            recommended = w["key"] in recommended_keys
            minimal = is_minimal(w)
            border = (
                "border:3px solid #3b82f6;"
                if recommended
                else "border:1px solid #4b5563;"
            )
            badge_min = (
                (
                    ' <span style="background-color:#166534;color:#bbf7d0;'
                    'border-radius:4px;padding:1px 6px;font-size:12px;">'
                    "Mathematically Minimal</span>"
                )
                if minimal
                else ""
            )
            badge_pending = (
                (
                    ' <span style="background-color:#7c2d12;color:#fed7aa;'
                    'border-radius:4px;padding:1px 6px;font-size:12px;">'
                    "combinations pending</span>"
                )
                if not w["ready"]
                else ""
            )
            badge_rec = (
                (
                    ' <span style="background-color:#1e3a8a;color:#bfdbfe;'
                    'border-radius:4px;padding:1px 6px;font-size:12px;">'
                    "RECOMMENDED</span>"
                )
                if recommended
                else ""
            )

            with st.container():
                st.markdown(
                    f'<div style="{border}border-radius:8px;padding:12px;margin-bottom:4px;">'
                    f'<b>System #{w["system_number"]}</b> — {w["numbers"]} numbers, '
                    f'<b>{w["tickets"]} tickets</b>{badge_min}{badge_pending}{badge_rec}'
                    f'<br><small>{w["guarantee"]}</small></div>',
                    unsafe_allow_html=True,
                )

                if w["ready"]:
                    with st.expander(f"View Tickets ({w['tickets']})"):
                        st.code(format_print(w["wheel"]), language=None)

                    nums_raw = st.text_input(
                        f"Your {w['numbers']} numbers (comma-separated)",
                        key=f"bl_nums_{w['key']}",
                        placeholder="e.g. 3, 7, 12, 14, 18, 22, 29, 33, 38, 40",
                    )
                    if st.button("Select for Play", key=f"bl_select_{w['key']}"):
                        try:
                            user_nums = (
                                [int(x) for x in nums_raw.replace(",", " ").split()]
                                if nums_raw.strip()
                                else None
                            )
                            if user_nums and len(user_nums) != w["numbers"]:
                                st.error(
                                    f"This system needs exactly {w['numbers']} numbers "
                                    f"(got {len(user_nums)})."
                                )
                            else:
                                row_id = save_selection(w["key"], user_nums)
                                from bluskov_wheel_library import substitute_numbers

                                template = (
                                    substitute_numbers(w["wheel"], user_nums)
                                    if user_nums
                                    else w["wheel"]
                                )
                                st.session_state["play_template"] = {
                                    "wheel_key": w["key"],
                                    "system_number": w["system_number"],
                                    "tickets": template,
                                    "selection_id": row_id,
                                }
                                st.success(
                                    f"System #{w['system_number']} selected "
                                    f"(saved as selection #{row_id}) — see export below."
                                )
                        except ValueError as e:
                            st.error(str(e))
                else:
                    st.caption(
                        "⏳ Combinations must be transcribed from Bluskov's book "
                        "before this system can be used."
                    )

    # --- Export the active selection ---
    template = st.session_state.get("play_template")
    if template:
        st.divider()
        st.markdown(
            f"### Active Template — System #{template['system_number']} "
            f"({len(template['tickets'])} tickets)"
        )
        # cast: session_state values are dynamic; export helpers want list[list[int]]
        tickets = template["tickets"]
        csv_data = export_csv(cast(Any, tickets))
        exp1, exp2 = st.columns(2)
        exp1.download_button(
            "⬇️ Download CSV",
            data=csv_data,
            file_name=f"wheel_system_{template['system_number']}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        with exp2.expander("🖨️ Print-friendly view"):
            st.code(
                format_print(
                    cast(Any, tickets), title=f"System #{template['system_number']}"
                ),
                language=None,
            )


# =========================================================================
# PAGE: Wheel Explorer
# =========================================================================
elif page == "Wheel Explorer":
    st.markdown(
        '<h2 class="section-header">Wheel Explorer — Guarantee Validation</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Validate Bluskov wheel guarantees via Monte Carlo simulation "
        "and inspect pair-coverage matrices."
    )

    explore_wheel = st.selectbox("Select wheel", wheel_names, key="explore_wheel")

    col_sims, col_btn = st.columns([2, 1])
    with col_sims:
        num_sims = st.number_input(
            "Simulations",
            min_value=100,
            max_value=100_000,
            value=5_000,
            step=500,
            key="explore_num_sims",
        )
    with col_btn:
        st.write("")
        run_val = st.button("Run Validation", type="primary", use_container_width=True)

    if run_val:
        from wheel_validator import WheelValidator

        validator = WheelValidator(explore_wheel)

        with st.spinner(f"Running {num_sims:,} simulations..."):
            result = validator.validate_guarantee(num_simulations=num_sims)

        # --- Validation badge ---
        st.divider()
        st.markdown("### Guarantee Result")
        if result["passed"]:
            st.success(
                f"✅ **PASSED** — {result['claimed_guarantee']} "
                f"({result['coverage_ratio']:.1%} coverage over {result['simulations']:,} sims)"
            )
        else:
            st.error(
                f"❌ **FAILED** — {result['claimed_guarantee']} "
                f"(coverage: {result['coverage_ratio']:.1%}, "
                f"worst match: {result['worst_case_match']})"
            )

        # --- Stats row ---
        c1, c2, c3 = st.columns(3)
        c1.metric("Pool Size", validator.pool_size)
        c2.metric("Tickets", len(validator.tickets))
        c3.metric("Trigger Count", result["trigger_count"])

        # --- Coverage heatmap ---
        st.divider()
        st.markdown("### Pair‑Coverage Matrix")
        matrix = validator.coverage_matrix()

        import plotly.graph_objects as go

        labels = [str(n) for n in validator.pool_list]
        fig = go.Figure(
            data=go.Heatmap(
                z=matrix,
                x=labels,
                y=labels,
                colorscale="Blues",
                text=[[str(v) if v > 0 else "" for v in row] for row in matrix],
                texttemplate="%{text}",
                textfont={"size": 9},
                colorbar={"title": "Tickets"},
            )
        )
        cast(Any, fig).update_layout(
            title=f"Coverage Matrix — {explore_wheel} ({len(validator.tickets)} tickets)",
            xaxis_title="Number",
            yaxis_title="Number",
            height=550,
            width=650,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Diagonal = tickets containing that number. "
            "Off-diagonal = tickets containing both numbers."
        )


# =========================================================================
# PAGE: Live Monitor
# =========================================================================
elif page == "Live Monitor":
    st.markdown(
        '<h2 class="section-header">Live Monitor — Draw Alerts</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Monitor scheduled draw-result checks and alert history. "
        "The background scheduler runs every Thu/Sun at 8am."
    )

    import json
    import os

    CHECK_LOG = "scheduler_checks.log"
    ALERT_LOG = os.environ.get("ALERT_LOG", "alert.log")

    # --- Status ---
    st.markdown("### Next Scheduled Check")
    st.info(
        "⏰ **Thu & Sun at 8:00 AM** — comparing stored tickets against latest draw results."
    )

    alerts_enabled = st.checkbox(
        "Enable Win Alerts",
        value=True,
        key="live_alerts_enabled",
        help="Toggle email + desktop notifications for ticket wins.",
    )
    if alerts_enabled:
        st.success("Win alerts enabled.")
    else:
        st.warning("Win alerts disabled.")

    draw_alerts_enabled = st.checkbox(
        "New Draw Notifications",
        value=True,
        key="draw_alerts_toggle",
        help="Get notified when a new draw is fetched and imported.",
    )
    if draw_alerts_enabled:
        st.success("New draw notifications enabled.")
    else:
        st.warning("New draw notifications disabled.")

    # Store toggle state for scheduler/pipeline to read
    st.session_state["draw_alerts_enabled"] = draw_alerts_enabled

    # --- Stored tickets ---
    tickets_json = "latest_tickets.json"
    stored_count = 0
    if os.path.exists(tickets_json):
        with open(tickets_json) as f:
            td = json.load(f)
        stored_count = len(td.get("tickets", []))
    st.metric("Stored Tickets", stored_count)

    if st.button("Save Current Wheel Tickets", key="save_current_tickets"):
        # Save the currently displayed wheel tickets if any are loaded
        if "show_tickets" in st.session_state:
            wheel_name = st.session_state["show_tickets"]
            from lotto_wheels import WHEELS

            tickets, _ = WHEELS[wheel_name]
            from scheduler import save_tickets

            save_tickets([list(t) for t in tickets])
            st.success(f"Saved {len(tickets)} tickets from '{wheel_name}' wheel.")
        else:
            st.warning(
                "Select a wheel first (Wheels & Tickets page → Show Tickets & Cost)."
            )

    # --- Check log ---
    st.divider()
    st.markdown("### Check History")
    if os.path.exists(CHECK_LOG):
        with open(CHECK_LOG, encoding="utf-8") as f:
            lines = f.readlines()
        # Show last 20 lines
        log_lines = [line.strip() for line in lines[-20:] if line.strip()]
        if log_lines:
            st.code("\n".join(reversed(log_lines)), language="text")
        else:
            st.info("No checks recorded yet.")
    else:
        st.info("No check history. Run the scheduler to populate.")

    # --- Alert log ---
    st.divider()
    st.markdown("### Alert Log")
    if os.path.exists(ALERT_LOG):
        with open(ALERT_LOG, encoding="utf-8") as f:
            alert_lines = [line.strip() for line in f.readlines()[-20:] if line.strip()]
        if alert_lines:
            st.code("\n".join(reversed(alert_lines)), language="text")
        else:
            st.info("No alerts logged.")
    else:
        st.info("No alert log yet.")

    # --- Manual trigger ---
    st.divider()
    if st.button("🔍 Run Manual Check Now", type="primary", use_container_width=True):
        with st.spinner("Fetching latest draw and checking tickets..."):
            from scheduler import check_job

            check_job()
        st.success("Manual check complete — see Check History above.")
        st.rerun()


# =========================================================================
# PAGE: Notification Settings
# =========================================================================
elif page == "Notification Settings":
    from datetime import datetime as _dt_cls

    from notifier import (
        _get_smtp_config,
        get_all_notifier_settings,
        get_notifier_setting,
        log_alert,
        send_desktop_notification,
        send_email_alert,
        set_notifier_setting,
    )

    st.markdown(
        '<h2 class="section-header">Notification Settings</h2>', unsafe_allow_html=True
    )
    st.markdown("Configure email alerts, desktop notifications, and alert thresholds.")

    # ---- SMTP Config display ----
    st.divider()
    st.markdown("### Email (SMTP) Configuration")
    cfg = _get_smtp_config()
    c1, c2, c3 = st.columns(3)
    c1.metric("SMTP Server", cfg["server"])
    c2.metric("Port", cfg["port"])
    c3.metric("Username", cfg["username"] or "(not set)")
    st.caption(
        "Set SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD in .env or environment."
    )

    # ---- Alert toggles ----
    st.divider()
    st.markdown("### Alert Settings")

    email_enabled = get_notifier_setting("email_enabled", "true") == "true"
    desktop_enabled = get_notifier_setting("desktop_enabled", "true") == "true"

    col_a, col_b = st.columns(2)
    with col_a:
        new_email = st.toggle(
            "Email Notifications",
            value=email_enabled,
            key="toggle_email",
            help="Send email when a win is detected.",
        )
        if new_email != email_enabled:
            set_notifier_setting("email_enabled", "true" if new_email else "false")
            st.toast(
                "Email notifications " + ("enabled" if new_email else "disabled") + "!"
            )
    with col_b:
        new_desktop = st.toggle(
            "Desktop Notifications",
            value=desktop_enabled,
            key="toggle_desktop",
            help="Show Windows toast when a win is detected.",
        )
        if new_desktop != desktop_enabled:
            set_notifier_setting("desktop_enabled", "true" if new_desktop else "false")
            st.toast(
                "Desktop notifications "
                + ("enabled" if new_desktop else "disabled")
                + "!"
            )

    # ---- Minimum division threshold ----
    st.divider()
    st.markdown("### Alert Threshold")
    min_div = int(get_notifier_setting("min_division", "4"))
    new_min = st.selectbox(
        "Minimum division to trigger an alert",
        [1, 2, 3, 4, 5, 6, 7],
        index=7 - min_div,
        key="min_div_sel",
        help="Only divisions at or above this level will trigger an alert (1 = Div 1, 7 = any win).",
    )
    if new_min != min_div:
        set_notifier_setting("min_division", str(new_min))
        st.toast(f"Alert threshold set to Division {new_min} or better.")

    # ---- Monitored wheels ----
    st.divider()
    st.markdown("### Monitored Wheels")
    from lotto_wheels import WHEELS

    monitored_str = get_notifier_setting("monitored_wheels", "")
    monitored = monitored_str.split(",") if monitored_str else list(WHEELS.keys())

    cols = st.columns(3)
    new_monitored = []
    for i, name in enumerate(WHEELS.keys()):
        with cols[i % 3]:
            checked = name in monitored
            val = st.checkbox(name, value=checked, key=f"mon_{name}")
            if val:
                new_monitored.append(name)

    if set(new_monitored) != set(monitored):
        set_notifier_setting("monitored_wheels", ",".join(new_monitored))
        st.toast("Monitored wheels updated!")

    # ---- Test Alert ----
    st.divider()
    st.markdown("### Send Test Alert")
    st.markdown(
        "Trigger a dummy notification to verify your email/desktop configuration."
    )

    if st.button("Send Test Alert", type="primary", use_container_width=True):
        subject = "[TEST] Lotto Wheel App - Test Alert"
        body = (
            "This is a test alert from your NZ Lotto Wheel Analysis Platform.\n"
            f"Timestamp: {_dt_cls.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "If you received this, your notification configuration is working!\n"
        )
        email_ok = send_email_alert(subject, body)
        desktop_ok = send_desktop_notification(subject, body)
        log_alert(f"Test alert sent. Email: {email_ok}, Desktop: {desktop_ok}", "INFO")

        if email_ok:
            st.success("Test email sent! Check your inbox.")
        else:
            st.warning("Email not sent - check SMTP configuration.")
        if desktop_ok:
            st.success("Desktop notification shown!")
        else:
            st.info(
                "Desktop notification not available (install plyer for Windows toasts)."
            )

    # ---- Raw settings ----
    with st.expander("Raw Settings (debug)", expanded=False):
        all_settings = get_all_notifier_settings()
        st.json(all_settings if all_settings else {"(empty)": "no settings stored yet"})


# =========================================================================
# PAGE: Ticket Wizard
# =========================================================================
elif page == "Ticket Wizard":
    from ticket_wizard import render_wizard

    render_wizard()


# =========================================================================
# PAGE: International Lotteries
# =========================================================================
elif page == "International Lotteries":
    st.markdown(
        '<h2 class="section-header">International Lotteries</h2>',
        unsafe_allow_html=True,
    )
    st.markdown("Fetch results from international lotteries via APIVerve API.")

    # API key in session state
    if "intl_api_key" not in st.session_state:
        st.session_state["intl_api_key"] = ""

    api_key = st.text_input(
        "APIVerve API Key",
        value=st.session_state["intl_api_key"],
        type="password",
        placeholder="Enter your APIVerve API key",
        key="intl_key_input",
    )
    if api_key:
        st.session_state["intl_api_key"] = api_key

    lottery = st.selectbox(
        "Select Lottery",
        ["powerball", "mega-millions", "euromillions", "superenalotto", "oz-lotto"],
        key="intl_lottery",
    )

    if st.button("Fetch Results", type="primary", use_container_width=True):
        if not api_key:
            st.error("Enter an API key.")
        else:
            with st.spinner(f"Fetching {lottery} results..."):
                from api_fetcher import fetch_apiverve_lottery

                api_result = fetch_apiverve_lottery(api_key, lottery)

            if api_result:
                st.success(f"Results for {lottery} — {api_result['draw_date']}")
                df = pd.DataFrame(
                    [
                        {
                            "Draw Date": api_result["draw_date"],
                            "Main Numbers": ", ".join(
                                str(n) for n in api_result["main_numbers"]
                            ),
                            "Bonus Ball": api_result["bonus_ball"] or "—",
                            "Powerball": api_result["powerball"] or "—",
                            "Source": api_result["source"],
                        }
                    ]
                )
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Save to DB
                if st.button("Save to Database"):
                    conn = sqlite3.connect("lotto.db")
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS intl_draws (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            draw_date TEXT,
                            lottery_name TEXT,
                            numbers TEXT,
                            bonus INTEGER,
                            powerball INTEGER,
                            fetched_at TEXT DEFAULT (datetime('now'))
                        )
                    """)
                    nums_str = ",".join(str(n) for n in api_result["main_numbers"])
                    try:
                        conn.execute(
                            "INSERT INTO intl_draws (draw_date, lottery_name, numbers, bonus, powerball) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (
                                api_result["draw_date"],
                                lottery,
                                nums_str,
                                api_result["bonus_ball"] or 0,
                                api_result["powerball"] or 0,
                            ),
                        )
                        conn.commit()
                        st.success("Saved to intl_draws table.")
                    except sqlite3.IntegrityError:
                        st.warning("Draw already exists in database.")
                    finally:
                        conn.close()
            else:
                st.error(
                    "Failed to fetch results. Check API key and internet connection."
                )

    # Show saved
    st.divider()
    st.markdown("### Saved International Draws")
    try:
        conn2 = sqlite3.connect("lotto.db")
        rows = conn2.execute(
            "SELECT draw_date, lottery_name, numbers, bonus, powerball, fetched_at "
            "FROM intl_draws ORDER BY fetched_at DESC LIMIT 10"
        ).fetchall()
        conn2.close()
        if rows:
            df2 = pd.DataFrame(
                rows, columns=["Date", "Lottery", "Numbers", "Bonus", "PB", "Fetched"]
            )
            st.dataframe(df2, use_container_width=True, hide_index=True)
        else:
            st.info("No saved international draws yet.")
    except sqlite3.OperationalError:
        st.info("No saved draws (table not yet created).")


# =========================================================================
# PAGE: Pipeline Status
# =========================================================================
elif page == "Pipeline Status":
    st.markdown(
        '<h2 class="section-header">Data Pipeline Status</h2>', unsafe_allow_html=True
    )
    st.markdown("Monitor the unified data-fetching pipeline and view recent activity.")

    if st.button("Manual Fetch Now", type="primary", use_container_width=True):
        with st.spinner("Running data pipeline..."):
            from data_pipeline import fetch_latest_job

            fetch_latest_job()
        st.success("Pipeline run complete. Check status below.")

    st.divider()

    # Show pipeline stats
    try:
        from data_pipeline import DataFetcher

        fetcher = DataFetcher()
        stats = fetcher.get_stats()

        if stats:
            df = pd.DataFrame(stats)
            # Success rate
            total = len(df)
            successes = df["success"].sum()
            rate = successes / total * 100 if total > 0 else 0
            c1, c2 = st.columns(2)
            c1.metric("Last Run", df.iloc[0]["run_time"])
            c2.metric("Success Rate", f"{rate:.1f}%", delta=f"{successes}/{total} runs")

            # Per-source breakdown
            st.markdown("#### Success by Source")
            source_stats = df.groupby("source")["success"].agg(["sum", "count"])
            source_stats["rate"] = (
                source_stats["sum"] / source_stats["count"] * 100
            ).round(1)
            st.dataframe(source_stats, use_container_width=True)

            # Recent errors
            errors = df[~df["success"]]
            if len(errors) > 0:
                st.markdown("#### Recent Errors")
                st.dataframe(
                    errors[["run_time", "source", "error"]],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info("No pipeline runs recorded yet.")
    except Exception as e:
        st.warning(f"Pipeline stats unavailable: {e}")


# =========================================================================
# PAGE: ML Predictor
# =========================================================================
elif page == "ML Predictor":
    st.markdown(
        '<h2 class="section-header">ML Predictor — XGBoost + SHAP</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Train a gradient-boosted trees model on historical draws "
        "and interpret predictions with SHAP values."
    )

    # --- Session state initialisation ---
    if "xgb_model" not in st.session_state:
        st.session_state["xgb_model"] = None
    if "xgb_shap_done" not in st.session_state:
        st.session_state["xgb_shap_done"] = False

    # --- Train button ---
    train_needed = True
    if st.session_state.get("xgb_model") is not None and hasattr(
        st.session_state["xgb_model"], "draws_hash"
    ):
        current_hash = hash(str([d[0] for d in draws[-200:]])) if draws else 0
        if current_hash == st.session_state["xgb_model"].draws_hash:
            train_needed = False

    train_clicked = st.button(
        "Train XGBoost Model", type="primary", use_container_width=True
    )
    if train_clicked or (st.session_state.get("xgb_model") is None):
        with st.spinner("Training XGBoost on historical draws..."):
            from datetime import datetime

            from predictions import XGBoostPredictor

            xgb = XGBoostPredictor(draws)
            xgb.fit(window_draws=200)
            xgb.last_trained_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # type: ignore[attr-defined]  # dashboard-attached metadata attr
            xgb.draws_hash = hash(str([d[0] for d in draws[-200:]])) if draws else 0  # type: ignore[attr-defined]  # dashboard-attached metadata attr

        if xgb.model:
            st.session_state["xgb_model"] = xgb
            st.session_state["xgb_shap_done"] = False
            st.success(f"Model trained successfully at {xgb.last_trained_on}")  # type: ignore[attr-defined]  # set just above
        else:
            st.warning("Training failed — not enough data. Need at least 6 draws.")

    from datetime import datetime

    xgb = cast(Any, st.session_state.get("xgb_model"))

    if xgb is not None and xgb.model:
        # --- Predictions ---
        st.divider()
        st.markdown("### Top 15 Predicted Numbers")
        top_k_xgb = xgb.predict_top_k(k=15)
        pred_df = pd.DataFrame(top_k_xgb, columns=["Number", "Probability"])
        pred_df["Probability"] = pred_df["Probability"].apply(lambda x: f"{x:.4%}")
        pred_df.index = cast(Any, range(1, len(pred_df) + 1))
        pred_df.index.name = "Rank"
        st.dataframe(pred_df, use_container_width=True)

        # --- SHAP ---
        st.divider()
        st.markdown("### SHAP Feature Importance")

        if st.button("Compute SHAP Values", key="shap_btn", use_container_width=True):
            with st.spinner("Computing SHAP (this may take a moment)..."):
                shap_result = xgb.explain_prediction()

            if "error" in shap_result:
                st.warning(shap_result["error"])
                st.session_state["xgb_shap_done"] = False
            else:
                st.session_state["xgb_shap_done"] = True
                st.session_state["xgb_shap_result"] = shap_result

        if st.session_state.get("xgb_shap_done"):
            shap_result = st.session_state.get("xgb_shap_result", {})
            if "features" in shap_result:
                import plotly.graph_objects as go

                features = shap_result["features"]
                mean_abs = shap_result["mean_abs"]

                fig = go.Figure(
                    data=[
                        go.Bar(
                            x=features,
                            y=mean_abs,
                            marker_color="#3498db",
                            text=[f"{v:.4f}" for v in mean_abs],
                            textposition="outside",
                        )
                    ]
                )
                cast(Any, fig).update_layout(
                    title="Mean |SHAP| per Feature",
                    xaxis_title="Feature",
                    yaxis_title="Mean |SHAP Value|",
                    height=350,
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    "Higher bars = more influential features. "
                    "freq_last_X = frequency in last X draws; "
                    "cold_streak = consecutive draws without this number."
                )

                # --- Force plot for individual number ---
                st.divider()
                st.markdown("### Individual Number Force Plot")

                col_num, col_info = st.columns([1, 3])
                with col_num:
                    sel_number = st.selectbox(
                        "Select number",
                        list(range(1, 41)),
                        key="force_num_sel",
                    )
                with col_info:
                    prob = xgb.predict_probabilities().get(sel_number, 0)
                    st.metric(
                        label=f"Predicted probability for #{sel_number}",
                        value=f"{prob:.4%}",
                    )

                with st.spinner(f"Generating force plot for number {sel_number}..."):
                    try:
                        force_html = xgb.get_force_plot_html(sel_number)
                        st.components.v1.html(force_html, height=220, scrolling=True)
                        st.caption(
                            "Red = pushes prediction higher (number more likely to appear). "
                            "Blue = pushes prediction lower.  "
                            "The base value is the model's expected output."
                        )
                    except Exception as e:
                        st.warning(f"Could not generate force plot: {e}")

                # --- Download all force plots ---
                st.divider()
                st.markdown("### Download SHAP Report")
                if st.button("Generate SHAP Report (ZIP)", use_container_width=True):
                    import io
                    import os
                    import tempfile
                    import zipfile

                    with st.spinner(
                        "Generating all 40 force plots... this may take a minute."
                    ):
                        tmpdir = tempfile.mkdtemp(prefix="shap_report_")
                        html_files = []
                        for num in range(1, 41):
                            try:
                                html = xgb.get_force_plot_html(num)
                                fname = os.path.join(
                                    tmpdir, f"shap_number_{num:02d}.html"
                                )
                                with open(fname, "w", encoding="utf-8") as fh:
                                    fh.write(
                                        f"<h2>SHAP Force Plot — Number {num}</h2>\n"
                                    )
                                    fh.write(html)
                                html_files.append(fname)
                            except Exception:
                                pass

                        if html_files:
                            zip_buf = io.BytesIO()
                            with zipfile.ZipFile(
                                zip_buf, "w", zipfile.ZIP_DEFLATED
                            ) as zf:
                                for fname in html_files:
                                    zf.write(fname, os.path.basename(fname))
                            zip_buf.seek(0)

                            st.download_button(
                                label="Download SHAP Report (ZIP)",
                                data=zip_buf,
                                file_name="shap_force_plots.zip",
                                mime="application/zip",
                                use_container_width=True,
                            )
                            st.success(f"Generated {len(html_files)} force plots.")
                        else:
                            st.warning("Could not generate any force plots.")

                        # Cleanup temp dir (best effort)
                        try:
                            for f in html_files:
                                os.unlink(f)
                            os.rmdir(tmpdir)
                        except Exception:
                            pass

    else:
        st.info("Click 'Train XGBoost Model' above to get started.")


# =========================================================================
# PAGE: Performance Monitor
# =========================================================================
elif page == "Performance Monitor":
    st.markdown(
        '<h2 class="section-header">Performance Monitor</h2>', unsafe_allow_html=True
    )
    st.markdown("Cache statistics and system resource usage.")

    # ---- Cache info ----
    st.markdown("### Streamlit Cache")
    try:
        st.info(
            "Cache stats not directly queryable via public API. Use 'Clear Cache' in the sidebar to reset."
        )
    except Exception:
        st.info("Cache info not available in this Streamlit version.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Clear All Caches", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.toast("All caches cleared!")
    with col2:
        if st.button("Clear Session State", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.toast("Session state cleared!")

    # ---- Memory usage (psutil) ----
    st.divider()
    st.markdown("### System Resources")
    try:
        import psutil

        mem = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=0.5)

        c1, c2, c3 = st.columns(3)
        c1.metric("CPU Usage", f"{cpu_pct:.1f}%")
        c2.metric("Memory Used", f"{mem.used / (1024**3):.1f} GB")
        c3.metric("Memory Available", f"{mem.available / (1024**3):.1f} GB")

        st.progress(
            mem.percent / 100,
            text=f"Memory: {mem.percent:.1f}% ({mem.used/(1024**3):.1f}/{mem.total/(1024**3):.1f} GB)",
        )

        # Process info
        process = psutil.Process()
        st.caption(
            f"Process memory: {process.memory_info().rss / (1024**2):.1f} MB  |  "
            f"Threads: {process.num_threads()}  |  "
            f"Connections: {len(process.connections())}"
        )
    except ImportError:
        st.info("Install `psutil` for memory and CPU monitoring: `pip install psutil`")
    except Exception as e:
        st.warning(f"Could not read system metrics: {e}")

    # ---- Cached data sizes ----
    st.divider()
    st.markdown("### Cached Objects")
    import sys

    cached_names = {}
    for key in list(st.session_state.keys()):
        val = st.session_state[key]
        try:
            size = sys.getsizeof(val)
        except Exception:
            size = 0
        cached_names[key] = {"type": type(val).__name__, "size_kb": size / 1024}

    if cached_names:
        import pandas as pd

        df_cache = pd.DataFrame(cached_names).T
        df_cache.index.name = "Key"
        st.dataframe(df_cache, use_container_width=True)
    else:
        st.caption("No objects in session state.")


# =========================================================================
# PAGE: 📊 Predictor Leaderboard
# =========================================================================
elif page == "📊 Predictor Leaderboard":
    import accuracy_tracker

    st.markdown(
        '<h2 class="section-header">📊 Predictor Leaderboard</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Predictor performance from the `scorecards` table in `data/lotto.db`, "
        "computed by `accuracy_tracker.py` over rolling windows of "
        f"{', '.join(str(w) for w in accuracy_tracker.LEADERBOARD_WINDOWS)} draws."
    )

    # ---- Refresh scores ----
    if st.button("🔄 Refresh Scores", use_container_width=True):
        try:
            with st.spinner("Recomputing scorecards…"):
                updated = accuracy_tracker.update_all_scorecards()
            st.toast(f"Updated {len(updated)} scorecard(s).", icon=":material/check:")
        except sqlite3.Error as e:
            st.error(f"Could not update scorecards: {e}")
        st.rerun()

    # ---- Load leaderboard data ----
    def _load_leaderboard(window_size: int) -> Any:
        """Scorecard rows for one window size; None if DB/table unavailable."""
        try:
            return accuracy_tracker.get_leaderboard(window_size)
        except sqlite3.Error:
            return None

    if not os.path.exists(str(accuracy_tracker.DB_PATH)):
        st.info(
            "No prediction database yet (`data/lotto.db`). Scorecards appear once "
            "predictions have been recorded with `accuracy_tracker.store_prediction()` "
            "and scored — press **🔄 Refresh Scores** after logging predictions."
        )
    else:
        boards = {w: _load_leaderboard(w) for w in accuracy_tracker.LEADERBOARD_WINDOWS}

        if any(b is None for b in boards.values()):
            st.info(
                "The `scorecards` table doesn't exist yet. Record some predictions, "
                "then press **🔄 Refresh Scores** to build the leaderboard."
            )
        elif all(len(b) == 0 for b in boards.values()):
            st.info(
                "No scorecards yet. Record some predictions with "
                "`accuracy_tracker.store_prediction()`, then press **🔄 Refresh Scores**."
            )
        else:
            # ---- Hot Predictor badge (window_size=20) ----
            hot = None
            with contextlib.suppress(sqlite3.Error):
                hot = accuracy_tracker.get_hot_predictor(20)
            if hot:
                st.markdown("### 🔥 Hot Predictor")
                st.badge(
                    f"{hot} — best over the last 20 draws",
                    icon="🔥",
                    color="orange",
                )

            display_cols = {
                "predictor_name": "Predictor",
                "draws_evaluated": "Draws",
                "hit_rate": "Hit Rate",
                "top15_accuracy": "Top-15 Acc",
                "top10_accuracy": "Top-10 Acc",
                "top20_accuracy": "Top-20 Acc",
                "brier_score": "Brier",
                "mean_reciprocal_rank": "MRR",
                "last_updated": "Updated",
            }

            # ---- One sorted table per window size ----
            for win in accuracy_tracker.LEADERBOARD_WINDOWS:
                lb_rows = boards[win]
                st.divider()
                if not lb_rows:
                    st.markdown(f"### Window: last {win} draws")
                    st.caption(f"No scorecards for window size {win} yet.")
                    continue

                df = (
                    pd.DataFrame(lb_rows)
                    .sort_values(
                        by=["hit_rate", "top15_accuracy", "brier_score"],
                        ascending=[False, False, True],
                        na_position="last",
                    )
                    .reset_index(drop=True)
                )

                top = df.iloc[0]
                st.markdown(
                    f"### Window: last {win} draws — "
                    f"🏆 <span style='color:#D4AF37'>{top['predictor_name']}</span> "
                    f"<small>(hit rate {top['hit_rate']:.1%})</small>",
                    unsafe_allow_html=True,
                )

                show = df[[c for c in display_cols if c in df.columns]].rename(
                    columns=display_cols
                )
                show["Updated"] = (
                    show["Updated"].astype(str).str[:19].str.replace("T", " ")
                )
                st.dataframe(
                    show,
                    width="stretch",
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Hit Rate": st.column_config.NumberColumn(format="%.1%"),
                        "Top-15 Acc": st.column_config.NumberColumn(format="%.1%"),
                        "Top-10 Acc": st.column_config.NumberColumn(format="%.1%"),
                        "Top-20 Acc": st.column_config.NumberColumn(format="%.1%"),
                        "Brier": st.column_config.NumberColumn(format="%.4f"),
                        "MRR": st.column_config.NumberColumn(format="%.3f"),
                    },
                )


# =========================================================================
# PAGE: 🎱 Bonus Impact
# =========================================================================
elif page == "🎱 Bonus Impact":
    import datetime as dt

    import bonus_impact
    from database import fetch_all_draws

    st.markdown(
        '<h2 class="section-header">🎱 Bonus Impact</h2>', unsafe_allow_html=True
    )
    st.markdown(
        "Quantify how much the **bonus ball** adds to your wheels: division "
        "upgrades, premium value, and the maximum possible upside."
    )

    # ---- Historical draws via database.py ----
    try:
        all_draws = fetch_all_draws()
    except Exception as e:
        st.warning(f"Could not load draws from the database: {e}")
        all_draws = []

    if not all_draws:
        st.info(
            "No draws in the database yet. Import draw history first (Data Import page)."
        )
    else:
        dates = sorted(d["draw_date"] for d in all_draws)
        min_d = dt.date.fromisoformat(dates[0])
        max_d = dt.date.fromisoformat(dates[-1])

        # ---- Controls ----
        ctl1, ctl2 = st.columns(2)
        start_d = ctl1.date_input(
            "Start date", value=min_d, min_value=min_d, max_value=max_d, key="bi_start"
        )
        end_d = ctl2.date_input(
            "End date", value=max_d, min_value=min_d, max_value=max_d, key="bi_end"
        )

        selected_wheels = st.multiselect(
            "Wheels played during this range",
            wheel_names,
            default=wheel_names,
            key="bi_wheels",
        )

        what_if = st.toggle(
            "What-If Bonus Matched",
            value=False,
            key="bi_what_if",
            help="Re-runs the report with force_bonus_match=True for every "
            "ticket to show the maximum possible bonus upside.",
        )

        if start_d > end_d:
            st.error("Start date must be on or before end date.")
        elif not selected_wheels:
            st.info("Select at least one wheel to backtest.")
        else:
            ranged = [
                d
                for d in all_draws
                if start_d.isoformat() <= d["draw_date"] <= end_d.isoformat()
            ]
            if not ranged:
                st.info("No draws found in the selected date range.")
            else:
                # Unique tickets across all selected wheels
                unique_tickets = [
                    list(t)
                    for t in sorted(
                        {
                            tuple(sorted(ticket))
                            for name in selected_wheels
                            for ticket in WHEELS[name][0]
                        }
                    )
                ]

                # Prize lookup per division (latest payouts, else static fallback)
                @st.cache_data(ttl=3600, show_spinner=False)
                def _division_prizes() -> Any:
                    from prize_calculator import fetch_payouts

                    try:
                        payouts = fetch_payouts()
                        if payouts:
                            return (
                                {int(k): float(v) for k, v in payouts["lotto"].items()},
                                "MyLotto API (latest)",
                            )
                    except Exception:
                        pass
                    try:
                        from settings import settings as _s

                        return (
                            {int(k): float(v) for k, v in _s.fallback_lotto.items()},
                            "static fallback estimates",
                        )
                    except Exception:
                        return (
                            {
                                1: 1_000_000.0,
                                2: 30_000.0,
                                3: 1_000.0,
                                4: 100.0,
                                5: 60.0,
                                6: 40.0,
                                7: 20.0,
                            },
                            "static fallback estimates",
                        )

                prize_lookup, prize_src = _division_prizes()

                tickets_per_draw = [unique_tickets] * len(ranged)
                draws_main = [d["numbers"] for d in ranged]
                draws_bonus = [d["bonus"] for d in ranged]

                baseline = bonus_impact.run_bonus_impact_backtest(
                    tickets_per_draw,
                    draws_main,
                    draws_bonus,
                    prize_lookup,
                )
                bi_report = baseline
                if what_if:
                    bi_report = bonus_impact.run_bonus_impact_backtest(
                        tickets_per_draw,
                        draws_main,
                        draws_bonus,
                        prize_lookup,
                        force_bonus_match=True,
                    )

                # ---- Key metrics ----
                if what_if:
                    st.caption(
                        "🔮 **What-If mode** — every ticket scored as if the bonus "
                        "matched. Actual baseline premium: "
                        f"${baseline.bonus_premium_value:,.2f} "
                        f"({baseline.bonus_premium_pct:.1f}%)."
                    )
                delta_val = (
                    (bi_report.bonus_premium_value - baseline.bonus_premium_value)
                    if what_if
                    else None
                )
                delta_pct = (
                    (bi_report.bonus_premium_pct - baseline.bonus_premium_pct)
                    if what_if
                    else None
                )

                m1, m2, m3 = st.columns(3)
                m1.metric(
                    "Total Prize (with bonus)",
                    f"${bi_report.total_prize_with_bonus:,.2f}",
                )
                m2.metric(
                    "Bonus Premium Value",
                    f"${bi_report.bonus_premium_value:,.2f}",
                    delta=f"${delta_val:+,.2f}" if delta_val is not None else None,
                )
                m3.metric(
                    "Bonus Premium %",
                    f"{bi_report.bonus_premium_pct:.1f}%",
                    delta=f"{delta_pct:+.1f} pts" if delta_pct is not None else None,
                )
                st.caption(
                    f"{bi_report.total_draws} draws × {len(unique_tickets)} unique tickets "
                    f"({bi_report.total_tickets_played:,} ticket-evaluations) · "
                    f"prizes: {prize_src}"
                )

                # ---- Full markdown report ----
                st.divider()
                st.markdown(bonus_impact.report_to_markdown(bi_report))

                # ---- Per-draw bonus premium chart ----
                st.divider()
                st.markdown("### Bonus Premium per Draw")
                chart_df = pd.DataFrame(
                    {
                        "date": [d["draw_date"] for d in ranged],
                        "bonus_premium": [
                            p["bonus_premium"] for p in bi_report.per_draw_impact
                        ],
                    }
                ).set_index("date")
                if chart_df["bonus_premium"].abs().sum() == 0:
                    st.info("No bonus premium recorded in any draw of this range.")
                else:
                    st.bar_chart(chart_df)


# =========================================================================
# PAGE: 🧲 Attraction Profile
# =========================================================================
elif page == "🧲 Attraction Profile":
    import numerical_attraction as numerical_attraction_mod

    st.markdown(
        '<h2 class="section-header">🧲 Attraction Profile</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Consecutive-pair and +2-gap patterns across the **last 30 draws**. "
        "Albert baseline: ~63% of draws contain a consecutive pair, ~42% a +2 gap."
    )

    if not draws:
        st.warning("No draws in database.")
    else:
        # Cached profile — re-analyzed at most once per hour per draw set
        @st.cache_data(ttl=3600, show_spinner=False)
        def _attraction_profile(recent_draws: Any) -> Any:
            return numerical_attraction_mod.analyze_attraction(
                [list(d) for d in recent_draws], lookback=30
            )

        recent_key = tuple(tuple(sorted(nums)) for nums, _pb, _b, _date in draws[-30:])
        profile = _attraction_profile(recent_key)
        s = profile.summary

        # ---- Summary metrics (with Albert baseline comparison) ----
        m1, m2, m3 = st.columns(3)
        m1.metric(
            "Consecutive Pair Rate",
            f"{s['consecutive_rate']:.1%}",
            delta=f"{s['consecutive_rate'] - s['albert_consecutive_baseline']:+.1%} vs Albert",
        )
        m2.metric(
            "+2 Gap Rate",
            f"{s['plus_two_rate']:.1%}",
            delta=f"{s['plus_two_rate'] - s['albert_plus_two_baseline']:+.1%} vs Albert",
        )
        m3.metric("Draws Analyzed", profile.total_draws_analyzed)
        st.caption(
            f"Unique pairs detected: {s['total_pairs_detected']} "
            f"({s['unique_consecutive_pairs']} consecutive, "
            f"{s['unique_plus_two_pairs']} +2 gap)"
        )

        # ---- Top-10 pair tables side by side ----
        t1, t2 = st.columns(2)
        with t1:
            st.markdown("### Top 10 Consecutive Pairs")
            rows_c = sorted(
                profile.consecutive_pairs.items(), key=lambda x: (-x[1], x[0])
            )[:10]
            if rows_c:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Pair": f"{a}–{b}",
                                "Hits": c,
                                "Score": round(
                                    profile.normalized_scores.get((a, b), 0.0), 3
                                ),
                            }
                            for (a, b), c in rows_c
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.info("No consecutive pairs in the last 30 draws.")
        with t2:
            st.markdown("### Top 10 +2 Gap Pairs")
            rows_p = sorted(
                profile.plus_two_pairs.items(), key=lambda x: (-x[1], x[0])
            )[:10]
            if rows_p:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Pair": f"{a}–{b}",
                                "Hits": c,
                                "Score": round(
                                    profile.normalized_scores.get((a, b), 0.0), 3
                                ),
                            }
                            for (a, b), c in rows_p
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.info("No +2 gap pairs in the last 30 draws.")

        # ---- Hot / Cold number badges ----
        def _badges(numbers: Any, color: str) -> str:
            return " ".join(
                f"<span style='background:{color};color:white;border-radius:12px;"
                f"padding:0.2rem 0.6rem;margin:0.15rem;display:inline-block;'>"
                f"{n}</span>"
                for n in numbers
            )

        st.divider()
        h1, h2 = st.columns(2)
        with h1:
            st.markdown("### 🔥 Hot Numbers")
            if profile.hot_numbers:
                st.markdown(
                    _badges(profile.hot_numbers[:10], "#e74c3c"), unsafe_allow_html=True
                )
                st.caption("Numbers appearing most often in hot pairs")
            else:
                st.info("No hot numbers detected.")
        with h2:
            st.markdown("### ❄️ Cold Numbers")
            if profile.cold_numbers:
                st.markdown(
                    _badges(profile.cold_numbers[:12], "#3498db"),
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"{len(profile.cold_numbers)} numbers absent from all detected pairs"
                )
            else:
                st.info("No cold numbers — every number appeared in a pair.")

        # ---- Score My Wheel ----
        st.divider()
        st.markdown("### Score My Wheel")
        wheel_input = st.text_input(
            "Your 6 numbers (comma-separated)",
            "3, 4, 12, 14, 25, 33",
            key="na_wheel_input",
        )
        if st.button("Score Wheel", key="na_score_btn"):
            try:
                nums = [int(x.strip()) for x in wheel_input.split(",") if x.strip()]
                err = None
                if len(nums) != 6:
                    err = "Enter exactly 6 numbers."
                elif len(set(nums)) != 6:
                    err = "Duplicate numbers detected."
                elif any(n < 1 or n > 40 for n in nums):
                    err = "Numbers must be between 1 and 40."
                if err:
                    st.error(err)
                else:
                    wa_score = numerical_attraction_mod.score_wheel_attraction(
                        nums, profile
                    )
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Albert Alignment", f"{wa_score.albert_alignment:.0%}")
                    c2.metric("Attraction Score", f"{wa_score.attraction_score:.2f}")
                    c3.metric("Hot-Pair Coverage", f"{wa_score.coverage_ratio:.0%}")

                    if wa_score.albert_alignment >= 0.99:
                        st.success(wa_score.recommendation)
                    elif wa_score.albert_alignment > 0:
                        st.info(wa_score.recommendation)
                    else:
                        st.warning(wa_score.recommendation)

                    st.write(
                        f"**Consecutive pairs:** "
                        f"{wa_score.consecutive_pairs_present or 'none'} · "
                        f"**+2 gap pairs:** {wa_score.plus_two_pairs_present or 'none'}"
                    )
            except ValueError:
                st.error(
                    "Could not parse numbers — use comma-separated integers, e.g. 3, 4, 12, 14, 25, 33."
                )


# =========================================================================
# PAGE: 👥 Syndicates
# =========================================================================
elif page == "👥 Syndicates":
    import syndicate

    st.markdown('<h2 class="section-header">👥 Syndicates</h2>', unsafe_allow_html=True)
    st.markdown(
        "Manage lottery pools: create a syndicate, manage members and their "
        "contribution shares, register tickets, and split prizes."
    )

    # ---- Users from auth.py (for friendly pickers) ----
    def _auth_users() -> list[Any]:
        """Return [(user_id, username)] from the auth users table, or []."""
        try:
            import auth

            conn = sqlite3.connect(auth.DB_PATH)
            rows = conn.execute(
                "SELECT id, username FROM users ORDER BY username"
            ).fetchall()
            conn.close()
            return rows
        except Exception:
            return []

    auth_users = _auth_users()

    def _user_picker(label: str, key: str) -> Any:
        """Selectbox over auth users, or manual id entry if unavailable."""
        if auth_users:
            options = {f"{uname} (#{uid})": uid for uid, uname in auth_users}
            choice = st.selectbox(label, list(options.keys()), key=key)
            return options[choice]
        return st.number_input(
            f"{label} (user id)", min_value=1, step=1, value=1, key=key
        )

    try:
        syndicates = syndicate.list_syndicates()
    except Exception as e:
        st.warning(f"Could not load syndicates: {e}")
        syndicates = []

    # ---- Create syndicate ----
    with st.expander("➕ Create Syndicate", expanded=not syndicates):
        with st.form("create_syndicate_form"):
            syn_name = st.text_input(
                "Syndicate name", placeholder="e.g. Friday Work Pool"
            )
            creator_id = _user_picker("Creator", "syn_creator")
            submitted = st.form_submit_button(
                "Create Syndicate", use_container_width=True
            )
        if submitted:
            try:
                new_id = syndicate.create_syndicate(syn_name, int(creator_id))
                st.toast(f"Syndicate created (id {new_id}).", icon=":material/check:")
                st.rerun()
            except Exception as e:
                st.error(f"Could not create syndicate: {e}")

    if not syndicates:
        st.info("No syndicates yet — create one above.")
    else:
        syn_options = {f"{s['name']} (#{s['id']})": s for s in syndicates}
        selected_label = st.selectbox("Select syndicate", list(syn_options.keys()))
        syn = syn_options[selected_label]
        sid = syn["id"]

        stat_cols = st.columns(4)
        stat_cols[0].metric("Members", syn["member_count"])
        stat_cols[1].metric("Total Contribution", f"{syn['total_contribution']:.1f}%")
        stat_cols[2].metric("Creator", f"user #{syn['created_by']}")
        stat_cols[3].metric("Created", str(syn["created_at"])[:10])

        # ---- Member management ----
        st.divider()
        st.markdown("### Members")
        members = syndicate.get_members(sid)
        if members:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "User ID": m["user_id"],
                            "Contribution %": m["contribution_pct"],
                            "Email": m["email"] or "—",
                        }
                        for m in members
                    ]
                ),
                width="stretch",
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No members yet.")

        m_col1, m_col2 = st.columns(2)
        with m_col1, st.form("add_member_form"):
            st.markdown("**Add / update member**")
            member_uid = _user_picker("Member", "syn_member_add")
            member_pct = st.number_input(
                "Contribution %",
                min_value=0.01,
                max_value=100.0,
                value=50.0,
                step=0.01,
            )
            member_email = st.text_input("Email (for winner notifications)")
            if st.form_submit_button("Add Member", use_container_width=True):
                try:
                    syndicate.add_member(
                        sid,
                        int(member_uid),
                        float(member_pct),
                        email=member_email.strip() or None,
                    )
                    st.toast("Member saved.", icon=":material/check:")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not add member: {e}")
        with m_col2:
            if members:
                st.markdown("**Remove member**")
                rm_options = {f"user #{m['user_id']}": m["user_id"] for m in members}
                rm_choice = st.selectbox("Member to remove", list(rm_options.keys()))
                if st.button("Remove Member", use_container_width=True):
                    syndicate.remove_member(sid, rm_options[rm_choice])
                    st.toast("Member removed.", icon=":material/check:")
                    st.rerun()

        # ---- Ticket entry ----
        st.divider()
        st.markdown("### Register Ticket")
        default_draw = draws[-1][3] if draws else ""
        with st.form("add_ticket_form"):
            t_col1, t_col2 = st.columns(2)
            draw_id_input = t_col1.text_input(
                "Draw ID / date", value=default_draw, placeholder="YYYY-MM-DD"
            )
            ticket_input = t_col2.text_input(
                "Ticket numbers (6, comma-separated)",
                placeholder="3, 7, 12, 18, 25, 33",
            )
            splits_input = st.text_area(
                "Contributor splits (JSON, optional — defaults to member shares)",
                placeholder='{"1": 60, "2": 40}',
                height=68,
            )
            if st.form_submit_button("Add Ticket", use_container_width=True):
                try:
                    nums = [
                        int(x.strip()) for x in ticket_input.split(",") if x.strip()
                    ]
                    splits = None
                    if splits_input.strip():
                        import json as _json

                        splits = {
                            int(k): float(v)
                            for k, v in _json.loads(splits_input).items()
                        }
                    ticket_id = syndicate.add_ticket(sid, nums, draw_id_input, splits)
                    st.toast(
                        f"Ticket registered (id {ticket_id}).", icon=":material/check:"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not add ticket: {e}")

        syn_tickets = syndicate.get_tickets(sid)
        if syn_tickets:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Ticket ID": t["id"],
                            "Draw": t["draw_id"],
                            "Numbers": ", ".join(
                                f"{n:02d}" for n in t["ticket_numbers"]
                            ),
                            "Splits": t["contributor_splits"],
                        }
                        for t in syn_tickets
                    ]
                ),
                width="stretch",
                hide_index=True,
                use_container_width=True,
            )

        # ---- Prize split ----
        st.divider()
        st.markdown("### Prize Split")
        if not members:
            st.info("Add members before calculating a prize split.")
        else:
            p_col1, p_col2 = st.columns(2)
            total_prize = p_col1.number_input(
                "Total prize ($)",
                min_value=0.0,
                value=1000.0,
                step=50.0,
                key="syn_prize",
            )
            draw_label = p_col2.text_input(
                "Draw label (for notifications)",
                value=default_draw,
                key="syn_draw_label",
            )

            if st.button("Calculate Prize Split", use_container_width=True):
                try:
                    splits = syndicate.calculate_prize_split(sid, float(total_prize))
                    email_map = {m["user_id"]: m["email"] for m in members}
                    split_df = pd.DataFrame(
                        [
                            {
                                "User ID": uid,
                                "Email": email_map.get(uid) or "—",
                                "Share": f"${amt:,.2f}",
                            }
                            for uid, amt in sorted(splits.items())
                        ]
                    )
                    st.dataframe(
                        split_df,
                        width="stretch",
                        hide_index=True,
                        use_container_width=True,
                    )
                    st.caption(
                        "Shares are proportional to contribution %, rounded to 2 "
                        "decimals; any rounding remainder goes to the creator."
                    )
                    st.session_state["syn_last_split"] = {
                        "sid": sid,
                        "prize": float(total_prize),
                        "draw": draw_label,
                    }
                except ValueError as e:
                    st.error(str(e))

            last = st.session_state.get("syn_last_split")
            if (
                last
                and last["sid"] == sid
                and st.button("📧 Notify Winners", use_container_width=True)
            ):
                result = syndicate.auto_notify_winners(
                    sid, {"total_prize": last["prize"], "draw_id": last["draw"]}
                )
                ok = sum(1 for v in result["notified"].values() if v)
                st.success(
                    f"Notifications sent to {ok}/{len(result['notified'])} "
                    "member(s) — see alert.log for details."
                )


# =========================================================================
# PAGE: 🎫 Standard Lotto
# =========================================================================
elif page == "🎫 Standard Lotto":
    import bonus_impact

    st.markdown(
        '<h2 class="section-header">🎫 Standard Lotto</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Wheel performance against the **Standard Lotto** structure — no "
        "Powerball required and all bonus-ball-dependent divisions filtered out."
    )

    # Mode banner (toggle lives in the sidebar, persists via session_state)
    if st.session_state.get("game_mode") == "standard":
        st.success("🎫 **Standard Lotto Mode** is active (set in the sidebar).")
    else:
        st.info(
            "🎱 **Powerball Mode** is active globally. This tab always shows the "
            "Standard-Lotto-only view — switch modes via the sidebar toggle."
        )

    # ---- Standard Lotto divisions & editable prize estimates ----
    try:
        from prize_calculator import DEFAULT_LOTTO_POOL, LOTTO_POOL_PERCENTAGES

        # Standard mode maps 6/5/4/3 mains onto pool-model divisions 1/3/5/7
        _defaults = {
            1: round(DEFAULT_LOTTO_POOL * LOTTO_POOL_PERCENTAGES.get(1, 0) / 100, 2),
            2: round(DEFAULT_LOTTO_POOL * LOTTO_POOL_PERCENTAGES.get(3, 0) / 100, 2),
            3: round(DEFAULT_LOTTO_POOL * LOTTO_POOL_PERCENTAGES.get(5, 0) / 100, 2),
            4: round(DEFAULT_LOTTO_POOL * LOTTO_POOL_PERCENTAGES.get(7, 0) / 100, 2),
        }
    except Exception:
        _defaults = {1: 74_390.0, 2: 22_575.0, 3: 46_225.0, 4: 0.0}

    try:
        from settings import settings as _st_sl

        _ticket_cost_sl = _st_sl.ticket_cost
    except Exception:
        _ticket_cost_sl = 1.50

    with st.expander("Standard Lotto divisions & prize estimates", expanded=True):
        st.caption(
            "Estimates derive from the pool-percentage model in prize_calculator.py — "
            "edit them to match the current draw's actual payouts."
        )
        p_cols = st.columns(4)
        div_labels = {
            1: "Div 1 — 6 main",
            2: "Div 2 — 5 main",
            3: "Div 3 — 4 main",
            4: "Div 4 — 3 main",
        }
        prize_amounts = {}
        for div, col in zip((1, 2, 3, 4), p_cols, strict=False):
            prize_amounts[div] = col.number_input(
                div_labels[div],
                min_value=0.0,
                value=float(_defaults[div]),
                step=100.0,
                key=f"sl_prize_{div}",
            )

    # ---- Prize calculator ----
    st.markdown("### Prize Calculator")
    calc_cols = st.columns([1, 2])
    matches_sel = calc_cols[0].selectbox(
        "Main numbers matched", [6, 5, 4, 3], key="sl_matches"
    )
    std_div = {6: 1, 5: 2, 4: 3, 3: 4}[matches_sel]
    calc_cols[1].metric(
        f"Standard {div_labels[std_div]}",
        f"${prize_amounts[std_div]:,.2f}",
        help="Estimated prize per winning ticket (edit amounts above).",
    )

    # ---- Backtest view ----
    st.divider()
    st.markdown("### Backtest: Wheels in Standard Lotto Only")
    st.caption(
        "Every ticket is scored with `bonus_impact.standard_lotto_results()` — "
        "bonus-ball upgrades (Div 2/4/6) are excluded by design."
    )

    if not draws:
        st.warning("No draws in database.")
    else:
        b_col1, b_col2 = st.columns(2)
        sl_wheels = b_col1.multiselect(
            "Wheels", wheel_names, default=wheel_names, key="sl_wheels"
        )
        sl_n = b_col2.slider(
            "Recent draws",
            min_value=10,
            max_value=max(10, len(draws)),
            value=min(50, len(draws)),
            key="sl_n_draws",
        )

        if st.button("Run Standard Lotto Backtest", use_container_width=True):
            if not sl_wheels:
                st.error("Select at least one wheel.")
            else:
                recent = draws[-sl_n:]
                sl_rows = []
                for name in sl_wheels:
                    tickets, _pb = WHEELS[name]
                    div_counts = {1: 0, 2: 0, 3: 0, 4: 0}
                    total_prize = 0.0
                    for nums, _dpb, _db, _dd in recent:
                        for r in bonus_impact.standard_lotto_results(
                            [list(t) for t in tickets], list(nums), prize_amounts
                        ):
                            if r.division is not None:
                                div_counts[r.division] += 1
                                total_prize += r.prize
                    cost = len(tickets) * _ticket_cost_sl * len(recent)
                    total_wins = sum(div_counts.values())
                    sl_rows.append(
                        {
                            "Wheel": name,
                            "Tickets/Draw": len(tickets),
                            "Div 1": div_counts[1],
                            "Div 2": div_counts[2],
                            "Div 3": div_counts[3],
                            "Div 4": div_counts[4],
                            "Total Wins": total_wins,
                            "Total Prize": round(total_prize, 2),
                            "Cost": round(cost, 2),
                            "ROI %": round((total_prize - cost) / cost * 100, 1)
                            if cost
                            else 0.0,
                        }
                    )
                st.session_state["sl_backtest"] = {
                    "rows": sl_rows,
                    "n_draws": len(recent),
                    "from": recent[0][3],
                    "to": recent[-1][3],
                }

        bt = st.session_state.get("sl_backtest")
        if bt:
            st.caption(
                f"Backtest over {bt['n_draws']} draws ({bt['from']} → {bt['to']}) · "
                f"ticket cost ${_ticket_cost_sl:.2f}"
            )
            df_bt = pd.DataFrame(bt["rows"])
            st.dataframe(
                df_bt, width="stretch", hide_index=True, use_container_width=True
            )
            st.bar_chart(df_bt.set_index("Wheel")[["Total Prize"]])


# =========================================================================
# PAGE: Export
# =========================================================================
elif page == "🔔 System Health":
    st.markdown('<h2 class="section-header">System Health</h2>', unsafe_allow_html=True)

    from datetime import datetime

    import requests as _requests

    _API_BASE = os.environ.get("LOTTO_API_URL", "http://localhost:8000")
    _PROM_URL = os.environ.get("PROMETHEUS_URL", "")

    # ---- Fetch health + metrics from the API ----
    health_data, metrics_text = None, ""
    try:
        hr = _requests.get(f"{_API_BASE}/health", timeout=5)
        health_data = hr.json()
    except Exception as exc:
        st.error(f"API unreachable at {_API_BASE} — {exc}")
    with contextlib.suppress(Exception):
        metrics_text = _requests.get(f"{_API_BASE}/metrics", timeout=5).text

    def _metric_samples(name: str) -> Any:
        """All samples for a metric family from the /metrics text."""
        from prometheus_client.parser import text_string_to_metric_families

        for fam in text_string_to_metric_families(metrics_text):
            if fam.name == name:
                return fam.samples
        return []

    def _quantile(samples: Any, q: float) -> Any:
        """Approximate a quantile from histogram bucket samples."""
        buckets, count = [], 0.0
        for s in samples:
            if s.name.endswith("_bucket"):
                le = s.labels.get("le")
                if le not in (None, "+Inf"):
                    buckets.append((float(le), s.value))
            elif s.name.endswith("_count"):
                count = s.value
        if not buckets or count <= 0:
            return None
        buckets.sort()
        target = q * count
        for le, cum in buckets:
            if cum >= target:
                return le
        return buckets[-1][0]

    # ---- Status cards ----
    if health_data:
        overall = health_data.get("status", "unknown")
        color = {
            "healthy": "🟢",
            "degraded": "🟡",
            "unhealthy": "🔴",
        }.get(overall, "⚪")
        st.markdown(
            f"### {color} Overall: **{overall.upper()}** "
            f"(v{health_data.get('version', '?')}, {health_data.get('timestamp', '?')})"
        )

        checks = health_data.get("checks", {})
        cols = st.columns(len(checks) or 1)
        for col, (name, value) in zip(cols, checks.items(), strict=False):
            text = str(value)
            if text == "ok" or isinstance(value, int | float):
                icon = "🟢"
            elif text.startswith("warn"):
                icon = "🟡"
            else:
                icon = "🔴"
            col.metric(
                label=f"{icon} {name.replace('_', ' ').title()}",
                value=text if len(text) <= 22 else text[:22] + "…",
            )

        if st.button("🔄 Re-check now", key="health_recheck"):
            st.rerun()

    if not metrics_text:
        st.info("No metrics available — start the API (uvicorn api:app --port 8000).")
    else:
        st.divider()

        # ---- Active users + request volume ----
        active = 0
        for s in _metric_samples("active_users"):
            active = int(s.value)
        total_req, err_req = 0.0, 0.0
        for s in _metric_samples("http_requests_total"):
            total_req += s.value
            if str(s.labels.get("status", "")).startswith("5"):
                err_req += s.value
        err_pct = (err_req / total_req * 100) if total_req else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("👤 Active Users (15 min)", active)
        c2.metric("📨 Total Requests", int(total_req))
        c3.metric("⚠️ 5xx Error Rate", f"{err_pct:.2f}%")

        # ---- Error rate over time ----
        st.markdown("#### Error Rate (last 24h)")
        series = None
        if _PROM_URL:
            try:
                end = datetime.now()
                start = end - pd.Timedelta(hours=24)
                resp = _requests.get(
                    f"{_PROM_URL}/api/v1/query_range",
                    params={
                        "query": 'sum(rate(http_requests_total{status=~"5.."}[5m])) '
                        "/ sum(rate(http_requests_total[5m]))",
                        "start": start.timestamp(),
                        "end": end.timestamp(),
                        "step": 900,
                    },
                    timeout=5,
                )
                results = resp.json()["data"]["result"]
                if results:
                    ts_vals = results[0]["values"]
                    series = pd.Series(
                        [float(v) * 100 for _t, v in ts_vals],
                        index=pd.to_datetime([t for t, _v in ts_vals], unit="s"),
                        name="5xx %",
                    )
            except Exception:
                series = None
        if series is not None and not series.empty:
            st.line_chart(series)
        else:
            # No Prometheus: accumulate samples while this page is open.
            samples = st.session_state.setdefault("health_err_rate", [])
            samples.append((datetime.now(), err_pct))
            df_err = pd.DataFrame(samples, columns=["time", "5xx %"]).set_index("time")
            st.line_chart(df_err)
            if not _PROM_URL:
                st.caption(
                    "Showing samples collected this session. Set PROMETHEUS_URL "
                    "(e.g. http://localhost:9090) for the full 24h history."
                )

        # ---- Prediction latency percentiles ----
        st.markdown("#### Prediction Latency (/predictions)")
        lat_samples = [
            s
            for s in _metric_samples("http_request_duration_seconds")
            if s.labels.get("endpoint") == "/predictions"
        ]
        p50 = _quantile(lat_samples, 0.50)
        p95 = _quantile(lat_samples, 0.95)
        p99 = _quantile(lat_samples, 0.99)
        l1, l2, l3 = st.columns(3)
        l1.metric("p50", f"{p50:.2f}s" if p50 is not None else "no data")
        l2.metric("p95", f"{p95:.2f}s" if p95 is not None else "no data")
        l3.metric("p99", f"{p99:.2f}s" if p99 is not None else "no data")

        # ---- Predictions / wheels generated ----
        pred_counts, wheel_counts = {}, {}
        for s in _metric_samples("predictions_generated_total"):
            pred_counts[s.labels.get("method", "?")] = int(s.value)
        for s in _metric_samples("wheels_generated_total"):
            wheel_counts[s.labels.get("system_type", "?")] = int(s.value)
        g1, g2 = st.columns(2)
        if pred_counts:
            g1.markdown("**Predictions generated**")
            g1.bar_chart(pd.Series(pred_counts))
        if wheel_counts:
            g2.markdown("**Wheels generated**")
            g2.bar_chart(pd.Series(wheel_counts))

    # ---- Disk / memory usage bars (local host) ----
    st.divider()
    st.markdown("#### Host Resources")
    import shutil as _shutil

    try:
        import psutil as _psutil

        mem_pct = _psutil.virtual_memory().percent / 100.0
    except Exception:
        mem_pct = None
    du = _shutil.disk_usage(os.path.dirname(__file__) or ".")
    disk_used = 1.0 - (du.free / du.total if du.total else 0.0)

    d1, d2 = st.columns(2)
    d1.markdown(f"**Disk used:** {disk_used * 100:.1f}%")
    d1.progress(min(max(disk_used, 0.0), 1.0))
    if mem_pct is not None:
        d2.markdown(f"**Memory used:** {mem_pct * 100:.1f}%")
        d2.progress(min(max(mem_pct, 0.0), 1.0))
    else:
        d2.markdown("**Memory used:** psutil unavailable")

else:
    st.markdown(
        '<h2 class="section-header">Export Tickets</h2>', unsafe_allow_html=True
    )
    st.markdown("Download a wheel's tickets as CSV.")

    export_wheel = st.selectbox(
        "Wheel", wheel_names, key="export_wheel", label_visibility="collapsed"
    )

    if st.button("Generate CSV Preview", use_container_width=True):
        tickets, pb = WHEELS[export_wheel]
        data = [
            {
                "Main Numbers": ", ".join(f"{x:02d}" for x in sorted(comb)),
                "Powerball": pb,
            }
            for comb in tickets
        ]
        df_export = pd.DataFrame(data)
        st.data_editor(
            df_export,
            width="stretch",
            hide_index=True,
            disabled=True,
            use_container_width=True,
        )

        csv = df_export.to_csv(index=False)
        st.download_button(
            "Download CSV",
            csv,
            f"{export_wheel}_tickets.csv",
            "text/csv",
            use_container_width=True,
        )
