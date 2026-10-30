#!/usr/bin/env python3
"""
compare_guarantees.py

Generate abbreviated wheels for multiple guarantee levels using the SAME
number pool, then print a cost/guarantee trade-off table. Each wheel is
saved to a file for immediate backtesting.

Usage:
    python compare_guarantees.py --pool-size 10 --strategy hot
    python compare_guarantees.py --numbers 3,7,12,18,22,29,34,36 --verify
    python compare_guarantees.py --pool-size 12 --guarantees "4 if 4,4 if 5,5 if 6"
"""

import argparse
import itertools
import random
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

DB_PATH = Path.cwd() / "data" / "lotto.db"
COST_PER_LINE = 0.70
TICKET_SIZE = 6
LOTTO_MIN, LOTTO_MAX = 1, 40


# ── Pool helpers ────────────────────────────────────────────────────────
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


def generate_pool(
    pool_size: int, strategy: str, include: list[int], exclude: list[int]
) -> list[int]:
    available = [n for n in range(LOTTO_MIN, LOTTO_MAX + 1) if n not in exclude]
    include = [n for n in include if n in available]
    if len(include) > pool_size:
        raise ValueError("Too many included numbers for pool size")
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
        # Interleave from start/middle/end for spread
        sources = [remaining, remaining[::-1], remaining[::2], remaining[1::2]]
        idx = 0
        while len(pool) < pool_size and idx < 1000:
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


# ── Guarantee parsing ───────────────────────────────────────────────────
def parse_guarantee(g: str) -> tuple[int, int]:
    g = g.lower().replace("if", " ").replace("-", " ")
    parts = g.split()
    if len(parts) != 2:
        raise ValueError(f"Invalid guarantee '{g}'. Use format 'X if Y'")
    return int(parts[0]), int(parts[1])


# ── Greedy set cover (silent version) ───────────────────────────────────
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
    pool: list[int], guarantee: int, trigger_size: int, verbose: bool = False
) -> list[tuple[int, ...]]:
    triggers = list(itertools.combinations(pool, trigger_size))
    all_tickets = list(itertools.combinations(pool, TICKET_SIZE))

    if verbose:
        print(
            f"    Pool: {len(pool)} numbers | Triggers: {len(triggers):,} | Candidates: {len(all_tickets):,}"
        )

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
            print(f"    WARNING: Could not cover {len(uncovered)} remaining triggers.")
            break

        selected.append(best_ticket)
        uncovered -= best_cover

    return selected


# ── Verification ────────────────────────────────────────────────────────
def verify_wheel(
    tickets: list[tuple[int, ...]],
    pool: list[int],
    guarantee: int,
    trigger_size: int,
    sims: int = 3000,
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


# ── Main comparison ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Compare abbreviated wheel guarantees for the same pool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --pool-size 10 --strategy hot
  %(prog)s --numbers 5,10,15,20,25,30,35,40 --guarantees "4 if 4,4 if 5"
  %(prog)s --pool-size 12 --guarantees "3 if 3,4 if 4,4 if 5,5 if 6" --verify
        """,
    )
    parser.add_argument("--pool-size", type=int, default=10, help="Pool size (6–20)")
    parser.add_argument(
        "--numbers", type=str, help="Comma-separated exact pool (overrides --pool-size)"
    )
    parser.add_argument(
        "--strategy", type=str, default="random", choices=["random", "hot", "cold", "balanced"]
    )
    parser.add_argument("--include", type=str, help="Comma-separated must-include numbers")
    parser.add_argument("--exclude", type=str, help="Comma-separated excluded numbers")
    parser.add_argument("--seed", type=int, help="Random seed for reproducible pools")
    parser.add_argument("--powerball", type=int, help="Fixed Powerball number")
    parser.add_argument(
        "--guarantees",
        type=str,
        default="3 if 3,4 if 4,4 if 5,5 if 6",
        help="Comma-separated guarantees to compare",
    )
    parser.add_argument("--verify", action="store_true", help="Run Monte-Carlo verification")
    parser.add_argument("--output-dir", type=str, default=".", help="Directory to save wheel files")

    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    include = [int(x.strip()) for x in args.include.split(",")] if args.include else []
    exclude = [int(x.strip()) for x in args.exclude.split(",")] if args.exclude else []

    if args.numbers:
        pool = sorted({int(x.strip()) for x in args.numbers.split(",")})
        if len(pool) < TICKET_SIZE:
            print("Error: Pool needs at least 6 numbers.")
            sys.exit(1)
    else:
        if args.pool_size < TICKET_SIZE or args.pool_size > 20:
            print("Error: --pool-size must be 6–20.")
            sys.exit(1)
        pool = generate_pool(args.pool_size, args.strategy, include, exclude)

    guarantees = [g.strip() for g in args.guarantees.split(",")]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(exist_ok=True)

    results = []

    print(f"\n{'='*80}")
    print(f"  COMPARING GUARANTEES FOR POOL: {pool}")
    print(f"{'='*80}\n")

    for g_str in guarantees:
        try:
            g_match, g_trig = parse_guarantee(g_str)
        except ValueError as e:
            print(f"  Skipping invalid guarantee '{g_str}': {e}\n")
            continue

        print(f"▶ Generating: {g_match} if {g_trig}")
        start = time.time()
        tickets = greedy_set_cover(pool, g_match, g_trig, verbose=True)
        elapsed = time.time() - start

        full_count = len(list(itertools.combinations(pool, TICKET_SIZE)))
        reduction = (len(tickets) / full_count * 100) if full_count else 0
        cost = len(tickets) * COST_PER_LINE

        # Verification
        ver_pass, ver_ratio, ver_worst = False, 0.0, 0
        if args.verify:
            print("  Verifying (3,000 simulations)...")
            ver_pass, ver_ratio, ver_worst = verify_wheel(tickets, pool, g_match, g_trig)

        results.append(
            {
                "guarantee": f"{g_match} if {g_trig}",
                "tickets": len(tickets),
                "full": full_count,
                "reduction": reduction,
                "cost": cost,
                "time": elapsed,
                "verified": ver_pass,
                "coverage": ver_ratio,
                "worst": ver_worst,
            }
        )

        # Save wheel file
        safe_name = f"wheel_abbrev_{g_match}if{g_trig}_pool{len(pool)}.txt"
        filepath = out_dir / safe_name
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Abbreviated Wheel: {g_match} if {g_trig}\n")
            f.write(f"Pool ({len(pool)} numbers): {pool}\n")
            f.write(f"Tickets: {len(tickets)}  (full wheel: {full_count})\n")
            f.write(f"Reduction: {reduction:.1f}% of full wheel\n")
            f.write(f"Cost per draw: ${cost:.2f}\n")
            if args.powerball:
                f.write(f"Powerball: {args.powerball}\n")
            f.write("-" * 45 + "\n")
            for i, t in enumerate(tickets, 1):
                nums = " ".join(f"{n:2d}" for n in t)
                pb = f"  PB:{args.powerball}" if args.powerball else ""
                f.write(f"Ticket {i:3d}: {nums}{pb}\n")
        print(f"  Saved: {filepath}\n")

    # ── Summary table ───────────────────────────────────────────────────
    print(f"{'='*95}")
    print(
        f"{'Guarantee':<12} {'Tickets':>8} {'Full':>8} {'Reduction':>10} {'Cost':>8} {'Time':>7} {'Verify':>8}"
    )
    print(f"{'-'*95}")
    for r in results:
        v_str = "PASS" if r["verified"] else ("—" if not args.verify else "FAIL")
        print(
            f"{r['guarantee']:<12} {r['tickets']:>8} {r['full']:>8} {r['reduction']:>9.1f}% ${r['cost']:>7.2f} {r['time']:>6.1f}s {v_str:>8}"
        )
    print(f"{'='*95}")

    print("\n📊 How to read this:")
    print("   • Reduction = how much cheaper than a full wheel (C(pool,6)).")
    print("   • '3 if 3' is cheap (~$2–$5) but only guarantees a bonus ticket.")
    print("   • '4 if 4' is the sweet spot: small cost, solid guarantee.")
    print("   • '5 if 6' is expensive and the trigger (all 6 in pool) is rare.")

    print("\n🎲 Backtest all generated wheels:")
    print("   python compare_wheels.py")
    print("   python refined_backtest.py")


if __name__ == "__main__":
    main()
