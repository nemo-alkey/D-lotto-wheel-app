"""Integration tests for the FastAPI endpoints in api.py.

api.py enforces a two-tier rate limit (60/min authenticated, 10/min
anonymous per IP). TestClient requests share one apparent IP, and the
register/token calls made by the authenticated_client fixture are
anonymous hits, so an autouse fixture resets the limiter storage before
each test to keep the suite deterministic. Most tests run through the
authenticated_client fixture; anonymous `client` is used only for the
explicitly unauthenticated checks.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi.testclient import TestClient

import api

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    """Clear slowapi's in-memory storage so per-IP limits don't accumulate."""
    try:
        storage = api.limiter.limiter.storage
        reset = getattr(storage, "reset", None)
        if callable(reset):
            reset()
    except Exception:
        pass
    yield


def _first_wheel_name(client: TestClient) -> str:
    resp = client.get("/wheels")
    assert resp.status_code == 200
    return cast(str, next(iter(resp.json()["wheels"])))


# ---------------------------------------------------------------------------
# Basic liveness
# ---------------------------------------------------------------------------


def test_root(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "draws" in body
    assert isinstance(body["draws"], int)


# ---------------------------------------------------------------------------
# Wheels
# ---------------------------------------------------------------------------


def test_list_wheels(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client
    resp = client.get("/wheels")
    assert resp.status_code == 200
    wheels = resp.json()["wheels"]
    assert len(wheels) > 0
    for _name, meta in wheels.items():
        assert meta["tickets"] > 0
        assert meta["pool_size"] > 0


def test_get_wheel_valid(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client
    name = _first_wheel_name(client)
    resp = client.get(f"/wheel/{name}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == name
    assert isinstance(body["tickets"], list)
    assert len(body["tickets"]) > 0
    for ticket in body["tickets"]:
        assert len(ticket) == 6


def test_get_wheel_invalid_returns_404(
    authenticated_client: tuple[TestClient, str],
) -> None:
    client, _ = authenticated_client
    resp = client.get("/wheel/no-such-wheel")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /check
# ---------------------------------------------------------------------------


def test_check_wheel(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client
    name = _first_wheel_name(client)
    resp = client.post(
        "/check",
        json={"wheel": name, "draw": [1, 2, 3, 4, 5, 6], "powerball": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "divisions" in body
    assert "total_prize" in body
    assert "net" in body
    assert body["wheel"] == name


def test_check_wheel_duplicate_draw_numbers_400(
    authenticated_client: tuple[TestClient, str],
) -> None:
    client, _ = authenticated_client
    name = _first_wheel_name(client)
    resp = client.post(
        "/check",
        json={"wheel": name, "draw": [1, 1, 2, 3, 4, 5], "powerball": 1},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


def test_leaderboard(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client
    resp = client.get("/leaderboard")
    assert resp.status_code == 200
    assert isinstance(resp.json()["leaderboard"], list)


# ---------------------------------------------------------------------------
# /predict/ensemble — verified manually against the 1-draw DB: returns 200
# with main/bonus/powerball lists. Slow because of the walk-forward fit.
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_predict_ensemble(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client
    resp = client.get("/predict/ensemble", params={"main": 5, "bonus": 2, "pb": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["main"]) == 5
    assert len(body["bonus"]) == 2
    assert len(body["powerball"]) == 1


# ---------------------------------------------------------------------------
# Anonymous vs authenticated /me
# ---------------------------------------------------------------------------


def test_me_anonymous(client: TestClient) -> None:
    resp = client.get("/me")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False}


def test_me_authenticated(authenticated_client: tuple[TestClient, str]) -> None:
    client, username = authenticated_client
    resp = client.get("/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True
    assert body["username"] == username
