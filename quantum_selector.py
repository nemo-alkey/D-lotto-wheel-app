#!/usr/bin/env python3
"""
quantum_selector.py — quantum annealing-inspired wheel optimizer.

IMPORTANT: this is *simulated* quantum annealing (SQA) running on classical
hardware — no real quantum computer is involved. It borrows the control
schedule of quantum annealing: a transverse field Gamma(t) that starts
strong and decays toward zero. While Gamma is large, the system can
"tunnel" through energy barriers (multi-number quantum jumps); as Gamma
decays it behaves like classical simulated annealing and settles into a
local minimum.

References
----------
  - Kadowaki & Nishimori, "Quantum annealing in the transverse Ising
    model", Phys. Rev. E 58, 5355 (1998).
  - Farhi et al., "Quantum computation by adiabatic evolution",
    arXiv:quant-ph/0001106 (2000).
  - Santoro et al., "Theory of quantum annealing of an Ising spin glass",
    Science 295, 2427 (2002).
  - Johnson et al., "Quantum annealing with manufactured spins",
    Nature 473, 194 (2011) — D-Wave hardware.

Energy model (minimised)
------------------------
    E(x) = -(coverage_score(x) + w_att * attraction_alignment(x))
           + lambda * (block_violations(x) + sum_violations(x))

  - coverage_score: fraction of all C(pool,2) pairs covered by the wheel
    (Bluskov-like pair balance).
  - attraction_alignment: weighted share of in-ticket pairs that are hot
    consecutive/+2 pairs (from numerical_attraction-style profile).
  - block_violations: per-ticket deviation from block_targeting's
    min_per_block constraints (too few OR too many from a block).
  - sum_violations: fractional distance outside sum_validator's dynamic
    sum range.

Update rule
-----------
  - Classical move: Metropolis spin flip — swap one number in one ticket;
    accept with prob min(1, exp(-dE / Gamma(t))).
  - Quantum jump: with probability proportional to Gamma(t)/Gamma(0),
    replace 2-3 numbers in a ticket simultaneously (tunnelling event),
    accepted by the same Metropolis criterion.
  - Gamma(t) = initial_gamma * cooling_rate**t.

Usage:
    from quantum_selector import quantum_anneal_wheel
    tickets = quantum_anneal_wheel(num_tickets=10, iterations=10000)
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from datetime import datetime
from itertools import combinations
from pathlib import Path

logger = logging.getLogger(__name__)

BENCHMARK_PATH = Path(__file__).parent / "data" / "benchmarks" / "quantum_vs_ga.json"

#: Default weight of the attraction-alignment bonus relative to coverage.
ATTRACTION_WEIGHT = 0.5


# ---------------------------------------------------------------------------
# Constraint/profile helpers
# ---------------------------------------------------------------------------


def build_attraction_profile(
    draws: list[list[int]], last_n: int = 30
) -> dict[tuple[int, int], float]:
    """Hot consecutive/+2 pair profile from recent draws.

    Counts pairs with gap 1-2 inside each draw over the last ``last_n``
    draws and normalises counts to weights in (0, 1]. This is the pair-level
    companion of lotto_wheels.numerical_attraction (which returns only the
    scalar probability that a draw contains such a pair).
    """
    recent = draws[-last_n:] if len(draws) > last_n else draws
    counts: dict[tuple[int, int], int] = {}
    for draw in recent:
        nums = sorted(draw)
        for a, b in combinations(nums, 2):
            if 1 <= b - a <= 2:
                counts[(a, b)] = counts.get((a, b), 0) + 1
    if not counts:
        return {}
    peak = max(counts.values())
    return {pair: c / peak for pair, c in counts.items()}


# ---------------------------------------------------------------------------
# Energy components
# ---------------------------------------------------------------------------


def _wheel_pair_coverage(tickets: list[list[int]], pool_size: int) -> float:
    """Fraction of all C(pool_size, 2) pairs covered by at least one ticket."""
    covered = set()
    for t in tickets:
        covered.update(combinations(sorted(t), 2))
    total = math.comb(pool_size, 2)
    return len(covered) / total if total else 0.0


def _attraction_alignment(tickets: list[list[int]], profile: dict[tuple[int, int], float]) -> float:
    """Weighted share of in-ticket pairs present in the attraction profile."""
    if not profile:
        return 0.0
    score = 0.0
    total = 0
    for t in tickets:
        for pair in combinations(sorted(t), 2):
            total += 1
            score += profile.get(pair, 0.0)
    return score / total if total else 0.0


def _block_violations(
    tickets: list[list[int]],
    blocks: dict[int, tuple[int, int]],
    min_per_block: dict[int, int],
) -> float:
    """Average per-ticket count of block-constraint violations.

    A ticket violates a block when it has fewer than min_per_block[b] or
    more than min_per_block[b] + 2 numbers from that block.
    """
    violations = 0.0
    for t in tickets:
        for b, (lo, hi) in blocks.items():
            c = sum(1 for n in t if lo <= n <= hi)
            minimum = min_per_block.get(b, 0)
            violations += max(0, minimum - c) + max(0, c - (minimum + 2))
    return violations / len(tickets) if tickets else 0.0


def _sum_violations(tickets: list[list[int]], sum_range: tuple[int, int]) -> float:
    """Average per-ticket fractional distance outside the dynamic sum range."""
    lo, hi = sum_range
    violations = 0.0
    for t in tickets:
        s = sum(t)
        if s < lo:
            violations += (lo - s) / lo
        elif s > hi:
            violations += (s - hi) / hi
    return violations / len(tickets) if tickets else 0.0


def wheel_energy(
    tickets: list[list[int]],
    pool_size: int = 40,
    attraction_profile: dict[tuple[int, int], float] | None = None,
    block_constraints: dict | None = None,
    sum_range: tuple[int, int] | None = None,
    lambda_penalty: float = 1.0,
    attraction_weight: float = ATTRACTION_WEIGHT,
) -> float:
    """Total energy of a wheel (lower is better). See module docstring."""
    score = _wheel_pair_coverage(tickets, pool_size)
    if attraction_profile:
        score += attraction_weight * _attraction_alignment(tickets, attraction_profile)

    penalty = 0.0
    if block_constraints:
        from block_targeting import BLOCKS

        blocks = {b: cfg["range"] for b, cfg in BLOCKS.items()}
        penalty += _block_violations(tickets, blocks, block_constraints.get("min_per_block", {}))
    if sum_range:
        penalty += _sum_violations(tickets, sum_range)

    return -score + lambda_penalty * penalty


# ---------------------------------------------------------------------------
# Simulated quantum annealing
# ---------------------------------------------------------------------------


def quantum_anneal_wheel(
    pool_size: int = 40,
    ticket_size: int = 6,
    num_tickets: int = 10,
    iterations: int = 10000,
    initial_gamma: float = 2.0,
    cooling_rate: float = 0.9995,
    lambda_penalty: float = 1.0,
    attraction_profile: dict[tuple[int, int], float] | None = None,
    block_constraints: dict | None = None,
    sum_range: tuple[int, int] | None = None,
    attraction_weight: float = ATTRACTION_WEIGHT,
    seed: int | None = None,
) -> list[list[int]]:
    """Optimise a wheel via simulated quantum annealing.

    Args:
        pool_size: Numbers are drawn from 1..pool_size (default 40).
        ticket_size: Numbers per ticket (default 6).
        num_tickets: Tickets in the wheel (default 10).
        iterations: Annealing steps (default 10 000).
        initial_gamma: Initial transverse field strength (default 2.0).
        cooling_rate: Per-step Gamma decay (default 0.9995).
        lambda_penalty: Weight of constraint violations in the energy.
        attraction_profile: {(a, b): weight} from build_attraction_profile().
        block_constraints: Output of block_targeting.generate_block_constraints().
        sum_range: (min_sum, max_sum) from sum_validator.calculate_dynamic_sum_range().
        attraction_weight: Weight of the attraction bonus vs coverage.
        seed: RNG seed for reproducibility.

    Returns:
        The best wheel found, as a list of sorted ticket lists.
    """
    rng = random.Random(seed)
    pool = list(range(1, pool_size + 1))

    # Random initial state
    tickets = [sorted(rng.sample(pool, ticket_size)) for _ in range(num_tickets)]

    def energy(state: list[list[int]]) -> float:
        return wheel_energy(
            state,
            pool_size,
            attraction_profile,
            block_constraints,
            sum_range,
            lambda_penalty,
            attraction_weight,
        )

    current = [list(t) for t in tickets]
    current_e = energy(current)
    best = [list(t) for t in current]
    best_e = current_e

    gamma = initial_gamma
    for _step in range(iterations):
        # --- Choose a move: quantum jump vs classical spin flip ---
        # Tunnelling probability decays with the transverse field.
        jump_prob = 0.3 * (gamma / initial_gamma) if initial_gamma else 0.0
        candidate = [list(t) for t in current]
        t_idx = rng.randrange(num_tickets)
        ticket = candidate[t_idx]

        if rng.random() < jump_prob:
            # Quantum jump: replace 2-3 numbers simultaneously
            k = rng.randint(2, min(3, ticket_size))
            available = [n for n in pool if n not in ticket]
            if len(available) >= k:
                drop = set(rng.sample(ticket, k))
                ticket = sorted(n for n in ticket if n not in drop)
                ticket = sorted(ticket + rng.sample(available, k))
        else:
            # Classical Metropolis spin flip: swap one number
            available = [n for n in pool if n not in ticket]
            if available:
                ticket = list(ticket)
                ticket[rng.randrange(ticket_size)] = rng.choice(available)
                ticket = sorted(ticket)
        candidate[t_idx] = ticket

        cand_e = energy(candidate)
        d_e = cand_e - current_e

        # --- Metropolis criterion against the transverse field ---
        if d_e <= 0 or rng.random() < math.exp(-d_e / max(gamma, 1e-9)):
            current = candidate
            current_e = cand_e
            if cand_e < best_e:
                best = [list(t) for t in candidate]
                best_e = cand_e

        gamma *= cooling_rate

    logger.info(
        "SQA finished: %d steps, best energy %.4f (initial %.4f)",
        iterations,
        best_e,
        energy([sorted(rng.sample(pool, ticket_size)) for _ in range(num_tickets)]),
    )
    return sorted(best)


# ---------------------------------------------------------------------------
# Benchmark: quantum annealer vs existing GA optimizer
# ---------------------------------------------------------------------------


def benchmark_quantum_vs_ga(
    iterations: int = 5000,
    num_tickets: int = 10,
    ga_population: int = 10,
    ga_generations: int = 5,
    db_path: str = "lotto.db",
    out_path: Path | str = BENCHMARK_PATH,
    seed: int | None = None,
) -> dict:
    """Run quantum_anneal_wheel and WheelOptimizerGA on shared constraints.

    Both wheels are scored with the SAME energy model (pair coverage,
    attraction alignment, block and sum penalties) so the comparison is
    apples-to-apples. The GA additionally reports its own EV fitness.

    Constraints (attraction profile, block constraints, sum range) are
    derived from the draw history when the database has enough draws;
    otherwise the run proceeds unconstrained.

    Results are appended to data/benchmarks/quantum_vs_ga.json and also
    returned as a dict.
    """
    import sqlite3

    # --- Shared constraints from draw history ---
    attraction_profile = None
    block_constraints = None
    sum_range = None
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT numbers FROM draws ORDER BY draw_date").fetchall()
        draws = [[int(x) for x in str(r[0]).replace(",", " ").split()] for r in rows]
        if len(draws) >= 10:
            from block_targeting import analyze_block_distribution, generate_block_constraints
            from sum_validator import calculate_dynamic_sum_range

            attraction_profile = build_attraction_profile(draws)
            block_constraints = generate_block_constraints(analyze_block_distribution(draws))
            sum_range = calculate_dynamic_sum_range(draws)
    finally:
        conn.close()

    constraints = {
        "attraction_pairs": len(attraction_profile or {}),
        "block_constraints": bool(block_constraints),
        "sum_range": list(sum_range) if sum_range else None,
    }

    # --- Quantum run ---
    t0 = time.perf_counter()
    q_wheel = quantum_anneal_wheel(
        num_tickets=num_tickets,
        iterations=iterations,
        attraction_profile=attraction_profile,
        block_constraints=block_constraints,
        sum_range=sum_range,
        seed=seed,
    )
    q_time = time.perf_counter() - t0
    q_energy = wheel_energy(q_wheel, 40, attraction_profile, block_constraints, sum_range)

    # --- GA run (existing optimizer; EV-fitness, its own wheel builder) ---
    ga_result: dict = {"error": None}
    ga_wheel: list[list[int]] = []
    ga_time = 0.0
    conn = sqlite3.connect(db_path)
    try:
        from ga_optimizer import WheelOptimizerGA

        ga = WheelOptimizerGA(
            conn,
            population_size=ga_population,
            generations=ga_generations,
            quick=True,
        )
        t0 = time.perf_counter()
        evolution = ga.evolve()
        ga_time = time.perf_counter() - t0
        if ga.best_individual:
            ga_wheel = [sorted(t) for t in ga._build_wheel(ga.best_individual)]
        ga_result = {
            "best_individual": evolution["best_individual"],
            "best_ev_fitness": evolution["best_fitness"],
        }
    except Exception as exc:  # GA needs enough draw history for its pool
        ga_result = {"error": str(exc)}
    finally:
        conn.close()

    ga_energy = (
        wheel_energy(ga_wheel, 40, attraction_profile, block_constraints, sum_range)
        if ga_wheel
        else None
    )

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "settings": {
            "iterations": iterations,
            "num_tickets": num_tickets,
            "ga_population": ga_population,
            "ga_generations": ga_generations,
        },
        "constraints": constraints,
        "quantum": {
            "tickets": len(q_wheel),
            "execution_time_s": round(q_time, 3),
            "best_energy": round(q_energy, 4),
            "pair_coverage_pct": round(_wheel_pair_coverage(q_wheel, 40) * 100, 1),
        },
        "ga": {
            **ga_result,
            "tickets": len(ga_wheel),
            "execution_time_s": round(ga_time, 3),
            "best_energy": round(ga_energy, 4) if ga_energy is not None else None,
            "pair_coverage_pct": (
                round(_wheel_pair_coverage(ga_wheel, 40) * 100, 1) if ga_wheel else None
            ),
        },
    }

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if out.exists():
        try:
            history = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    history.append(report)
    out.write_text(json.dumps(history, indent=2), encoding="utf-8")
    logger.info("Benchmark written to %s", out)
    return report


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    rng = random.Random(3)

    # --- Basic validity ---
    wheel = quantum_anneal_wheel(num_tickets=8, iterations=3000, seed=3)
    assert len(wheel) == 8
    for t in wheel:
        assert len(t) == 6 and len(set(t)) == 6
        assert all(1 <= n <= 40 for n in t)
    print(f"Wheel (8 tickets): {wheel}")

    # --- Coverage beats a random baseline ---
    cov_sqa = _wheel_pair_coverage(wheel, 40)
    random_wheels = [[sorted(rng.sample(range(1, 41), 6)) for _ in range(8)] for _ in range(20)]
    cov_rand = max(_wheel_pair_coverage(w, 40) for w in random_wheels)
    print(f"Pair coverage: SQA {cov_sqa:.3f} vs best-of-20-random {cov_rand:.3f}")
    assert cov_sqa >= cov_rand

    # --- Energy decreases vs a random start ---
    e_rand = min(wheel_energy(w) for w in random_wheels)
    e_sqa = wheel_energy(wheel)
    print(f"Energy: SQA {e_sqa:.4f} vs best random {e_rand:.4f}")
    assert e_sqa <= e_rand

    # --- Constraints are respected ---
    profile = {(i, i + 1): 1.0 for i in range(10, 20)}  # hot strip 10-20
    constrained = quantum_anneal_wheel(
        num_tickets=6,
        iterations=3000,
        seed=5,
        attraction_profile=profile,
        sum_range=(100, 160),
        lambda_penalty=2.0,
    )
    in_range = sum(1 for t in constrained if 100 <= sum(t) <= 160)
    align = _attraction_alignment(constrained, profile)
    print(f"\nConstrained wheel: {constrained}")
    print(f"Tickets in sum range 100-160: {in_range}/6, " f"attraction alignment: {align:.3f}")
    assert in_range >= 4, "most tickets should land inside the sum range"

    # --- Benchmark smoke test (GA may fail on tiny DBs; that's handled) ---
    report = benchmark_quantum_vs_ga(
        iterations=1500,
        num_tickets=6,
        ga_population=4,
        ga_generations=2,
        seed=3,
    )
    print(
        f"\nBenchmark: quantum energy {report['quantum']['best_energy']}, "
        f"GA energy {report['ga']['best_energy']} "
        f"(GA error: {report['ga'].get('error')})"
    )
    assert BENCHMARK_PATH.exists()
    assert report["quantum"]["tickets"] == 6

    print("\nAll quantum_selector self-tests passed.")
