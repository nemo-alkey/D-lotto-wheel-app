#!/usr/bin/env python3
"""
ticket_wizard.py — Multi‑step Streamlit wizard for guided ticket generation.

Steps:
  1. Selection Method   — manual / Albert / Ensemble
  2. Number Picker       — tweak the final pool
  3. Wheel Selection     — Bluskov preset or custom
  4. Constraints         — block, sum, attraction, min compliance
  5. Powerball           — auto / manual / none
  6. Budget              — lines count
  7. Review & Generate   — preview + compliance score
  8. Output              — table, CSV/PDF/email export

Uses st.session_state["wizard"] to persist all data across reruns.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Step renderers — each returns True when the user clicks Next
# ---------------------------------------------------------------------------


def _step_method() -> bool:
    st.markdown("### Step 1: Selection Method")
    method = st.radio(
        "How should numbers be chosen?",
        [
            "Manual number selection",
            "Albert recommended pool",
            "Ensemble predicted numbers",
        ],
        key="wiz_method",
    )
    st.session_state["wizard"]["method"] = method
    return True  # always valid


def _step_numbers() -> bool:
    st.markdown("### Step 2: Number Picker")
    method = st.session_state["wizard"]["method"]
    numbers = st.session_state["wizard"].get("pool", [])

    if method == "Albert recommended pool":
        conn = sqlite3.connect("lotto.db")
        try:
            from albert_analysis import get_recommended_pool

            auto = get_recommended_pool(conn, window_draws=20, target_pool_size=10)
        finally:
            conn.close()
        numbers = st.multiselect(
            "Albert pool (edit if desired)",
            list(range(1, 41)),
            default=auto,
            key="wiz_pool_pick",
        )
        st.caption(f"Default: {', '.join(str(n) for n in auto)}")
    elif method == "Ensemble predicted numbers":
        conn = sqlite3.connect("lotto.db")
        try:
            from ensemble import EnsemblePredictor

            ep = EnsemblePredictor(conn)
            ep.fit_weights(validation_draws=10)
            preds = ep.predict_all(main_top=15, bonus_top=5, pb_top=3)
            top = [n for n, _ in preds["main"]]
        finally:
            conn.close()
        numbers = st.multiselect(
            "Ensemble top‑15 (edit if desired)",
            list(range(1, 41)),
            default=top,
            key="wiz_pool_pick",
        )
    else:
        numbers = st.multiselect(
            "Select your numbers",
            list(range(1, 41)),
            default=numbers,
            key="wiz_pool_pick",
        )

    st.session_state["wizard"]["pool"] = sorted(numbers)
    if len(numbers) < 6:
        st.warning("Select at least 6 numbers.")
        return False
    return True


def _step_wheel() -> bool:
    st.markdown("### Step 3: Wheel Selection")
    wheel_type = st.radio(
        "Wheel template",
        ["Bluskov preset", "Custom"],
        key="wiz_wheel_type",
    )
    if wheel_type == "Bluskov preset":
        from lotto_wheels import WHEELS

        names = list(WHEELS.keys())
        preset = st.selectbox("Preset", names, key="wiz_preset")
        st.session_state["wizard"]["wheel_preset"] = preset
        st.session_state["wizard"]["wheel_custom"] = None
    else:
        pool = st.number_input("Pool size", 6, 20, 10, key="wiz_pool_size")
        guarantee = st.selectbox(
            "Guarantee",
            ["3 if 3", "3 if 4", "4 if 4", "4 if 5", "5 if 6"],
            index=2,
            key="wiz_guarantee",
        )
        st.session_state["wizard"]["wheel_custom"] = {
            "pool_size": pool,
            "guarantee": guarantee,
        }
        st.session_state["wizard"]["wheel_preset"] = None
    return True


def _step_constraints() -> bool:
    st.markdown("### Step 4: Constraints")
    use_block = st.checkbox("Enforce block analysis", value=True, key="wiz_block")
    use_sum = st.checkbox("Enforce sum range", value=True, key="wiz_sum")
    use_attract = st.checkbox("Enforce numerical attraction", value=False, key="wiz_attract")
    min_comply = st.slider("Minimum compliance score", 0, 100, 60, 5, key="wiz_min_comply")

    st.session_state["wizard"]["constraints"] = {
        "block": use_block,
        "sum": use_sum,
        "attraction": use_attract,
        "min_compliance": min_comply,
    }
    return True


def _step_powerball() -> bool:
    st.markdown("### Step 5: Powerball")
    pb_mode = st.radio(
        "Powerball selection",
        ["Auto (frequency)", "Manual", "No Powerball (Lotto‑only)"],
        key="wiz_pb_mode",
    )
    if pb_mode == "Manual":
        pb = st.selectbox("Powerball", list(range(1, 11)), key="wiz_pb_manual")
        st.session_state["wizard"]["powerball"] = pb
    elif pb_mode == "Auto (frequency)":
        st.session_state["wizard"]["powerball"] = "auto"
    else:
        st.session_state["wizard"]["powerball"] = None
    st.session_state["wizard"]["pb_mode"] = pb_mode
    return True


def _step_budget() -> bool:
    st.markdown("### Step 6: Budget")
    max_lines = st.number_input(
        "Number of lines (tickets)",
        1,
        100,
        12,
        key="wiz_lines",
        help="If using a custom wheel, this is the max ticket count.",
    )
    st.session_state["wizard"]["max_lines"] = max_lines
    cost = max_lines * 1.50
    st.metric("Estimated cost", f"${cost:.2f}")
    return True


def _step_review() -> bool:
    st.markdown("### Step 7: Review & Generate")
    wiz = st.session_state["wizard"]
    pool = wiz.get("pool", [])

    if not pool or len(pool) < 6:
        st.error("Need at least 6 numbers. Go back to Step 2.")
        return False

    # Generate
    from wheel_generator import generate_abbreviated_wheel

    if wiz.get("wheel_preset"):
        from lotto_wheels import WHEELS

        tickets, _ = WHEELS[wiz["wheel_preset"]]
        guarantee_desc = wiz["wheel_preset"]
    else:
        custom = wiz.get("wheel_custom", {})
        tickets, desc = generate_abbreviated_wheel(
            pool,
            guarantee=custom.get("guarantee", "4 if 4"),
            max_tickets=min(wiz["max_lines"], 200),
            verbose=False,
        )
        guarantee_desc = desc

    wiz["generated_tickets"] = tickets
    wiz["guarantee_desc"] = guarantee_desc

    # Preview first 5
    st.markdown(f"**Generated:** {len(tickets)} tickets ({guarantee_desc})")
    preview = tickets[:5]
    prev_df = pd.DataFrame(
        [
            {"Ticket": i + 1, "Numbers": ", ".join(f"{n:02d}" for n in sorted(t))}
            for i, t in enumerate(preview)
        ]
    )
    st.dataframe(prev_df, hide_index=True, use_container_width=True)

    # Compliance score
    try:
        from compliance_scorer import score_wheel

        conn_c = sqlite3.connect("lotto.db")
        import os
        import sys

        from albert_analysis import classify_numbers
        from block_analysis import compute_block_ranges
        from sum_analysis import dynamic_sum_range

        sys.path.insert(0, os.path.dirname(__file__))
        from lotto_wheels import load_draws

        draws = load_draws()
        albert = classify_numbers(conn_c, 20)
        albert["block_ranges"] = compute_block_ranges(draws, 30)
        albert["sum_range"] = dynamic_sum_range(conn_c, 30)
        score = score_wheel(tickets, albert)
        conn_c.close()
        badge = "🟢" if score >= 80 else ("🟡" if score >= 60 else "🔴")
        st.metric(f"{badge} Lotto Code Score", f"{score:.0f}/100")
    except Exception:
        st.caption("Compliance score unavailable.")

    return True


def _step_output() -> bool:
    st.markdown("### Step 8: Output")
    wiz = st.session_state["wizard"]
    tickets = wiz.get("generated_tickets", [])

    if not tickets:
        st.warning("No tickets generated.")
        return False

    # PB
    pb = wiz.get("powerball")
    pb_val = 3 if pb == "auto" else pb  # 3 = default

    # Full table
    rows = []
    for i, t in enumerate(tickets, 1):
        rows.append(
            {
                "Line": i,
                "Main Numbers": ", ".join(f"{n:02d}" for n in sorted(t)),
                "Powerball": pb_val if pb_val else "—",
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.success(f"{len(tickets)} tickets | Cost: ${len(tickets) * 1.50:.2f}")

    # CSV download
    csv = df.to_csv(index=False)
    st.download_button("📥 Download CSV", csv, "lotto_tickets.csv", "text/csv")

    # Email (placeholder)
    st.text_input("Email to send tickets (requires SMTP config)", key="wiz_email")
    if st.button("📧 Send via Email", key="wiz_send_email"):
        email = st.session_state.get("wiz_email", "")
        if email:
            from notifier import send_email_alert

            body = f"Your Lotto Tickets:\n\n{csv}"
            ok = send_email_alert("Your Lotto Tickets", body)
            if ok:
                st.success(f"Sent to {email}")
            else:
                st.error("Email failed — check SMTP config.")
        else:
            st.warning("Enter an email address.")

    return True


# ---------------------------------------------------------------------------
# Master wizard runner
# ---------------------------------------------------------------------------

STEPS = [
    ("Selection Method", _step_method),
    ("Number Picker", _step_numbers),
    ("Wheel Selection", _step_wheel),
    ("Constraints", _step_constraints),
    ("Powerball", _step_powerball),
    ("Budget", _step_budget),
    ("Review & Generate", _step_review),
    ("Output", _step_output),
]


def render_wizard() -> None:
    """Render the full multi‑step wizard inside the current Streamlit page."""
    st.markdown(
        '<h2 class="section-header">🎫 Generate Tickets Wizard</h2>',
        unsafe_allow_html=True,
    )

    # Init session state
    if "wizard" not in st.session_state:
        st.session_state["wizard"] = {}
    if "wiz_step" not in st.session_state:
        st.session_state["wiz_step"] = 0

    step_idx = st.session_state["wiz_step"]
    total = len(STEPS)

    # Progress
    progress = (step_idx + 1) / total
    st.progress(progress, f"Step {step_idx + 1} of {total}: {STEPS[step_idx][0]}")

    # Render current step
    valid = STEPS[step_idx][1]()

    # Navigation
    c1, c2, c3 = st.columns([1, 1, 4])
    if step_idx > 0 and c1.button("← Back", use_container_width=True):
        st.session_state["wiz_step"] -= 1
        st.rerun()
    if step_idx < total - 1:
        if c2.button("Next →", type="primary", use_container_width=True, disabled=not valid):
            st.session_state["wiz_step"] += 1
            st.rerun()
    else:
        if c2.button("🔄 Start Over", use_container_width=True):
            st.session_state["wizard"] = {}
            st.session_state["wiz_step"] = 0
            st.rerun()
