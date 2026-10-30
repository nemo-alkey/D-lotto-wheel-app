import itertools
import random
import sqlite3
import time
from collections import Counter
from pathlib import Path

import streamlit as st

# ── Page config ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Abbreviated Wheel Generator",
    page_icon="🎯",
    layout="wide",
)

# ── Constants ───────────────────────────────────────────────────────────
LOTTO_MIN, LOTTO_MAX = 1, 40
TICKET_SIZE = 6
PB_MIN, PB_MAX = 1, 10
COST_PER_LINE = 0.70
DB_PATH = Path.cwd() / "data" / "lotto.db"


# ── Database helpers ────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_hot_numbers(top_n: int = 40) -> list[int]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    rows = conn.execute("SELECT numbers FROM draws").fetchall()
    conn.close()
    freq = Counter()
    for (nums_str,) in rows:
        freq.update(int(x) for x in nums_str.split(","))
    return [n for n, _ in freq.most_common(top_n)]


@st.cache_data(ttl=300)
def get_hot_powerball() -> int:
    if not DB_PATH.exists():
        return random.randint(PB_MIN, PB_MAX)
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    rows = conn.execute("SELECT powerball FROM draws").fetchall()
    conn.close()
    freq = Counter(pb for (pb,) in rows if pb is not None)
    return freq.most_common(1)[0][0] if freq else random.randint(PB_MIN, PB_MAX)


# ── Pool generation ─────────────────────────────────────────────────────
def generate_pool(
    pool_size: int, strategy: str, include: list[int], exclude: list[int]
) -> list[int]:
    available = [n for n in range(LOTTO_MIN, LOTTO_MAX + 1) if n not in exclude]
    include = [n for n in include if n in available]
    if len(include) > pool_size:
        raise ValueError("Too many included numbers")
    remaining = [n for n in available if n not in include]
    needed = pool_size - len(include)

    if strategy == "hot":
        hot = get_hot_numbers(LOTTO_MAX)
        candidates = [n for n in hot if n in remaining]
        pool = include + candidates[:needed]
    elif strategy == "cold":
        hot = set(get_hot_numbers(LOTTO_MAX))
        cold = [n for n in remaining if n not in hot]
        pool = include + cold[:needed]
    elif strategy == "balanced":
        pool = include
        sources = [remaining, remaining[::-1], remaining[::2], remaining[1::2]]
        idx = 0
        while len(pool) < pool_size and idx < 2000:
            src = sources[idx % len(sources)]
            pos = idx // len(sources)
            if pos < len(src) and src[pos] not in pool:
                pool.append(src[pos])
            idx += 1
    else:
        pool = include + random.sample(remaining, needed)

    if len(pool) < pool_size:
        extras = [n for n in remaining if n not in pool]
        pool += random.sample(extras, pool_size - len(pool))
    return sorted(pool[:pool_size])


# ── Core greedy set-cover algorithm ─────────────────────────────────────
def compute_coverage(
    ticket: tuple[int, ...], triggers: list[tuple[int, ...]], guarantee: int
) -> set[int]:
    tset = set(ticket)
    covered = set()
    for i, trig in enumerate(triggers):
        if len(tset & set(trig)) >= guarantee:
            covered.add(i)
    return covered


def greedy_set_cover(
    pool: list[int], guarantee: int, trigger_size: int, progress_bar=None
) -> list[tuple[int, ...]]:
    triggers = list(itertools.combinations(pool, trigger_size))
    all_tickets = list(itertools.combinations(pool, TICKET_SIZE))

    ticket_coverage = [compute_coverage(ticket, triggers, guarantee) for ticket in all_tickets]

    uncovered: set[int] = set(range(len(triggers)))
    selected: list[tuple[int, ...]] = []

    while uncovered:
        best_ticket = None
        best_cover = set()
        best_count = -1

        for ticket, coverage in zip(all_tickets, ticket_coverage, strict=False):
            new_cover = coverage & uncovered
            cnt = len(new_cover)
            if cnt > best_count:
                best_count = cnt
                best_cover = new_cover
                best_ticket = ticket

        if best_ticket is None or best_count == 0:
            st.warning(
                f"Could not cover {len(uncovered)} remaining triggers. Guarantee may be impossible."
            )
            break

        selected.append(best_ticket)
        uncovered -= best_cover

        if progress_bar is not None:
            progress = 1.0 - (len(uncovered) / len(triggers))
            progress_bar.progress(min(progress, 0.99), text=f"Selected {len(selected)} tickets...")

    if progress_bar is not None:
        progress_bar.empty()
    return selected


# ── Verification ────────────────────────────────────────────────────────
def verify_wheel(
    tickets: list[tuple[int, ...]],
    pool: list[int],
    guarantee: int,
    trigger_size: int,
    sims: int = 2000,
) -> tuple[bool, float, int]:
    hits = 0
    worst = TICKET_SIZE
    for _ in range(sims):
        trigger = random.sample(pool, trigger_size)
        tset = set(trigger)
        best = max(len(set(tick) & tset) for tick in tickets)
        if best >= guarantee:
            hits += 1
        worst = min(worst, best)
    return hits == sims, hits / sims, worst


# ── UI ──────────────────────────────────────────────────────────────────
st.title("🎯 Abbreviated Wheel Generator")
st.markdown("""
Generate **mathematically guaranteed** abbreviated wheels that cost a fraction of a full wheel.
Choose your pool, guarantee level, and let the greedy set-cover algorithm do the rest.
""")

with st.expander("ℹ️ What is an abbreviated wheel?", expanded=False):
    st.markdown("""
    An abbreviated wheel is a carefully chosen subset of all possible tickets from your number pool.

    | Guarantee | Meaning | Typical Cost |
    |-----------|---------|-------------|
    | **3 if 3** | Any 3 pool numbers drawn → at least 1 ticket matches 3 | ~$2–$7 |
    | **4 if 4** | Any 4 pool numbers drawn → at least 1 ticket matches 4 | ~$10–$40 |
    | **4 if 5** | Any 5 pool numbers drawn → at least 1 ticket matches 4 | ~$5–$15 |
    | **5 if 6** | All 6 drawn in pool → at least 1 ticket matches 5 | ~$30–$80 |

    **Important:** A guarantee is about the *worst case*, not profit. All wheels lose money long-term.
    """)

# ── Controls ────────────────────────────────────────────────────────────
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Pool Settings")
    pool_size = st.slider(
        "Pool size",
        min_value=6,
        max_value=20,
        value=10,
        step=1,
        help="How many numbers to wheel (6–20). Larger = more tickets.",
    )

    strategy = st.selectbox(
        "Pool strategy",
        options=["random", "hot", "cold", "balanced"],
        format_func=lambda x: {
            "random": "🎲 Random",
            "hot": "🔥 Hot (most frequent historically)",
            "cold": "❄️ Cold (least frequent historically)",
            "balanced": "⚖️ Balanced (spread across ranges)",
        }[x],
    )

    include_str = st.text_input(
        "Force-include numbers (comma-separated)",
        placeholder="e.g. 7, 14, 21",
        help="These numbers will always be in your pool.",
    )
    exclude_str = st.text_input(
        "Exclude numbers (comma-separated)",
        placeholder="e.g. 1, 2, 3",
        help="These numbers will never be in your pool.",
    )

with col2:
    st.subheader("Guarantee & Powerball")
    guarantee = st.selectbox(
        "Guarantee level",
        options=["3 if 3", "4 if 4", "4 if 5", "5 if 6"],
        index=1,
        help="The mathematical promise your wheel makes.",
    )

    pb_option = st.radio(
        "Powerball",
        options=["None", "Hot number", "Fixed number", "Random"],
        horizontal=True,
    )
    powerball = None
    if pb_option == "Fixed number":
        powerball = st.number_input("Fixed Powerball", min_value=1, max_value=10, value=7)
    elif pb_option == "Hot number":
        powerball = get_hot_powerball()
        st.caption(f"Hot Powerball: **{powerball}**")
    elif pb_option == "Random":
        powerball = random.randint(PB_MIN, PB_MAX)
        st.caption(f"Random Powerball: **{powerball}**")

    verify = st.toggle(
        "Run Monte-Carlo verification",
        value=True,
        help="Simulates 2,000 random draws to confirm the guarantee holds.",
    )

# ── Parse inputs ────────────────────────────────────────────────────────
include = []
exclude = []
try:
    if include_str:
        include = [int(x.strip()) for x in include_str.split(",") if x.strip().isdigit()]
    if exclude_str:
        exclude = [int(x.strip()) for x in exclude_str.split(",") if x.strip().isdigit()]
except ValueError:
    st.error("Invalid number format. Use comma-separated integers.")

invalid = [n for n in include + exclude if not (LOTTO_MIN <= n <= LOTTO_MAX)]
if invalid:
    st.error(f"Numbers must be between {LOTTO_MIN} and {LOTTO_MAX}. Invalid: {invalid}")

# ── Generation ──────────────────────────────────────────────────────────
st.divider()

if st.button("🚀 Generate Wheel", type="primary", use_container_width=True):
    if len(include) > pool_size:
        st.error(f"Cannot force-include {len(include)} numbers in a pool of {pool_size}.")
        st.stop()

    try:
        with st.spinner("Building pool..."):
            pool = generate_pool(pool_size, strategy, include, exclude)

        g_match, g_trig = {
            "3 if 3": (3, 3),
            "4 if 4": (4, 4),
            "4 if 5": (4, 5),
            "5 if 6": (5, 6),
        }[guarantee]

        st.info(f"Pool: {pool}  |  Guarantee: {g_match} if {g_trig}")

        progress_bar = st.progress(0, text="Computing coverage matrix...")
        start = time.time()
        tickets = greedy_set_cover(pool, g_match, g_trig, progress_bar=progress_bar)
        elapsed = time.time() - start

        full_count = len(list(itertools.combinations(pool, TICKET_SIZE)))
        reduction = (len(tickets) / full_count * 100) if full_count else 0
        cost = len(tickets) * COST_PER_LINE

        # ── Metrics ─────────────────────────────────────────────────────
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Tickets", len(tickets))
        m2.metric("Full wheel size", full_count)
        m3.metric("Reduction", f"{100 - reduction:.1f}%")
        m4.metric("Cost per draw", f"${cost:.2f}")

        st.caption(f"Generation time: {elapsed:.2f}s")

        # ── Verification ────────────────────────────────────────────────
        if verify:
            with st.spinner("Running Monte-Carlo verification (2,000 sims)..."):
                passed, ratio, worst = verify_wheel(tickets, pool, g_match, g_trig)
            if passed:
                st.success("✅ Verification passed — guarantee holds in all 2,000 simulations.")
            else:
                st.warning(
                    f"⚠️ Verification: guarantee held in {ratio*100:.1f}% of simulations. Worst match: {worst}."
                )
            st.caption(f"Coverage ratio: {ratio*100:.2f}% | Worst-case best-match: {worst}")

        # ── Ticket display ──────────────────────────────────────────────
        st.subheader("Your tickets")

        ticket_data = []
        for i, t in enumerate(tickets, 1):
            nums = " ".join(f"{n:02d}" for n in t)
            pb = str(powerball) if powerball is not None else "—"
            ticket_data.append({"#": i, "Numbers": nums, "PB": pb})

        st.dataframe(ticket_data, use_container_width=True, hide_index=True)

        # ── Download ────────────────────────────────────────────────────
        output_lines = [
            f"Abbreviated Wheel: {g_match} if {g_trig}",
            f"Pool ({len(pool)} numbers): {pool}",
            f"Strategy: {strategy}",
            f"Tickets: {len(tickets)}  (full wheel: {full_count})",
            f"Reduction: {100 - reduction:.1f}% cheaper than full wheel",
            f"Cost per draw: ${cost:.2f}",
        ]
        if powerball is not None:
            output_lines.append(f"Powerball: {powerball}")
        output_lines.append("-" * 50)

        for i, t in enumerate(tickets, 1):
            nums = " ".join(f"{n:02d}" for n in t)
            pb = f"  PB:{powerball}" if powerball is not None else ""
            output_lines.append(f"Ticket {i:3d}: {nums}{pb}")

        wheel_text = "\n".join(output_lines)

        col_d1, col_d2 = st.columns([1, 3])
        with col_d1:
            st.download_button(
                label="📥 Download wheel (.txt)",
                data=wheel_text,
                file_name=f"wheel_abbrev_{g_match}if{g_trig}_pool{len(pool)}.txt",
                mime="text/plain",
            )

        # ── Visual: number coverage heatmap ─────────────────────────────
        st.subheader("Number coverage")
        st.markdown("Shows how many tickets each pool number appears in.")

        coverage = Counter()
        for t in tickets:
            coverage.update(t)

        heat_data = []
        for n in pool:
            heat_data.append({"Number": n, "Appearances": coverage.get(n, 0)})

        st.bar_chart(
            {row["Number"]: row["Appearances"] for row in heat_data}, use_container_width=True
        )

    except Exception as e:
        st.error(f"Error generating wheel: {e}")
        st.exception(e)
