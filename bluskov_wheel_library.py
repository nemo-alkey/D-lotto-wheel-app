"""
Bluskov Wheel Library Extension
================================
Adds proven, mathematically minimal wheels from Iliya Bluskov's
"Combinatorial Lottery Systems (Wheels) with Guaranteed Wins".

Verified systems (combinations entered):
  - DOUBLE_4IF4_10 : System #88  (10 numbers, 30 tickets, TWO 4-wins
                     guaranteed if 4 of your numbers are drawn)

Pending systems (TODO — combinations must be transcribed from the book,
see the instructions above each empty list below):
  - DOUBLE_4IF4_11 : System #89  (11 numbers, 54 tickets, TWO 4-wins
                     guaranteed if 4 of your numbers are drawn)
  - DOUBLE_4IF4_12 : System #90  (12 numbers, 72 tickets, TWO 4-wins
                     guaranteed if 4 of your numbers are drawn)
  - TRIPLE_4IF5_12 : System #107 (12 numbers, 22 tickets, main guarantee
                     is TWO 3-wins if 3 of your numbers are drawn)
  - SIX_4IF5_12    : System #119 (12 numbers, 44 tickets, SIX 4-wins
                     guaranteed if 5 of your numbers are drawn)

WARNING: Do NOT fabricate wheel combinations. The guarantees only hold
when using the exact published combinations from Bluskov's book.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

#: Source for all systems in this library. Systems are indexed by number
#: (e.g., System #89); page numbers vary by edition, so locate each system
#: by its number in the book's tables.
BOOK_REFERENCE = "Iliya Bluskov, 'Combinatorial Lottery Systems (Wheels) with " "Guaranteed Wins'"

# ---------------------------------------------------------------------------
# System #88 — 10 numbers, 30 combinations
# Guarantee: TWO 4-wins if 4 of your numbers are drawn.
# Properties: Exceptionally highly balanced.
#   Each number in exactly 18 combinations.
#   Each pair in exactly 10 combinations.
#   Each triple in exactly 5 combinations.
#   Every two combinations differ in at least 2 numbers.
# Source: Verified from Bluskov's book / lottowheeling.com
# ---------------------------------------------------------------------------
DOUBLE_4IF4_10: list[list[int]] = [
    [1, 2, 3, 4, 5, 10],
    [1, 2, 3, 4, 7, 8],
    [1, 2, 3, 5, 6, 8],
    [1, 2, 3, 5, 7, 9],
    [1, 2, 3, 6, 9, 10],
    [1, 2, 4, 5, 6, 9],
    [1, 2, 4, 6, 7, 10],
    [1, 2, 4, 8, 9, 10],
    [1, 2, 5, 7, 8, 10],
    [1, 2, 6, 7, 8, 9],
    [1, 3, 4, 5, 6, 7],
    [1, 3, 4, 6, 8, 9],
    [1, 3, 4, 7, 9, 10],
    [1, 3, 5, 8, 9, 10],
    [1, 3, 6, 7, 8, 10],
    [1, 4, 5, 6, 8, 10],
    [1, 4, 5, 7, 8, 9],
    [1, 5, 6, 7, 9, 10],
    [2, 3, 4, 5, 8, 9],
    [2, 3, 4, 6, 7, 9],
    [2, 3, 4, 6, 8, 10],
    [2, 3, 5, 6, 7, 10],
    [2, 3, 7, 8, 9, 10],
    [2, 4, 5, 6, 7, 8],
    [2, 4, 5, 7, 9, 10],
    [2, 5, 6, 8, 9, 10],
    [3, 4, 5, 6, 9, 10],
    [3, 4, 5, 7, 8, 10],
    [3, 5, 6, 7, 8, 9],
    [4, 6, 7, 8, 9, 10],
]

# ---------------------------------------------------------------------------
# System #89 — 11 numbers, 54 combinations
# Guarantee: TWO 4-wins if 4 of your numbers are drawn.
# Status: PENDING — combinations not yet entered.
#
# TODO: Transcribe the exact 54 combinations from:
#       Iliya Bluskov, "Combinatorial Lottery Systems (Wheels) with
#       Guaranteed Wins", System #89 (locate by system number in the
#       book's tables; page number varies by edition).
#
#       How to fill in:
#         1. Copy the combinations exactly as printed, using the generic
#            indices 1..11. Do not reorder, renumber, or "optimize" them.
#         2. Replace the empty list below with 54 lists of 6 integers.
#         3. Verify: len(DOUBLE_4IF4_11) == 54 and
#            validate_balance(DOUBLE_4IF4_11, pool_size=11) passes.
#
#       Do NOT use random or AI-generated combinations — the mathematical
#       guarantee will be invalid.
# ---------------------------------------------------------------------------
DOUBLE_4IF4_11: list[list[int]] = []  # TODO: 54 combinations, Bluskov System #89

# ---------------------------------------------------------------------------
# System #90 — 12 numbers, 72 combinations
# Guarantee: TWO 4-wins if 4 of your numbers are drawn.
# Status: PENDING — combinations not yet entered.
#
# TODO: Transcribe the exact 72 combinations from:
#       Iliya Bluskov, "Combinatorial Lottery Systems (Wheels) with
#       Guaranteed Wins", System #90 (locate by system number in the
#       book's tables; page number varies by edition).
#
#       How to fill in:
#         1. Copy the combinations exactly as printed, using the generic
#            indices 1..12. Do not reorder, renumber, or "optimize" them.
#         2. Replace the empty list below with 72 lists of 6 integers.
#         3. Verify: len(DOUBLE_4IF4_12) == 72 and
#            validate_balance(DOUBLE_4IF4_12, pool_size=12) passes.
#
#       Do NOT use random or AI-generated combinations — the mathematical
#       guarantee will be invalid.
# ---------------------------------------------------------------------------
DOUBLE_4IF4_12: list[list[int]] = []  # TODO: 72 combinations, Bluskov System #90

# ---------------------------------------------------------------------------
# System #107 — 12 numbers, 22 combinations
# Guarantee: TWO 3-wins if 3 of your numbers are drawn.
# Bonus:     Additional higher-tier wins possible (see book table).
# Status: PENDING — combinations not yet entered.
#
# TODO: Transcribe the exact 22 combinations from:
#       Iliya Bluskov, "Combinatorial Lottery Systems (Wheels) with
#       Guaranteed Wins", System #107 (locate by system number in the
#       book's tables; page number varies by edition).
#
#       How to fill in:
#         1. Copy the combinations exactly as printed, using the generic
#            indices 1..12. Do not reorder, renumber, or "optimize" them.
#         2. Replace the empty list below with 22 lists of 6 integers.
#         3. Verify: len(TRIPLE_4IF5_12) == 22 and
#            validate_balance(TRIPLE_4IF5_12, pool_size=12) passes.
#
#       Do NOT use random or AI-generated combinations — the mathematical
#       guarantee will be invalid.
# ---------------------------------------------------------------------------
TRIPLE_4IF5_12: list[list[int]] = []  # TODO: 22 combinations, Bluskov System #107

# ---------------------------------------------------------------------------
# System #119 — 12 numbers, 44 combinations
# Guarantee: SIX 4-wins if 5 of your numbers are drawn.
# Status: PENDING — combinations not yet entered.
#
# TODO: Transcribe the exact 44 combinations from:
#       Iliya Bluskov, "Combinatorial Lottery Systems (Wheels) with
#       Guaranteed Wins", System #119 (locate by system number in the
#       book's tables; page number varies by edition).
#
#       How to fill in:
#         1. Copy the combinations exactly as printed, using the generic
#            indices 1..12. Do not reorder, renumber, or "optimize" them.
#         2. Replace the empty list below with 44 lists of 6 integers.
#         3. Verify: len(SIX_4IF5_12) == 44 and
#            validate_balance(SIX_4IF5_12, pool_size=12) passes.
#
#       Do NOT use random or AI-generated combinations — the mathematical
#       guarantee will be invalid.
# ---------------------------------------------------------------------------
SIX_4IF5_12: list[list[int]] = []  # TODO: 44 combinations, Bluskov System #119

# ---------------------------------------------------------------------------
# Registry for easy lookup
# ---------------------------------------------------------------------------
WHEEL_REGISTRY: dict[str, dict[str, Any]] = {
    "double4_10": {
        "system_number": 88,
        "numbers": 10,
        "tickets": 30,
        "guarantee": "TWO 4-wins if 4 pool numbers hit",
        "wheel": DOUBLE_4IF4_10,
    },
    "double4_11": {
        "system_number": 89,
        "numbers": 11,
        "tickets": 54,
        "guarantee": "TWO 4-wins if 4 pool numbers hit",
        "wheel": DOUBLE_4IF4_11,
    },
    "double4_12": {
        "system_number": 90,
        "numbers": 12,
        "tickets": 72,
        "guarantee": "TWO 4-wins if 4 pool numbers hit",
        "wheel": DOUBLE_4IF4_12,
    },
    "triple4_12": {
        "system_number": 107,
        "numbers": 12,
        "tickets": 22,
        "guarantee": "TWO 3-wins if 3 pool numbers hit (main)",
        "wheel": TRIPLE_4IF5_12,
    },
    "six4_12": {
        "system_number": 119,
        "numbers": 12,
        "tickets": 44,
        "guarantee": "SIX 4-wins if 5 pool numbers hit",
        "wheel": SIX_4IF5_12,
    },
}

# ---------------------------------------------------------------------------
# WHEEL_EXPLORER — minimal system per (guarantee type, pool size)
# ---------------------------------------------------------------------------
# Maps each guarantee type to the system with the FEWEST tickets for each
# pool size, so the dashboard can auto-select the mathematically optimal
# wheel. Values are keys into WHEEL_REGISTRY.
#
# "4-if-4" and "5-if-5" (single-win) systems are not part of this library
# yet — add them to WHEEL_REGISTRY first, then register them here.
WHEEL_EXPLORER: dict[str, dict[int, str]] = {
    "4-if-4": {
        # No single-win 4-if-4 systems in this library yet.
    },
    "5-if-5": {
        # No 5-if-5 systems in this library yet.
    },
    "double-4-if-4": {
        10: "double4_10",  # System #88 — 30 tickets (verified)
        11: "double4_11",  # System #89 — 54 tickets (combinations pending)
        12: "double4_12",  # System #90 — 72 tickets (combinations pending)
    },
    "triple-4-if-5": {
        12: "triple4_12",  # System #107 — 22 tickets (combinations pending)
    },
    "six-4-if-5": {
        12: "six4_12",  # System #119 — 44 tickets (combinations pending)
    },
}


def get_optimal_wheel(guarantee_type: str, pool_size: int) -> dict[str, Any]:
    """
    Look up the minimal wheel for a guarantee type and pool size.

    Args:
        guarantee_type: A key of WHEEL_EXPLORER, e.g. "double-4-if-4".
        pool_size: Number of pool numbers, e.g. 12.

    Returns:
        A copy of the WHEEL_REGISTRY entry, plus:
          "key"   — the registry key, e.g. "double4_12"
          "ready" — True only if the combinations are actually filled in
                    (len(wheel) == tickets). Check this before generating
                    tickets so the dashboard can flag pending systems.

    Raises:
        KeyError: If no system covers that guarantee type / pool size.
    """
    try:
        key = WHEEL_EXPLORER[guarantee_type][pool_size]
    except KeyError:
        raise KeyError(
            f"No system registered for guarantee {guarantee_type!r} " f"with pool size {pool_size}."
        ) from None

    entry = dict(WHEEL_REGISTRY[key])
    entry["key"] = key
    entry["ready"] = len(entry["wheel"]) == entry["tickets"]
    return entry


def substitute_numbers(
    wheel: list[list[int]],
    user_numbers: list[int],
) -> list[list[int]]:
    """
    Map the generic 1..N wheel onto your chosen numbers.

    Args:
        wheel: A Bluskov system using generic indices 1..N.
        user_numbers: Your chosen numbers in the order you want them mapped.
                      Length must equal the wheel's number pool size.

    Returns:
        List of tickets with your actual numbers substituted in.

    Example:
        >>> wheel = DOUBLE_4IF4_10
        >>> my_nums = [3, 7, 12, 14, 18, 22, 29, 33, 40, 46]
        >>> tickets = substitute_numbers(wheel, my_nums)
    """
    if not wheel:
        raise ValueError("Wheel is empty. Have you filled in the combinations?")

    pool_size = max(max(ticket) for ticket in wheel)
    if len(user_numbers) != pool_size:
        raise ValueError(f"Wheel requires {pool_size} numbers, but {len(user_numbers)} provided.")

    # Map 1-indexed wheel positions to 0-indexed user_numbers
    return [[user_numbers[pos - 1] for pos in ticket] for ticket in wheel]


def validate_balance(
    wheel: list[list[int]],
    pool_size: int,
    verbose: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """
    Sanity-check a wheel's balance properties (number frequency, pair coverage).

    Args:
        wheel: The wheel combinations.
        pool_size: The total numbers in the pool (e.g., 10 for System #88).
        verbose: Print detailed stats.

    Returns:
        (is_valid, stats_dict)
    """
    from itertools import combinations

    if not wheel:
        return False, {"error": "Wheel is empty"}

    ticket_len = len(wheel[0])
    total_pairs = pool_size * (pool_size - 1) // 2
    pair_counter: Counter[tuple[int, int]] = Counter()
    num_counter: Counter[int] = Counter()

    for ticket in wheel:
        num_counter.update(ticket)
        pair_counter.update(combinations(sorted(ticket), 2))

    # Check every number 1..pool_size appears at least once
    missing = [i for i in range(1, pool_size + 1) if i not in num_counter]
    if missing:
        return False, {"error": f"Missing numbers: {missing}"}

    stats = {
        "tickets": len(wheel),
        "pool_size": pool_size,
        "ticket_length": ticket_len,
        "number_freq": dict(num_counter),
        "pair_freq": dict(pair_counter),
        "total_pairs_covered": len(pair_counter),
        "total_possible_pairs": total_pairs,
        "pair_coverage_pct": round(len(pair_counter) / total_pairs * 100, 2),
    }

    if verbose:
        print(f"Tickets: {stats['tickets']}")
        print(f"Pool size: {stats['pool_size']}")
        print(f"Number frequencies: {stats['number_freq']}")
        print(f"Unique pairs covered: {stats['total_pairs_covered']} / {total_pairs}")
        print(f"Pair coverage: {stats['pair_coverage_pct']}%")

    return True, stats


# ---------------------------------------------------------------------------
# Self-test / demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Validate the verified System #88
    valid, stats = validate_balance(DOUBLE_4IF4_10, pool_size=10, verbose=True)
    print(f"\nSystem #88 valid: {valid}")

    # Demo substitution
    my_numbers = [3, 7, 12, 14, 18, 22, 29, 33, 40, 46]
    my_tickets = substitute_numbers(DOUBLE_4IF4_10, my_numbers)
    print("\nFirst 3 tickets with your numbers:")
    for t in my_tickets[:3]:
        print(f"  {t}")

    # WHEEL_EXPLORER demo: minimal system per guarantee type / pool size
    print("\nWHEEL_EXPLORER:")
    for gtype, sizes in WHEEL_EXPLORER.items():
        if not sizes:
            print(f"  {gtype}: (no systems in library yet)")
            continue
        for size in sorted(sizes):
            entry = get_optimal_wheel(gtype, size)
            status = "ready" if entry["ready"] else "PENDING combinations"
            print(
                f"  {gtype} / {size} numbers -> "
                f"System #{entry['system_number']} "
                f"({entry['tickets']} tickets) [{status}]"
            )
