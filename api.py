#!/usr/bin/env python3
"""
FastAPI server for NZ Lotto Powerball wheel analysis.
Reuses existing functions from lotto_wheels.py.

Start with:  uvicorn api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import sqlite3

from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from auth import (
    UserRegister, UserLogin, Token,
    register_user, authenticate_user,
    get_current_user, require_user, require_admin, User,
)

from lotto_wheels import (
    WHEELS,
    DIVISIONS,
    load_draws,
    get_bonus_stats,
    positive_negative_split,
    block_analysis,
    sum_range,
    numerical_attraction,
    bayesian_posterior,
    bandit_recommendation,
)


# ---------------------------------------------------------------------------
# Lifespan — load draws once at startup
# ---------------------------------------------------------------------------

_draws: list | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _draws
    _draws = load_draws()
    yield
    _draws = None


# --- Rate Limiter ---

try:
    from settings import settings
    _default_limit = settings.api_rate_limit
    _heavy_limit = settings.heavy_rate_limit
    _ticket_cost = settings.ticket_cost
except ImportError:
    _default_limit = "60/minute"
    _heavy_limit = "5/minute"
    _ticket_cost = 1.50

limiter = Limiter(key_func=get_remote_address, default_limits=[_default_limit])

app = FastAPI(title="NZ Lotto Powerball API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class CheckRequest(BaseModel):
    wheel: str = Field(description="Wheel name (e.g. double, single1, jackpot7)")
    draw: list[int] = Field(min_length=6, max_length=6, description="6 main draw numbers")
    powerball: int = Field(ge=1, le=10, description="Powerball (1-10)")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"status": "ok", "message": "NZ Lotto Powerball API"}


@app.post("/register", status_code=201)
def register(req: UserRegister):
    """Register a new user."""
    ok = register_user(req.username, req.password)
    if not ok:
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"message": "User registered successfully"}


@app.post("/token", response_model=Token)
def login(req: UserLogin):
    """Login and receive a JWT access token."""
    token = authenticate_user(req.username, req.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return Token(access_token=token)


@app.get("/me")
def me(user: User | None = Depends(get_current_user)):
    if user:
        return {"username": user.username, "is_admin": user.is_admin, "authenticated": True}
    return {"authenticated": False}


@app.get("/wheels")
def list_wheels() -> dict[str, Any]:
    """Return list of available wheels with metadata."""
    result = {}
    for name, (tickets, pb) in WHEELS.items():
        pool = set()
        for t in tickets:
            pool.update(t)
        result[name] = {
            "name": name,
            "tickets": len(tickets),
            "suggested_powerball": pb,
            "pool_size": len(pool),
            "pool_numbers": sorted(pool),
        }
    return {"wheels": result}


@app.get("/wheel/{wheel_name}")
def get_wheel(wheel_name: str) -> dict[str, Any]:
    """Return a wheel's tickets and suggested powerball."""
    if wheel_name not in WHEELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wheel '{wheel_name}'. Available: {list(WHEELS.keys())}",
        )
    tickets, pb = WHEELS[wheel_name]
    return {
        "name": wheel_name,
        "tickets": [sorted(t) for t in tickets],
        "suggested_powerball": pb,
        "ticket_count": len(tickets),
        "cost": len(tickets) * _ticket_cost,
    }


@app.post("/check")
def check_wheel(req: CheckRequest) -> dict[str, Any]:
    """Check a wheel against a draw and return the win summary."""
    if req.wheel not in WHEELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wheel '{req.wheel}'. Available: {list(WHEELS.keys())}",
        )

    if len(set(req.draw)) != 6:
        raise HTTPException(status_code=400, detail="Draw numbers must be unique.")
    if any(n < 1 or n > 40 for n in req.draw):
        raise HTTPException(status_code=400, detail="Main numbers must be between 1 and 40.")

    tickets, wheel_pb = WHEELS[req.wheel]
    draw_set = set(req.draw)
    n_tickets = len(tickets)
    cost = n_tickets * _ticket_cost

    # Score each ticket — highest qualifying division wins
    counts = {d[0]: 0 for d in DIVISIONS}
    for ticket in tickets:
        matches = len(set(ticket) & draw_set)
        pb_hit = wheel_pb == req.powerball
        for label, main_needed, pb_must_match, _ in DIVISIONS:
            if matches == main_needed and pb_hit == pb_must_match:
                counts[label] += 1
                break

    # Pool overlap
    pool_set = set()
    for t in tickets:
        pool_set.update(t)

    divisions = []
    total_prize = 0.0
    for label, _, _, prize in DIVISIONS:
        c = counts[label]
        winnings = c * prize
        if c:
            divisions.append({
                "division": label,
                "winners": c,
                "prize_per_ticket": prize,
                "total": winnings,
            })
            total_prize += winnings

    net = total_prize - cost
    roi_pct = (net / cost * 100) if cost else 0.0

    return {
        "wheel": req.wheel,
        "draw": sorted(req.draw),
        "powerball": req.powerball,
        "wheel_powerball": wheel_pb,
        "pool_overlap": len(draw_set & pool_set),
        "ticket_count": n_tickets,
        "cost": round(cost, 2),
        "divisions": divisions,
        "total_prize": round(total_prize, 2),
        "net": round(net, 2),
        "roi_pct": round(roi_pct, 2),
    }


@app.get("/check-strike")
def check_strike(
    n1: int = 0,
    n2: int = 0,
    n3: int = 0,
    n4: int = 0,
) -> dict[str, Any]:
    """Check Lotto Strike against the first 4 numbers of the latest draw.

    Query parameters:
        n1, n2, n3, n4 — the four Strike numbers (1–40) in exact order.

    Returns the Strike division won, exact match count, and estimated prize.
    """
    from prize_calculator import count_exact_matches, calculate_strike_prize, STRIKE_LABELS

    player_nums = [n1, n2, n3, n4]
    if any(n < 1 or n > 40 for n in player_nums if n != 0):
        raise HTTPException(
            status_code=400,
            detail="Each Strike number must be between 1 and 40.",
        )
    if any(n == 0 for n in player_nums):
        raise HTTPException(
            status_code=400,
            detail="All four Strike numbers (n1, n2, n3, n4) are required.",
        )

    if not _draws:
        raise HTTPException(status_code=503, detail="Draw data not loaded.")

    # Use the latest draw's first 4 numbers
    latest = _draws[-1]
    draw_first4 = list(latest[0][:4])
    draw_date = latest[3]

    exact = count_exact_matches(player_nums, draw_first4)
    result = calculate_strike_prize(exact)

    return {
        "draw_date": draw_date,
        "draw_numbers": draw_first4,
        "player_numbers": player_nums,
        "exact_matches": exact,
        "strike_division": result["division"],
        "division_label": result["division_label"],
        "prize": result["prize"],
        "is_estimated": result["is_estimated"],
    }


@app.get("/stats")
def get_stats() -> dict[str, Any]:
    """Return statistical report (positive/negative, block analysis, etc.)."""
    if not _draws:
        raise HTTPException(status_code=503, detail="Draw data not loaded.")

    draws = _draws
    pos, neg, freq = positive_negative_split(draws)
    blocks = block_analysis(draws)
    low_sum, high_sum = sum_range(draws)
    adj_ratio = numerical_attraction(draws)
    bayes = bayesian_posterior(draws)
    top_bayes = [n for n, _ in sorted(bayes.items(), key=lambda x: x[1], reverse=True)[:10]]
    bandit_top = bandit_recommendation(draws)

    return {
        "positive_numbers": sorted(pos),
        "negative_numbers": sorted(neg),
        "frequency": dict(freq.most_common()),
        "block_analysis": {
            f"pos_{i+1}": cats for i, cats in blocks.items()
        },
        "sum_range": {"low": low_sum, "high": high_sum},
        "numerical_attraction_pct": round(adj_ratio * 100, 1),
        "bayesian_top_10": top_bayes,
        "bandit_top_6": bandit_top,
    }


@app.get("/api/bonus/stats")
def get_bonus_stats_endpoint() -> list[dict]:
    """Return bonus ball statistics for numbers 1-40."""
    conn = sqlite3.connect("lotto.db")
    try:
        return get_bonus_stats(conn)
    finally:
        conn.close()


@app.get("/predict/bonus_bayesian")
def predict_bonus_bayesian(k: int = 5) -> list[dict]:
    """Return top-k bonus ball predictions using Dirichlet-Multinomial Bayesian.

    Query params:
        k (int): number of top predictions to return (default 5).
    """
    from predictions import BonusBayesian

    conn = sqlite3.connect("lotto.db")
    try:
        rows = conn.execute("SELECT bonus FROM draws ORDER BY draw_date ASC").fetchall()
    finally:
        conn.close()

    bonus_balls = [r[0] for r in rows if r[0] and 1 <= r[0] <= 40]
    if not bonus_balls:
        raise HTTPException(status_code=404, detail="No bonus ball data found.")

    model = BonusBayesian(bonus_balls, alpha=1.0)
    top_k = model.predict_top_k(k=min(k, 40))
    return [
        {"rank": i + 1, "bonus_number": n, "probability": round(p, 6)}
        for i, (n, p) in enumerate(top_k)
    ]


@app.get("/predict/bonus_gap")
def predict_bonus_gap(k: int = 5) -> list[dict]:
    """Return top-k 'due' bonus ball predictions using gap + frequency scoring."""
    from predictions import bonus_gap_prediction

    conn = sqlite3.connect("lotto.db")
    try:
        top_k = bonus_gap_prediction(conn, k=min(k, 40))
        return [
            {"rank": i + 1, "bonus_number": n, "score": s}
            for i, (n, s) in enumerate(top_k)
        ]
    finally:
        conn.close()


@app.get("/predict/bonus/hierarchical")
def predict_bonus_hierarchical(k: int = 5, halflife: int = 90) -> list[dict]:
    """Return top-k bonus predictions using Hierarchical Bayesian with recency.

    Query params:
        k (int): number of top predictions (default 5).
        halflife (int): recency half-life in days (default 90).
    """
    from predictions import HierarchicalBonusPredictor

    conn = sqlite3.connect("lotto.db")
    try:
        rows = conn.execute(
            "SELECT draw_date, bonus FROM draws ORDER BY draw_date ASC"
        ).fetchall()
    finally:
        conn.close()

    draws = [(r[0], r[1]) for r in rows if r[1] and 1 <= r[1] <= 40]
    if not draws:
        raise HTTPException(status_code=404, detail="No bonus ball data found.")

    model = HierarchicalBonusPredictor(draws, recency_halflife_days=halflife)
    model.fit()
    top_k = model.predict_top_k(k=min(k, 40))
    return [
        {"rank": i + 1, "bonus_number": n, "posterior_mean": m, "posterior_std": s}
        for i, (n, m, s) in enumerate(top_k)
    ]


@app.get("/predict/bonus/probability")
def predict_bonus_probability(num: int, halflife: int = 90) -> dict[str, Any]:
    """Return posterior probability for a specific bonus number.

    Query params:
        num (int): bonus ball number (1-40).
        halflife (int): recency half-life in days (default 90).
    """
    if not (1 <= num <= 40):
        raise HTTPException(status_code=400, detail="num must be 1-40.")

    from predictions import HierarchicalBonusPredictor

    conn = sqlite3.connect("lotto.db")
    try:
        rows = conn.execute(
            "SELECT draw_date, bonus FROM draws ORDER BY draw_date ASC"
        ).fetchall()
    finally:
        conn.close()

    draws = [(r[0], r[1]) for r in rows if r[1] and 1 <= r[1] <= 40]
    if not draws:
        raise HTTPException(status_code=404, detail="No bonus ball data found.")

    model = HierarchicalBonusPredictor(draws, recency_halflife_days=halflife)
    model.fit()
    prob = model.probability_of_number(num)
    return {
        "bonus_number": num,
        "posterior_mean": prob,
        "posterior_std": round(model.posterior_std.get(num, 0), 6),
        "halflife_days": halflife,
    }


@app.get("/predict/ensemble")
def predict_ensemble(main: int = 15, bonus: int = 5, pb: int = 3) -> dict[str, Any]:
    """Return ensemble predictions fusing Bayesian, Markov, and Albert methods.

    Query params:
        main (int): number of top main numbers (default 15).
        bonus (int): number of top bonus balls (default 5).
        pb (int): number of top Powerballs (default 3).
    """
    conn = sqlite3.connect("lotto.db")
    try:
        from ensemble import EnsemblePredictor
        ep = EnsemblePredictor(conn)
        ep.fit_weights(validation_draws=10)
        return ep.predict_all(main_top=main, bonus_top=bonus, pb_top=pb)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# EV Simulation
# ---------------------------------------------------------------------------

class EVSimulationRequest(BaseModel):
    wheel: str
    num_sims: int = 100_000


@app.post("/ev_simulation")
@limiter.limit(_heavy_limit)
def ev_simulation_endpoint(req: EVSimulationRequest, request: Request = None) -> dict[str, Any]:
    """Run a Monte Carlo bonus-ball EV simulation for a wheel.

    Body: {"wheel": "single1", "num_sims": 100000}
    """
    if req.wheel not in WHEELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wheel '{req.wheel}'. Available: {list(WHEELS.keys())}",
        )
    if not (10_000 <= req.num_sims <= 5_000_000):
        raise HTTPException(status_code=400, detail="num_sims must be 10 000 – 5 000 000.")

    from backtest import simulate_bonus_ev
    return simulate_bonus_ev(req.wheel, num_sims=req.num_sims)


# ---------------------------------------------------------------------------
# Bonus–Main Co-occurrence
# ---------------------------------------------------------------------------

@app.get("/analysis/cooccurrence/matrix")
def cooccurrence_matrix_endpoint(min_support: int = 5) -> dict[str, Any]:
    """Return the bonus–main co-occurrence matrix as a nested JSON structure.

    Query params:
        min_support (int): minimum count threshold (default 5).
    """
    conn = sqlite3.connect("lotto.db")
    try:
        from analysis_bonus_pairs import compute_cooccurrence_matrix
        df = compute_cooccurrence_matrix(conn, min_support=min_support)
        return {
            "index": df.index.tolist(),
            "columns": df.columns.tolist(),
            "data": df.values.tolist(),
        }
    finally:
        conn.close()


@app.get("/analysis/cooccurrence/pairs/{bonus_num}")
def cooccurrence_pairs_endpoint(bonus_num: int, top_k: int = 3) -> list[dict]:
    """Return top-k main numbers that co-occur with a specific bonus ball."""
    if not (1 <= bonus_num <= 40):
        raise HTTPException(status_code=400, detail="bonus_num must be 1-40.")

    conn = sqlite3.connect("lotto.db")
    try:
        from analysis_bonus_pairs import get_top_pairs_for_bonus
        pairs = get_top_pairs_for_bonus(conn, bonus_num, top_k=top_k)
        return [{"main_number": n, "count": c} for n, c in pairs]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Backtest Bonus Impact
# ---------------------------------------------------------------------------

@app.get("/backtest/bonus_impact")
@limiter.limit(_heavy_limit)
def backtest_bonus_impact_endpoint(wheel_name: str, draws: int = 0, request: Request = None) -> dict[str, Any]:
    """Return bonus-impact report for a wheel against historical draws.

    Query params:
        wheel_name (str): Wheel name (e.g. 'single1', 'double').
        draws (int): Number of recent draws to test (0 = all).
    """
    if wheel_name not in WHEELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wheel '{wheel_name}'. Available: {list(WHEELS.keys())}",
        )

    from backtest import backtest_bonus_impact
    num = draws if draws > 0 else None
    return backtest_bonus_impact(wheel_name, num)

@app.get("/analysis/cooccurrence/triplets")
def cooccurrence_triplets_endpoint(top_n: int = 10) -> list[dict]:
    """Return top-N bonus+main+main triplets."""
    conn = sqlite3.connect("lotto.db")
    try:
        from analysis_bonus_pairs import get_top_triplets
        triplets = get_top_triplets(conn, top_n=top_n)
        return [{"bonus": b, "main1": m1, "main2": m2, "count": c}
                for b, m1, m2, c in triplets]
    finally:
        conn.close()