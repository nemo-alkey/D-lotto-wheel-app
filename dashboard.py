#!/usr/bin/env python3
import streamlit as st
import pandas as pd
import sys
import os
import sqlite3
from collections import Counter

# Import functions from your existing script
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

# ---- Custom CSS for mobile-friendly sizing ----
st.markdown(
    """
<style>
    /* Responsive font sizing */
    @media (max-width: 640px) {
        .main-header { font-size: 1.25rem !important; }
        .section-header { font-size: 1.05rem !important; }
        .stDataFrame { font-size: 0.8rem; }
        .st-emotion-cache-1avcm0n { font-size: 0.8rem; }
        div[data-testid="stMetricValue"] { font-size: 1.1rem !important; }
    }
    /* Ensure the tickets dataframe scrolls horizontally */
    div[data-testid="stDataFrame"] > div {
        overflow-x: auto;
    }
    div[data-testid="stDataFrame"] table {
        min-width: 480px;
    }
    /* Sidebar nav links styling */
    .nav-link {
        padding: 0.35rem 0;
        font-size: 0.95rem;
    }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<h1 class="main-header">NZ Lotto Powerball Wheel Dashboard</h1>', unsafe_allow_html=True)
st.markdown("Based on Bluskov & Albert methods")

# ---- Sidebar ----
with st.sidebar:
    st.markdown("### Database Info")
    draws = load_draws()
    if draws:
        col_a, col_b = st.columns(2)
        col_a.metric("Total Draws", len(draws))
        col_b.metric("Powerball", f"1-10")
        st.caption(f"{draws[0][2]} to {draws[-1][2]}")
    else:
        st.warning("No draws loaded. Run a script to populate lotto_working.db")

    st.divider()

    st.markdown("### Quick Links")
    page = st.radio(
        "Navigate",
        ["Wheels & Tickets", "Statistical Report", "Check Draw", "Export"],
        label_visibility="collapsed",
    )

    st.divider()

    st.markdown("### Wheel Selector")
    wheel_names = list(WHEELS.keys())
    selected_wheel = st.selectbox("Wheel", wheel_names, label_visibility="collapsed")

    if st.button("Show Tickets & Cost", use_container_width=True):
        st.session_state["show_tickets"] = selected_wheel

# ---- Helper ----
def wheel_guarantee(wheel):
    guarantees = {
        "single1": "4-win if 4 of your 10 numbers are drawn",
        "single2": "4-win if 4 of your 10 numbers are drawn",
        "double": "Two 4-wins if 4 of your 10 numbers are drawn",
        "five-if-six": "5-win if all 6 numbers are within your 11 numbers",
        "jackpot7": "Jackpot (6-win) if all 6 numbers are within your 7 numbers",
    }
    return guarantees.get(wheel, "See documentation")


# =====================================================================
# PAGE: Wheels & Tickets
# =====================================================================
if page == "Wheels & Tickets":
    st.markdown('<h2 class="section-header">Wheels &amp; Tickets</h2>', unsafe_allow_html=True)

    # Overview cards using responsive columns
    overview_data = []
    for name, (tickets, pb) in WHEELS.items():
        pool = set()
        for t in tickets:
            pool.update(t)
        overview_data.append(
            {"Wheel": name, "Tickets": len(tickets), "Pool": len(pool), "PB": pb}
        )
    df_overview = pd.DataFrame(overview_data)

    # Responsive columns — stack on narrow screens
    cards = st.columns([1, 1, 1, 1, 1], gap="small")
    for i, row in df_overview.iterrows():
        with cards[i]:
            st.markdown(
                f"<div style='border:1px solid #ccc; border-radius:8px; padding:0.5rem; text-align:center;'>"
                f"<div style='font-weight:600; font-size:0.95rem;'>{row['Wheel']}</div>"
                f"<div>🎫 {row['Tickets']} tickets</div>"
                f"<div>🎯 pool of {row['Pool']}</div>"
                f"<div>⚡ PB {row['PB']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # Detailed view when a wheel is selected
    if "show_tickets" in st.session_state:
        wheel = st.session_state["show_tickets"]
        tickets, pb = WHEELS[wheel]
        cost = len(tickets) * 1.5

        st.markdown(f'<h3 class="section-header">{wheel.upper()}</h3>', unsafe_allow_html=True)

        info_cols = st.columns([2, 2, 1], gap="medium")
        info_cols[0].info(f"**{len(tickets)}** tickets")
        info_cols[1].info(f"**PB {pb}**")
        info_cols[2].info(f"**${cost:.2f}**")

        st.write(f"**Guarantee:** {wheel_guarantee(wheel)}")

        # Scrollable tickets table
        data = []
        for i, comb in enumerate(tickets, 1):
            data.append(
                {"Ticket": i, "Main Numbers": ", ".join(f"{x:02d}" for x in sorted(comb))}
            )
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        with st.expander("Pool numbers used by this wheel"):
            pool = set()
            for t in tickets:
                pool.update(t)
            st.write(", ".join(str(n) for n in sorted(pool)))
    else:
        st.info("Select a wheel in the sidebar and click **Show Tickets & Cost**.")


# =====================================================================
# PAGE: Statistical Report
# =====================================================================
elif page == "Statistical Report":
    st.markdown('<h2 class="section-header">Statistical Report</h2>', unsafe_allow_html=True)

    if not draws:
        st.warning("No draws in database.")
    else:
        with st.expander("Albert's Lotto Code Analysis (last 30 draws)", expanded=True):
            pos, neg, _ = positive_negative_split(draws)
            ranges = block_analysis(draws)
            low, high = sum_range(draws)
            adj = numerical_attraction(draws)
            bayes = bayesian_posterior(draws)
            top_bayes = sorted(bayes.items(), key=lambda x: x[1], reverse=True)[:10]
            bandit = bandit_recommendation(draws)

            # Two-column layout for stats
            left, right = st.columns([1, 1], gap="medium")

            with left:
                st.markdown("**Positive / Negative Split**")
                st.markdown(f"✅ **Positive:** {sorted(pos)}")
                st.markdown(f"❌ **Negative:** {sorted(neg)}")

                st.markdown("**Sum Range**")
                st.markdown(f"📊 {low} -- {high} (trimmed)")

                st.markdown("**Numerical Attraction**")
                st.markdown(f"🔗 {adj*100:.1f}% of draws have adjacent numbers")

            with right:
                st.markdown("**Block Analysis (positional ranges)**")
                for i, cats in ranges.items():
                    st.markdown(f"Pos {i+1}: {cats}")

            st.divider()

            bayes_cols = st.columns([1, 1], gap="medium")
            with bayes_cols[0]:
                st.markdown("**Bayesian Top 10**")
                st.markdown(", ".join(str(n) for n in top_bayes))
            with bayes_cols[1]:
                st.markdown("**Thompson Sampling Top 6**")
                st.markdown(", ".join(str(n) for n in bandit))


# =====================================================================
# PAGE: Check Draw
# =====================================================================
elif page == "Check Draw":
    st.markdown('<h2 class="section-header">Check Draw</h2>', unsafe_allow_html=True)
    st.markdown("Check how many winning tickets a wheel would produce for a given draw.")

    col1, col2 = st.columns([2, 1], gap="medium")
    with col1:
        draw_input = st.text_input(
            "Main numbers (comma-separated)", "11,12,17,22,28,32"
        )
    with col2:
        pb_input = st.number_input("Powerball", min_value=1, max_value=10, value=3)

    wheel_to_check = st.selectbox("Wheel", wheel_names, key="check_wheel", label_visibility="collapsed")

    if st.button("Check Draw", use_container_width=True):
        try:
            nums = [int(x.strip()) for x in draw_input.split(",")]
            if len(nums) != 6:
                st.error("Enter exactly 6 numbers.")
            elif len(set(nums)) != 6:
                st.error("Duplicate numbers detected.")
            elif any(n < 1 or n > 40 for n in nums):
                st.error("Numbers must be 1-40.")
            else:
                draw_set = set(nums)
                tickets, wheel_pb = WHEELS[wheel_to_check]
                pool = set()
                for t in tickets:
                    pool.update(t)

                match_data = []
                for i, comb in enumerate(tickets, 1):
                    match_count = len(draw_set.intersection(comb))
                    if match_count >= 3:
                        match_data.append(
                            {
                                "Ticket": i,
                                "Numbers": ", ".join(f"{x:02d}" for x in sorted(comb)),
                                "Matches": match_count,
                            }
                        )

                st.markdown(
                    f"**Pool overlap:** {len(draw_set & pool)} / 6 "
                    f"| **Wheel PB:** {wheel_pb} "
                    f"| **Draw PB:** {pb_input}"
                )

                if match_data:
                    st.success(f"**{len(match_data)}** ticket(s) with 3+ matches")
                    df = pd.DataFrame(match_data)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.info("No winning tickets (need 3+ main matches from the wheel).")
        except Exception as e:
            st.error(f"Error: {e}")


# =====================================================================
# PAGE: Export
# =====================================================================
else:  # Export
    st.markdown('<h2 class="section-header">Export Tickets</h2>', unsafe_allow_html=True)
    st.markdown("Download a wheel's tickets as a CSV file for bulk upload.")

    export_wheel = st.selectbox("Wheel", wheel_names, key="export_wheel", label_visibility="collapsed")

    if st.button("Generate CSV Preview", use_container_width=True):
        tickets, pb = WHEELS[export_wheel]
        data = []
        for comb in tickets:
            data.append(
                {
                    "Main Numbers": ", ".join(f"{x:02d}" for x in sorted(comb)),
                    "Powerball": pb,
                }
            )
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
