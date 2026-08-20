#!/usr/bin/env python3
"""
wheel_generator.py — Generate abbreviated lottery wheels (covering designs) for NZ Lotto 6/40.

Usage:
    from wheel_generator import generate_abbreviated_wheel

    tickets, desc = generate_abbreviated_wheel([1,2,3,4,5,6,7,8,9,10], "4 if 4")
    # tickets: list of 6-number tuples
    # desc: human-readable guarantee string
"""

import itertools
import logging
import random
import sqlite3
from collections import Counter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Guarantee parsing
# ---------------------------------------------------------------------------


def _parse_guarantee(guarantee: str) -> tuple[int, int]:
    """Parse 'X if Y' into (win_match, trigger_match)."""
    s = guarantee.lower().replace(" ", "").replace("‐", "-").replace("–", "-")
    if "if" not in s:
        raise ValueError(f"Invalid guarantee format: '{guarantee}'. Use 'X if Y'.")
    parts = s.split("if")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(
            f"Invalid guarantee format: '{guarantee}'. Use 'X if Y'."
        ) from None


def _guarantee_description(guarantee: str, pool_size: int) -> str:
    """Human-readable guarantee text."""
    win_match, trigger_match = _parse_guarantee(guarantee)
    return (
        f"If {trigger_match} of your {pool_size} numbers are drawn, "
        f"you are guaranteed at least one ticket with {win_match}+ matches."
    )


# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------


def generate_abbreviated_wheel(
    numbers: list[int],
    guarantee: str = "4 if 4",
    max_tickets: int = 200,
    max_bonus_coverage: bool = False,
    prefer_numbers: list[int] | None = None,
    include_numbers: list[int] | None = None,
    exclude_numbers: list[int] | None = None,
    sum_range: tuple[int, int] | None = None,
    verbose: bool = False,
) -> tuple[list[tuple[int, ...]], str]:
    """Generate an abbreviated wheel using greedy set covering.

    Builds all possible C(pool, 6) tickets and all C(pool, trigger_match)
    trigger combinations, then greedily picks tickets that cover the most
    remaining trigger combos.

    Args:
        numbers: Your chosen pool of numbers (ideally 6–20 numbers).
        guarantee: Covering guarantee, e.g. "4 if 4", "4 if 5", "5 if 6".
        max_tickets: Hard limit on output ticket count.
        max_bonus_coverage: When True, prefer tickets that add new distinct
            numbers to the wheel, increasing bonus ball eligibility at the
            cost of slightly reduced trigger-combo coverage per ticket.
        prefer_numbers: Optional list of numbers that MUST be included in the
            pool.  If the user's input is missing any of these, they are
            appended automatically.
        include_numbers: Numbers that MUST appear in the pool (added to the
            user-supplied list before validation).
        exclude_numbers: Numbers that are STRIPPED from the pool before
            wheel generation begins.
        sum_range: Optional (min_sum, max_sum) from
            sum_validator.calculate_dynamic_sum_range(). When set, candidate
            tickets whose sum falls outside the range are filtered out
            before the greedy cover (Albert's central-90% rule). The greedy
            loop then naturally picks in-range alternatives instead. Not
            applied to full (6-if-Y) wheels, where filtering would void the
            exhaustive guarantee.
        verbose: Print progress info to stderr.

    Returns:
        (list of 6-number ticket tuples, guarantee description string).
    """
    nums = sorted(set(numbers))
    # Apply include/exclude filters
    if include_numbers:
        for n in include_numbers:
            if 1 <= n <= 40 and n not in nums:
                nums.append(n)
        nums = sorted(set(nums))
    if exclude_numbers:
        exclude_set = set(exclude_numbers)
        nums = [n for n in nums if n not in exclude_set]

    pool_size = len(nums)
    ticket_size = 6

    try:
        win_match, trigger_match = _parse_guarantee(guarantee)
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Invalid guarantee: '{guarantee}'.") from exc

    # --- Validation ---
    if not (2 <= win_match <= ticket_size):
        raise ValueError(f"win_match ({win_match}) must be 2–{ticket_size}.")
    if trigger_match < win_match:
        raise ValueError(
            f"trigger_match ({trigger_match}) cannot be less than "
            f"win_match ({win_match})."
        )
    if pool_size < trigger_match:
        desc = (
            f"Need at least {trigger_match} numbers in your pool "
            f"for the {guarantee} guarantee."
        )
        return [], desc
    if pool_size < ticket_size:
        desc = f"Need at least {ticket_size} numbers to generate tickets."
        return [], desc

    desc = _guarantee_description(guarantee, pool_size)

    # --- Enforce prefer_numbers ---
    if prefer_numbers:
        prefs = sorted({pn for pn in prefer_numbers if 1 <= pn <= 40})
        missing = [pn for pn in prefs if pn not in nums]
        if missing:
            # Append missing preferred numbers; if pool gets too large,
            # remove the lowest-frequency non-preferred numbers from the tail
            extended = nums + missing
            if len(extended) > 20:
                # Keep preferred + top-frequency non-preferred
                non_pref = [n for n in nums if n not in prefs]
                keep = len(non_pref) - (len(extended) - 20)
                if keep < 0:
                    keep = 0
                nums = sorted(prefs + non_pref[:keep])
            else:
                nums = sorted(extended)
            pool_size = len(nums)
            desc = _guarantee_description(guarantee, pool_size)

    # --- Full wheel shortcut (6 if Y) ---
    if win_match == ticket_size:
        all_tickets = list(itertools.combinations(nums, ticket_size))
        n = len(all_tickets)
        if n <= max_tickets:
            return all_tickets, desc
        return [], (
            f"Full wheel requires {n} tickets (exceeds {max_tickets} limit). "
            f"Reduce your pool size."
        )

    # --- Generate all possible tickets ---
    all_tickets = list(itertools.combinations(nums, ticket_size))
    trigger_combos = list(itertools.combinations(nums, trigger_match))
    n_triggers = len(trigger_combos)

    if verbose:
        print(f"  Pool: {pool_size} numbers  |  Guarantee: {guarantee}")
        print(f"  Possible tickets: {len(all_tickets)}")
        print(f"  Trigger combos to cover: {n_triggers}")

    # --- Heuristic fallback for very large pools ---
    if pool_size > 20:
        return _heuristic_wheel(
            nums, win_match, trigger_match, max_tickets, desc, verbose
        )

    # --- Build fast index: ticket -> set of trigger combos it covers ---
    # Each 6-number ticket covers exactly C(6, trigger_match) combos.
    # Generating sub-combos from each ticket is O(T * C(6, tm)) instead of
    # O(T * n_triggers), a huge speedup.
    trigger_set_lookup = {tc: idx for idx, tc in enumerate(trigger_combos)}
    ticket_coverage = []
    for ticket in all_tickets:
        covered = set()
        for sub in itertools.combinations(ticket, trigger_match):
            idx = trigger_set_lookup.get(sub)
            if idx is not None:
                covered.add(idx)
        if covered:
            ticket_coverage.append((ticket, covered))

    if not ticket_coverage:
        return [], f"No tickets can cover {trigger_match}-combos from this pool."

    # --- Albert sum-range filter (optional) ---
    # Drop candidate tickets whose sum is outside the central-90% range;
    # the greedy loop below then regenerates with in-range alternatives.
    if sum_range is not None:
        lo_sum, hi_sum = sum_range
        before = len(ticket_coverage)
        ticket_coverage = [
            (t, cov) for t, cov in ticket_coverage if lo_sum <= sum(t) <= hi_sum
        ]
        dropped = before - len(ticket_coverage)
        if dropped:
            logger.warning(
                "Sum-range filter: dropped %d/%d candidate tickets outside "
                "the %d–%d range.",
                dropped,
                before,
                lo_sum,
                hi_sum,
            )
        if not ticket_coverage:
            return [], (
                f"Sum-range filter ({lo_sum}–{hi_sum}) removed every candidate "
                f"ticket — widen the range or pick different pool numbers."
            )

    # --- Greedy set cover ---
    uncovered = set(range(n_triggers))
    selected_tickets: list[tuple[int, ...]] = []
    # Sort descending by coverage size — good heuristic that speeds early iterations
    seen_numbers: set[int] = set()
    ticket_coverage.sort(key=lambda x: len(x[1]), reverse=True)
    total_covered = 0

    while uncovered and len(selected_tickets) < max_tickets:
        best_ticket = None
        best_covered = set()
        best_count = 0
        best_score = -1.0

        for ticket, cov in ticket_coverage:
            # Skip already-selected tickets
            if ticket in selected_tickets:
                continue
            new = cov & uncovered
            count = len(new)

            # Bonus-coverage bonus: each new distinct number adds a small
            # weight so the algorithm prefers expanding the number pool
            # even when it slightly reduces immediate combo coverage.
            if max_bonus_coverage:
                new_nums = len(set(ticket) - seen_numbers)
                score = count + new_nums * 0.5
            else:
                score = count

            if score > best_score:
                best_count = count
                best_score = score
                best_ticket = ticket
                best_covered = new
                # If this ticket's full coverage is entirely uncovered, it's optimal
                if count == len(cov):
                    break

        if best_count == 0 or best_ticket is None:
            break

        selected_tickets.append(best_ticket)
        seen_numbers.update(best_ticket)
        uncovered -= best_covered
        total_covered += best_count

    n_covered = n_triggers - len(uncovered)
    if verbose:
        print(
            f"  Generated {len(selected_tickets)} tickets "
            f"covering {n_covered}/{n_triggers} combos"
        )

    if uncovered and len(selected_tickets) >= max_tickets:
        desc += (
            f" ({n_covered}/{n_triggers} combos covered; "
            f"increase max_tickets or use fewer numbers for full coverage)"
        )

    return selected_tickets, desc


# ---------------------------------------------------------------------------
# Heuristic fallback for large pools (>20 numbers)
# ---------------------------------------------------------------------------


def _heuristic_wheel(
    nums: list[int],
    win_match: int,
    trigger_match: int,
    max_tickets: int,
    desc: str,
    verbose: bool = False,
) -> tuple[list[tuple[int, ...]], str]:
    """Randomised covering for large pools where exhaustive search is infeasible.

    Generates random 6-number tickets and scores them by how many new
    trigger combos they'd cover (sampled from a random subset).  Picks the
    best-scoring ticket at each step.
    """
    pool_size = len(nums)
    ticket_size = 6
    rng = random.Random()

    # Sample trigger combos to estimate coverage (can't enumerate all)
    # For heuristic, we just pick balanced-looking tickets.
    selected: set[tuple[int, ...]] = set()
    attempts = 0
    seen_tickets: set[tuple[int, ...]] = set()

    while len(selected) < max_tickets and attempts < max_tickets * 500:
        attempts += 1
        ticket = tuple(sorted(rng.sample(nums, ticket_size)))
        if ticket in seen_tickets:
            continue
        seen_tickets.add(ticket)

        # Accept ticket if it's "balanced": has a mix of high/low numbers
        # and isn't too similar to already selected tickets
        min_new = 0
        for existing in selected:
            overlap = len(set(ticket) & set(existing))
            if overlap > min_new:
                min_new = overlap

        # Accept if at most 3 numbers overlap with any existing ticket
        if min_new <= 3:
            selected.add(ticket)

        # Prevent infinite loop
        if attempts >= max_tickets * 500:
            break

    # If heuristic didn't yield enough, just sample randomly
    while len(selected) < min(max_tickets, 50):
        remaining = [t for t in seen_tickets if t not in selected] or [
            tuple(sorted(rng.sample(nums, ticket_size))) for _ in range(100)
        ]
        for t in remaining:
            if len(selected) >= min(max_tickets, 50):
                break
            selected.add(t)

    result = sorted(selected)
    if verbose:
        print(
            f"  Heuristic: generated {len(result)} tickets " f"(pool size {pool_size})"
        )

    return result, desc + f" ({len(result)} tickets via heuristic)."


# ---------------------------------------------------------------------------
# Bonus hot-zone coverage metric
# ---------------------------------------------------------------------------


def bonus_hotzone_coverage(
    tickets: list[tuple[int, ...]],
    conn: sqlite3.Connection,
    lookback: int = 50,
    top_n: int = 10,
) -> tuple[float, list[int], list[int]]:
    """Percentage of the wheel's pool numbers inside the bonus hot zone.

    The "bonus hot zone" is the ``top_n`` most frequently drawn bonus
    numbers over the last ``lookback`` draws (draws table, ordered by date).

    Args:
        tickets: Generated wheel tickets (iterables of 6 ints).
        conn: Open connection to lotto.db.
        lookback: How many recent draws to consider (default 50).
        top_n: Size of the hot zone (default 10 numbers).

    Returns:
        (coverage_pct, hot_numbers, pool_hits) — the percentage (0–100,
        rounded to 1 dp), the hot-zone numbers, and which pool numbers are
        in the zone. coverage_pct is 0.0 when no bonus data exists.
    """
    pool = sorted({n for ticket in tickets for n in ticket})
    if not pool:
        return 0.0, [], []

    rows = conn.execute(
        "SELECT bonus FROM draws ORDER BY draw_date DESC LIMIT ?",
        (lookback,),
    ).fetchall()
    freq = Counter(b for (b,) in rows if b and 1 <= b <= 40)
    if not freq:
        return 0.0, [], pool

    hot = [n for n, _ in freq.most_common(top_n)]
    hits = [n for n in pool if n in hot]
    pct = round(len(hits) / len(pool) * 100, 1)
    return pct, hot, hits
