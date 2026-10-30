"""
numerical_attraction.py
=======================
Detects consecutive pairs (e.g., 20, 21) and +2 gaps (e.g., 22, 24)
across the last N draws. Returns an "attraction score" for every number pair.
Feed this into the wheel generator as a soft constraint.

Based on Emil Albert's Lotto Code: ~63% of draws contain at least one
consecutive pair or +2 gap from the last 30 draws.

Integrates with: wheel_generator.py, block_analysis.py, dashboard.py
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_LOOKBACK = 30
POOL_SIZE = 40

# Albert's observed frequencies (from the book)
ALBERT_BASELINE = {
    "consecutive": 0.63,  # ~63% of draws have a consecutive pair from last 30
    "plus_two": 0.42,  # ~42% of draws have a +2 gap from last 30
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AttractionProfile:
    """Complete attraction analysis for a number pool."""

    lookback_draws: int
    total_draws_analyzed: int
    consecutive_pairs: dict[tuple[int, int], int]  # (a, a+1) -> count
    plus_two_pairs: dict[tuple[int, int], int]  # (a, a+2) -> count
    raw_attraction_scores: dict[tuple[int, int], float]
    normalized_scores: dict[tuple[int, int], float]  # 0.0 - 1.0
    hot_numbers: list[int]  # numbers in hot pairs
    cold_numbers: list[int]  # numbers rarely in pairs
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class WheelAttractionScore:
    """Score for a candidate wheel against the attraction profile."""

    wheel_numbers: list[int]
    consecutive_pairs_present: list[tuple[int, int]]
    plus_two_pairs_present: list[tuple[int, int]]
    attraction_score: float  # sum of normalized pair scores
    coverage_ratio: float  # what fraction of hot pairs are covered
    albert_alignment: float  # how close to Albert's ~63% pattern
    recommendation: str


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------


def extract_pairs_from_draw(
    draw: list[int],
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """
    From a single draw (6 main numbers), extract all consecutive and +2 pairs.
    Returns (consecutive_set, plus_two_set).
    """
    sorted_nums = sorted(set(draw))
    consecutive = set()
    plus_two = set()

    for i, a in enumerate(sorted_nums):
        for b in sorted_nums[i + 1 :]:
            diff = b - a
            if diff == 1:
                consecutive.add((a, b))
            elif diff == 2:
                plus_two.add((a, b))
            elif diff > 2:
                break  # sorted, so no need to check further

    return consecutive, plus_two


def analyze_attraction(
    draws: list[list[int]],
    lookback: int = DEFAULT_LOOKBACK,
    pool_size: int = POOL_SIZE,
) -> AttractionProfile:
    """
    Analyze the last `lookback` draws for consecutive and +2 gap patterns.

    Args:
        draws: List of draws, each a list of 6 main numbers.
        lookback: How many recent draws to analyze.
        pool_size: Total numbers in the game (e.g., 40 for NZ Lotto).

    Returns:
        AttractionProfile with all pair frequencies and scores.
    """
    recent = draws[-lookback:] if len(draws) > lookback else draws
    total = len(recent)

    consec_counter: Counter[tuple[int, int]] = Counter()
    plus2_counter: Counter[tuple[int, int]] = Counter()

    for draw in recent:
        c, p2 = extract_pairs_from_draw(draw)
        consec_counter.update(c)
        plus2_counter.update(p2)

    # Raw scores: simple frequency count
    all_pairs = set(consec_counter.keys()) | set(plus2_counter.keys())
    raw_scores = {}
    for pair in all_pairs:
        raw_scores[pair] = consec_counter.get(pair, 0) + 0.5 * plus2_counter.get(pair, 0)

    # Normalize to 0-1 range
    if raw_scores:
        max_score = max(raw_scores.values())
        min_score = min(raw_scores.values())
        score_range = max_score - min_score if max_score != min_score else 1.0
        normalized = {pair: (score - min_score) / score_range for pair, score in raw_scores.items()}
    else:
        normalized = {}

    # Identify hot/cold numbers
    num_freq: Counter[int] = Counter()
    for pair in all_pairs:
        num_freq.update(pair)

    hot = [n for n, c in num_freq.most_common(10)]
    cold = [n for n in range(1, pool_size + 1) if n not in num_freq]

    # Albert alignment: what % of recent draws had at least one consecutive pair?
    draws_with_consecutive = sum(1 for d in recent if extract_pairs_from_draw(d)[0])
    draws_with_plus2 = sum(1 for d in recent if extract_pairs_from_draw(d)[1])

    summary = {
        "draws_with_consecutive": draws_with_consecutive,
        "draws_with_plus_two": draws_with_plus2,
        "consecutive_rate": draws_with_consecutive / total if total else 0.0,
        "plus_two_rate": draws_with_plus2 / total if total else 0.0,
        "albert_consecutive_baseline": ALBERT_BASELINE["consecutive"],
        "albert_plus_two_baseline": ALBERT_BASELINE["plus_two"],
        "total_pairs_detected": len(all_pairs),
        "unique_consecutive_pairs": len(consec_counter),
        "unique_plus_two_pairs": len(plus2_counter),
    }

    return AttractionProfile(
        lookback_draws=lookback,
        total_draws_analyzed=total,
        consecutive_pairs=dict(consec_counter),
        plus_two_pairs=dict(plus2_counter),
        raw_attraction_scores=raw_scores,
        normalized_scores=normalized,
        hot_numbers=hot,
        cold_numbers=cold,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Wheel scoring (soft constraint for generator)
# ---------------------------------------------------------------------------


def score_wheel_attraction(
    wheel_numbers: list[int],
    profile: AttractionProfile,
    target_consecutive_pairs: int = 1,
    target_plus_two_pairs: int = 1,
) -> WheelAttractionScore:
    """
    Score a candidate wheel (or single ticket) against the attraction profile.
    Higher score = better alignment with recent hot patterns.

    Args:
        wheel_numbers: A sorted list of 6 (or more) numbers in the wheel.
        profile: AttractionProfile from analyze_attraction().
        target_consecutive_pairs: Ideal number of consecutive pairs to include.
        target_plus_two_pairs: Ideal number of +2 gap pairs to include.
    """
    wheel_set = set(wheel_numbers)
    consec_found = []
    plus2_found = []
    attraction_sum = 0.0

    # Check all pairs in the wheel
    sorted_wheel = sorted(wheel_numbers)
    for i, a in enumerate(sorted_wheel):
        for b in sorted_wheel[i + 1 :]:
            diff = b - a
            if diff == 1:
                consec_found.append((a, b))
                attraction_sum += profile.normalized_scores.get((a, b), 0.0)
            elif diff == 2:
                plus2_found.append((a, b))
                attraction_sum += profile.normalized_scores.get((a, b), 0.0) * 0.5

    # Coverage ratio: how many of the top hot pairs are covered?
    top_pairs = sorted(profile.normalized_scores.items(), key=lambda x: -x[1])[:20]
    covered = sum(1 for pair, _ in top_pairs if pair[0] in wheel_set and pair[1] in wheel_set)
    coverage_ratio = covered / len(top_pairs) if top_pairs else 0.0

    # Albert alignment: how close is this wheel to the ~63% pattern?
    has_consecutive = len(consec_found) >= target_consecutive_pairs
    has_plus2 = len(plus2_found) >= target_plus_two_pairs
    albert_align = 0.0
    if has_consecutive:
        albert_align += 0.63
    if has_plus2:
        albert_align += 0.37

    # Recommendation
    if has_consecutive and has_plus2:
        rec = "Strong Albert alignment: includes both consecutive and +2 gap pairs."
    elif has_consecutive:
        rec = "Good: includes consecutive pair. Consider adding a +2 gap."
    elif has_plus2:
        rec = "Moderate: includes +2 gap. Consider adding a consecutive pair."
    else:
        rec = "Weak: no hot attraction pairs. Wheel may be too spread out."

    return WheelAttractionScore(
        wheel_numbers=wheel_numbers,
        consecutive_pairs_present=consec_found,
        plus_two_pairs_present=plus2_found,
        attraction_score=attraction_sum,
        coverage_ratio=coverage_ratio,
        albert_alignment=albert_align,
        recommendation=rec,
    )


def rank_wheels_by_attraction(
    wheels: list[list[int]],
    profile: AttractionProfile,
) -> list[tuple[list[int], float]]:
    """
    Rank multiple candidate wheels by their attraction score.
    Returns list of (wheel_numbers, score) sorted descending.
    """
    scored = []
    for wheel in wheels:
        score_obj = score_wheel_attraction(wheel, profile)
        # Composite score: attraction + coverage + albert alignment
        composite = (
            score_obj.attraction_score * 0.5
            + score_obj.coverage_ratio * 0.3
            + score_obj.albert_alignment * 0.2
        )
        scored.append((wheel, composite))

    scored.sort(key=lambda x: -x[1])
    return scored


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------


def get_attraction_constraints(
    profile: AttractionProfile,
    top_n_pairs: int = 10,
    min_score_threshold: float = 0.3,
) -> dict[str, Any]:
    """
    Generate constraint hints for the wheel generator.
    Returns a dict that can be passed to a GA or optimizer.
    """
    # Top consecutive pairs to favor
    top_consec = sorted(
        profile.consecutive_pairs.items(),
        key=lambda x: -x[1],
    )[:top_n_pairs]

    top_plus2 = sorted(
        profile.plus_two_pairs.items(),
        key=lambda x: -x[1],
    )[:top_n_pairs]

    # Numbers that must appear (hot numbers)
    must_include = [
        n
        for n in profile.hot_numbers[:6]
        if any(
            score >= min_score_threshold
            for pair, score in profile.normalized_scores.items()
            if n in pair
        )
    ]

    return {
        "favored_consecutive_pairs": [list(p) for p, _ in top_consec],
        "favored_plus_two_pairs": [list(p) for p, _ in top_plus2],
        "must_include_numbers": list(dict.fromkeys(must_include)),  # dedupe, preserve order
        "avoid_numbers": profile.cold_numbers[:5],
        "summary": profile.summary,
    }


def save_profile(
    profile: AttractionProfile, path: Path = Path("data/attraction_profile.json")
) -> None:
    """Serialize profile to JSON for caching."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "lookback_draws": profile.lookback_draws,
        "total_draws_analyzed": profile.total_draws_analyzed,
        "consecutive_pairs": {f"{a},{b}": c for (a, b), c in profile.consecutive_pairs.items()},
        "plus_two_pairs": {f"{a},{b}": c for (a, b), c in profile.plus_two_pairs.items()},
        "normalized_scores": {f"{a},{b}": s for (a, b), s in profile.normalized_scores.items()},
        "hot_numbers": profile.hot_numbers,
        "cold_numbers": profile.cold_numbers,
        "summary": profile.summary,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_profile(
    path: Path = Path("data/attraction_profile.json"),
) -> AttractionProfile:
    """Load cached profile."""
    with open(path) as f:
        data = json.load(f)

    def _parse_pairs(d: dict[str, Any]) -> dict[tuple[int, int], Any]:
        return {cast(tuple[int, int], tuple(map(int, k.split(",")))): v for k, v in d.items()}

    # NOTE: saved JSON predates the raw_attraction_scores field, so this call
    # intentionally omits it (raw scores are recomputed, never persisted).
    return AttractionProfile(  # type: ignore[call-arg]
        lookback_draws=data["lookback_draws"],
        total_draws_analyzed=data["total_draws_analyzed"],
        consecutive_pairs=_parse_pairs(data["consecutive_pairs"]),
        plus_two_pairs=_parse_pairs(data["plus_two_pairs"]),
        normalized_scores=_parse_pairs(data["normalized_scores"]),
        hot_numbers=data["hot_numbers"],
        cold_numbers=data["cold_numbers"],
        summary=data["summary"],
    )


# ---------------------------------------------------------------------------
# Dashboard-friendly summary
# ---------------------------------------------------------------------------


def profile_to_markdown(profile: AttractionProfile) -> str:
    """Convert profile to markdown for Streamlit/CLI display."""
    lines = [
        "# Numerical Attraction Profile",
        "",
        f"- **Lookback draws:** {profile.lookback_draws}",
        f"- **Total draws analyzed:** {profile.total_draws_analyzed}",
        f"- **Consecutive pair rate:** {profile.summary.get('consecutive_rate', 0):.1%}",
        f"- **+2 gap rate:** {profile.summary.get('plus_two_rate', 0):.1%}",
        f"- **Albert baseline (consecutive):** {ALBERT_BASELINE['consecutive']:.1%}",
        "",
        "## Top 10 Consecutive Pairs",
    ]
    top_c = sorted(profile.consecutive_pairs.items(), key=lambda x: -x[1])[:10]
    for (a, b), count in top_c:
        score = profile.normalized_scores.get((a, b), 0.0)
        lines.append(f"- ({a}, {b}): {count} hits (score: {score:.2f})")

    lines.extend(["", "## Top 10 +2 Gap Pairs"])
    top_p = sorted(profile.plus_two_pairs.items(), key=lambda x: -x[1])[:10]
    for (a, b), count in top_p:
        score = profile.normalized_scores.get((a, b), 0.0)
        lines.append(f"- ({a}, {b}): {count} hits (score: {score:.2f})")

    lines.extend(["", "## Hot Numbers"])
    lines.append(", ".join(map(str, profile.hot_numbers[:10])))

    lines.extend(["", "## Cold Numbers"])
    lines.append(", ".join(map(str, profile.cold_numbers[:10])))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Streamlit tab (lazy UI rendering; called by dashboard.py)
# ---------------------------------------------------------------------------
def render_attraction_tab(draws: list[tuple[list[int], int, int, str]]) -> None:
    """Render the "🧲 Attraction Profile" Streamlit page.

    Extracted from dashboard.py (pure code motion, behavior identical).
    Streamlit is imported lazily so this module stays importable without
    a Streamlit runtime.

    Parameters
    ----------
    draws : list[tuple[list[int], int, int, str]]
        Draw history as (numbers, powerball, bonus, date) tuples.
    """
    import pandas as pd
    import streamlit as st

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
            return analyze_attraction([list(d) for d in recent_draws], lookback=30)

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
            rows_c = sorted(profile.consecutive_pairs.items(), key=lambda x: (-x[1], x[0]))[:10]
            if rows_c:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Pair": f"{a}–{b}",
                                "Hits": c,
                                "Score": round(profile.normalized_scores.get((a, b), 0.0), 3),
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
            rows_p = sorted(profile.plus_two_pairs.items(), key=lambda x: (-x[1], x[0]))[:10]
            if rows_p:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Pair": f"{a}–{b}",
                                "Hits": c,
                                "Score": round(profile.normalized_scores.get((a, b), 0.0), 3),
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
                st.markdown(_badges(profile.hot_numbers[:10], "#e74c3c"), unsafe_allow_html=True)
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
                st.caption(f"{len(profile.cold_numbers)} numbers absent from all detected pairs")
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
                    wa_score = score_wheel_attraction(nums, profile)
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


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Fake 30 draws with injected patterns
    np.random.seed(42)
    fake_draws = []
    for _ in range(30):
        # 70% chance of including a consecutive pair
        if np.random.rand() < 0.7:
            base = np.random.randint(1, 35)
            pair = [base, base + 1]
            rest = np.random.choice(
                [n for n in range(1, 41) if n not in pair],
                size=4,
                replace=False,
            )
            draw = sorted(list(pair) + list(rest))
        else:
            draw = sorted(np.random.choice(range(1, 41), size=6, replace=False))
        fake_draws.append(draw)

    profile = analyze_attraction(fake_draws, lookback=30)
    print(profile_to_markdown(profile))
    print("\n--- Wheel Scoring Demo ---")

    test_wheel = [3, 4, 12, 14, 25, 33]  # 3-4 is consecutive
    score = score_wheel_attraction(test_wheel, profile)
    print(f"Wheel: {score.wheel_numbers}")
    print(f"Consecutive pairs: {score.consecutive_pairs_present}")
    print(f"+2 pairs: {score.plus_two_pairs_present}")
    print(f"Attraction score: {score.attraction_score:.2f}")
    print(f"Albert alignment: {score.albert_alignment:.2f}")
    print(f"Recommendation: {score.recommendation}")
