#!/usr/bin/env python3
"""
ga_optimizer.py — Genetic Algorithm for optimising wheel generation parameters.

Evolves a population of parameter sets (pool_size, positive_ratio, max_overlap,
require_attraction, include_bonus_coverage) to maximise the expected value
of the generated wheel, computed via simulate_bonus_ev() from backtest.py.

Each individual is a dict:
  {
    "pool_size": int 8-20,
    "positive_ratio": float 0.4-0.8,
    "max_overlap": int 1-4,
    "require_attraction": bool,
    "include_bonus_coverage": bool,
  }

Fitness = EV with bonus (simulate_bonus_ev, 50k sims for speed).
"""

from __future__ import annotations

import math
import random
import sqlite3
from copy import deepcopy
from typing import Any


class WheelOptimizerGA:
    """Genetic Algorithm for wheel parameter optimisation.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open connection to lotto.db.
    population_size : int
        Number of individuals per generation (default 50).
    generations : int
        Number of generations to evolve (default 30).
    quick : bool
        Quick Mode (faster, less optimal): use 5,000 Monte Carlo
        simulations per fitness evaluation instead of 50,000.
    """

    FULL_SIMS = 50_000
    QUICK_SIMS = 5_000

    def __init__(
        self,
        conn: sqlite3.Connection,
        population_size: int = 50,
        generations: int = 30,
        quick: bool = False,
    ):
        self.conn = conn
        self.pop_size = population_size
        self.generations = generations
        self.quick = quick
        self.num_sims = self.QUICK_SIMS if quick else self.FULL_SIMS
        self.population: list[dict[str, Any]] = []
        self.best_individual: dict[str, Any] | None = None
        self.best_fitness: float = -float("inf")
        self.history: list[dict[str, Any]] = []  # generation stats

    # ------------------------------------------------------------------
    def _random_individual(self) -> dict[str, Any]:
        """Generate a random parameter set."""
        return {
            "pool_size": random.randint(8, 20),
            "positive_ratio": round(random.uniform(0.4, 0.8), 2),
            "max_overlap": random.randint(1, 4),
            "require_attraction": random.choice([True, False]),
            "include_bonus_coverage": random.choice([True, False]),
        }

    def _mutate(self, ind: dict[str, Any]) -> dict[str, Any]:
        """Mutate an individual with small perturbations."""
        mutant = deepcopy(ind)
        if random.random() < 0.3:
            mutant["pool_size"] = max(
                8, min(20, mutant["pool_size"] + random.choice([-2, -1, 1, 2]))
            )
        if random.random() < 0.3:
            mutant["positive_ratio"] = round(
                max(0.4, min(0.8, mutant["positive_ratio"] + random.uniform(-0.1, 0.1))), 2
            )
        if random.random() < 0.3:
            mutant["max_overlap"] = max(1, min(4, mutant["max_overlap"] + random.choice([-1, 1])))
        if random.random() < 0.2:
            mutant["require_attraction"] = not mutant["require_attraction"]
        if random.random() < 0.2:
            mutant["include_bonus_coverage"] = not mutant["include_bonus_coverage"]
        return mutant

    def _crossover(self, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        """Uniform crossover between two parents."""
        child: dict[str, Any] = {}
        for key in a:
            child[key] = a[key] if random.random() < 0.5 else b[key]
        return child

    # ------------------------------------------------------------------
    def _build_wheel(self, ind: dict[str, Any]) -> list[tuple[int, ...]]:
        """Generate a wheel from parameter set using Albert-optimised pool."""
        from albert_analysis import get_recommended_pool
        from wheel_generator import generate_abbreviated_wheel

        pool = get_recommended_pool(
            self.conn,
            window_draws=20,
            target_pool_size=ind["pool_size"],
        )
        if not pool or len(pool) < 6:
            return []

        tickets, _ = generate_abbreviated_wheel(
            pool,
            guarantee="4 if 4",
            max_tickets=min(200, math.comb(len(pool), 6)),
            max_bonus_coverage=ind.get("include_bonus_coverage", False),
            verbose=False,
        )
        return tickets

    # ------------------------------------------------------------------
    def _fitness(self, ind: dict[str, Any]) -> float:
        """Compute fitness = EV with bonus via simulate_bonus_ev."""
        tickets = self._build_wheel(ind)
        if not tickets:
            return 0.0

        from backtest import simulate_bonus_ev

        result = simulate_bonus_ev(tickets, num_sims=self.num_sims)
        return float(result["ev_with_bonus"])

    # ------------------------------------------------------------------
    def _tournament_select(self, fitnesses: list[float], k: int = 3) -> int:
        """Tournament selection: pick k random, return index of best."""
        candidates = random.sample(range(len(self.population)), k=min(k, len(self.population)))
        return max(candidates, key=lambda i: fitnesses[i])

    # ------------------------------------------------------------------
    def evolve(self) -> dict[str, Any]:
        """Run the GA and return the best individual + fitness + history.

        Returns
        -------
        dict
            Keys: best_individual, best_fitness, history (list of per-gen stats).
        """
        # Initialise population
        self.population = [self._random_individual() for _ in range(self.pop_size)]
        self.best_individual = None
        self.best_fitness = -float("inf")
        self.history = []

        for gen in range(self.generations):
            # Evaluate fitness
            fitnesses = []
            for ind in self.population:
                fit = self._fitness(ind)
                fitnesses.append(fit)
                if fit > self.best_fitness:
                    self.best_fitness = fit
                    self.best_individual = deepcopy(ind)

            # Record stats
            avg_fit = sum(fitnesses) / len(fitnesses) if fitnesses else 0.0
            self.history.append(
                {
                    "generation": gen + 1,
                    "best_fitness": round(self.best_fitness, 4),
                    "avg_fitness": round(avg_fit, 4),
                    "max_fitness": round(max(fitnesses), 4),
                }
            )

            # Elitism: keep top 2
            ranked = sorted(range(len(fitnesses)), key=lambda i: -fitnesses[i])
            elites = [deepcopy(self.population[i]) for i in ranked[:2]]

            # Create next generation
            next_gen = elites[:]
            while len(next_gen) < self.pop_size:
                p1_idx = self._tournament_select(fitnesses)
                p2_idx = self._tournament_select(fitnesses)
                child = self._crossover(self.population[p1_idx], self.population[p2_idx])
                child = self._mutate(child)
                next_gen.append(child)

            self.population = next_gen

        return {
            "best_individual": self.best_individual,
            "best_fitness": round(self.best_fitness, 4),
            "history": self.history,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Genetic algorithm wheel-parameter optimisation.")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick Mode (faster, less optimal): 5,000 simulations per "
        "fitness evaluation instead of 50,000.",
    )
    parser.add_argument("--population", type=int, default=30)
    parser.add_argument("--generations", type=int, default=10)
    args = parser.parse_args()

    conn = sqlite3.connect("lotto.db")
    try:
        ga = WheelOptimizerGA(
            conn,
            population_size=args.population,
            generations=args.generations,
            quick=args.quick,
        )
        result = ga.evolve()
    finally:
        conn.close()

    mode = "Quick Mode (5,000 sims)" if args.quick else "Full Mode (50,000 sims)"
    print(f"\n{mode}")
    print(f"Best fitness (EV): ${result['best_fitness']:.4f}")
    print(f"Best parameters: {result['best_individual']}")
