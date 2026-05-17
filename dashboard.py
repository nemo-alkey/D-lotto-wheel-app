#!/usr/bin/env python3
import streamlit as st
import pandas as pd
import sys
import os
import sqlite3
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))

try:
    from lotto_wheels import (
        load_draws, positive_negative_split, block_analysis,
        sum_range, numerical_attraction, bayesian_posterior,
        bandit_recommendation, WHEELS, show_wheel
    )
except ImportError as e:
    st.error(f"Could not import from lotto_wheels.py: {e}")
    st.stop()

st.set_page_config(page_title="NZ Lotto Powerball Dashboard", layout="wide")

# ---------------------------------------------------------------------------
# Custom CSS — responsive, scrollable tables, compact mobile layout
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    @media (max-width: 640px) {
        .main-header { font-size: 1.2rem !important; }
        .section-header { font-size: 1.0rem !important; }
        .st-emotion-cache-1avcm0n { font-size: 0.75rem; }
        div[data-testid="stMetricValue"] { font-size: 1.0rem !important; }
        .wheel-card { font-size: 0.85rem; padding: 0.3rem !important; }
        div[data-testid="column"] { min-width: 140px; }
        section[data-testid="stSidebar"] { min-width: 200px; }
    }
    @media (min-width: 641px) and (max-width: 1024px) {
        .wheel-card { font-size: 0.9rem; }
    }
    div[data-testid="stDataFrame"] > div { overflow-x: auto; }
    div[data-testid="stDataFrame"] table { min-width: 400px; }
    .block-container { padding-top: 1.5rem; }
    section[data-testid="stSidebar"] > div { padding-top: 1rem; }
    .stExpander details summary { font-weight: 600; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="main-header">NZ Lotto Powerball Wheel Dashboard</h1>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar — DB info + navigation + wheel selector
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Database Info")
    draws = load_draws()
    if draws:
        col_a, col_b = st.columns(2)
        col_a.metric("Total Draws", len(draws))
        col_b.metric("Draw Range", f"{draws[0][2][:4]}-{draws[-1][2][:4]}")
        st.caption(f"{draws[0][2]} to {draws[-1][2]}")
    else:
        st.warning("No draws loaded.")

    st.divider()

    st.markdown("### Navigation")
    page = st.radio(
        "Go to",
        ["Wheels & Tickets", "Statistical Report", "Check Draw", "Export"],
        label_visibility="collapsed",
    )

    st.divider()

    st.markdown("### Wheel Selector")
    wheel_names = list(WHEELS.keys())
    selected_wheel = st.selectbox("Wheel", wheel_names, label_visibility="collapsed")

    if st.button("Show Tickets & Cost", use_container_width=True):
        st.session_state["show_tickets"] = selected_wheel


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


# =========================================================================
# PAGE: Wheels & Tickets
# =========================================================================
if page == "Wheels & Tickets":
    st.markdown('<h2 class="section-header">Wheels &amp; Tickets</h2>', unsafe_allow_html=True)

    # --- Overview cards — responsive grid (max 3 per row on mobile) ---
    overview_data = []
    for name, (tickets, pb) in WHEELS.items():
        p = pool_of(name)
        overview_data.append({
            "Wheel": name,
            "Tickets": len(tickets),
            "Pool": len(p),
            "PB": pb,
            "Guarantee": wheel_guarantee(name),
        })

    # Display cards in rows of 3 on small screens, 5 on wide
    cols_per_row = 3
    rows = [overview_data[i:i+cols_per_row] for i in range(0, len(overview_data), cols_per_row)]
    for row in rows:
        cols = st.columns(len(row), gap="small")
        for i, info in enumerate(row):
            with cols[i]:
                st.markdown(f"""
                <div class="wheel-card" style="border:1px solid #ccc;border-radius:8px;padding:0.5rem;text-align:center;">
                    <div style="font-weight:600">{info['Wheel']}</div>
                    <div>Tickets: {info['Tickets']}</div>
                    <div>Pool: {info['Pool']} numbers</div>
                    <div>PB: {info['PB']}</div>
                    <div style="font-size:0.8rem;margin-top:4px">{info['Guarantee']}</div>
                </div>
                """, unsafe_allow_html=True)

    st.divider()

    # --- Detailed wheel view ---
    if "show_tickets" in st.session_state:
        wheel = st.session_state["show_tickets"]
        tickets, pb = WHEELS[wheel]
        cost = len(tickets) * 1.5

        st.markdown(f'<h3 class="section-header">{wheel.upper()}</h3>', unsafe_allow_html=True)

        info_cols = st.columns([2, 2, 2], gap="medium")
        info_cols[0].metric("Tickets", len(tickets))
        info_cols[1].metric("Powerball", pb)
        info_cols[2].metric("Cost", f"${cost:.2f}")

        st.write(f"**Guarantee:** {wheel_guarantee(wheel)}")

        tickets_data = [
            {"Ticket": i + 1, "Main Numbers": ", ".join(f"{x:02d}" for x in sorted(comb))}
            for i, comb in enumerate(tickets)
        ]
        st.dataframe(pd.DataFrame(tickets_data), use_container_width=True, hide_index=True)

        with st.expander("Pool numbers used by this wheel"):
            st.write(", ".join(str(n) for n in pool_of(wheel)))
    else:
        st.info("Select a wheel in the sidebar and click **Show Tickets & Cost**.")


# =========================================================================
# PAGE: Statistical Report — each section in its own expander
# =========================================================================
elif page == "Statistical Report":
    st.markdown('<h2 class="section-header">Statistical Report</h2>', unsafe_allow_html=True)

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
            st.dataframe(pd.DataFrame(rows_b).set_index("Position"), use_container_width=True)

        # --- Sum Range ---
        with st.expander("Sum Range (trimmed extremes)"):
            st.metric("Typical sum range", f"{low} – {high}")

        # --- Numerical Attraction ---
        with st.expander("Numerical Attraction"):
            st.markdown(f"**{adj*100:.1f}%** of draws contain adjacent numbers (gap ≤ 2)")

        # --- Bayesian Posterior ---
        with st.expander("Bayesian Top 10"):
            bayes_df = pd.DataFrame(
                [{"Number": n, "Probability": f"{p:.4%}"} for n, p in top_bayes]
            )
            st.dataframe(bayes_df, use_container_width=True, hide_index=True)

            # Bar visualisation
            max_prob = top_bayes[0][1] if top_bayes else 1
            bars = "\n".join(
                f"#{n:02d} {'█' * round(p/max_prob*20)}{p:.2%}"
                for n, p in top_bayes
            )
            st.code(bars, language="text")

        # --- Thompson Sampling ---
        with st.expander("Thompson Sampling Top 6"):
            st.markdown(f"Recommended numbers: **{bandit}**")
            st.caption("Multi-armed bandit with Beta(α, β) per number")


# =========================================================================
# PAGE: Check Draw
# =========================================================================
elif page == "Check Draw":
    st.markdown('<h2 class="section-header">Check Draw</h2>', unsafe_allow_html=True)
    st.markdown("See how many winning tickets a wheel produces for a given draw.")

    col1, col2 = st.columns([3, 1], gap="medium")
    with col1:
        draw_input = st.text_input("Draw numbers (comma-separated)", "11,12,17,22,28,32")
    with col2:
        pb_input = st.number_input("Powerball", min_value=1, max_value=10, value=3)

    wheel_to_check = st.selectbox("Wheel", wheel_names, key="check_wheel", label_visibility="collapsed")

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
                        match_data.append({
                            "Ticket": i,
                            "Main Numbers": ", ".join(f"{x:02d}" for x in sorted(comb)),
                            "Matches": match_count,
                        })

                st.markdown(
                    f"**Pool overlap:** {len(draw_set & set(pool))} / 6 "
                    f"| **Wheel PB:** {wheel_pb} "
                    f"| **Draw PB:** {pb_input}"
                )

                if match_data:
                    st.success(f"**{len(match_data)}** ticket(s) with 3+ matches")
                    st.dataframe(pd.DataFrame(match_data), use_container_width=True, hide_index=True)
                else:
                    st.info("No winning tickets (need 3+ main matches from the wheel).")
        except Exception as e:
            st.error(f"Error: {e}")


# =========================================================================
# PAGE: Export
# =========================================================================
else:
    st.markdown('<h2 class="section-header">Export Tickets</h2>', unsafe_allow_html=True)
    st.markdown("Download a wheel's tickets as CSV.")

    export_wheel = st.selectbox("Wheel", wheel_names, key="export_wheel", label_visibility="collapsed")

    if st.button("Generate CSV Preview", use_container_width=True):
        tickets, pb = WHEELS[export_wheel]
        data = [
            {"Main Numbers": ", ".join(f"{x:02d}" for x in sorted(comb)), "Powerball": pb}
            for comb in tickets
        ]
        df_export = pd.DataFrame(data)
        st.dataframe(df_export, use_container_width=True, hide_index=True)

        csv = df_export.to_csv(index=False)
        st.download_button(
            "Download CSV",
            csv,
            f"{export_wheel}_tickets.csv",
            "text/csv",
            use_container_width=True,
        )
