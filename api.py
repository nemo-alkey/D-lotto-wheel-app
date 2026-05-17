#!/usr/bin/env python3
"""
FastAPI server for NZ Lotto Powerball wheel analysis.
Reuses existing functions from lotto_wheels.py.

Start with:  uvicorn api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from lotto_wheels import (
    WHEELS,
    DIVISIONS,
    load_draws,
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


app = FastAPI(title="NZ Lotto Powerball API", version="1.0.0", lifespan=lifespan)


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
        "cost": len(tickets) * 1.50,
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
    cost = n_tickets * 1.50

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
