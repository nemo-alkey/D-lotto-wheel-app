"""Shared pytest fixtures for the NZ Lotto test suite."""

from __future__ import annotations

import os
import random
import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Tests run in dev mode: DEBUG defaults to False (secure by default) in
# config/settings.py, and the startup guard would reject the placeholder
# SECRET_KEY in production mode. Set before any test module imports api.
os.environ.setdefault("DEBUG", "true")


@pytest.fixture
def db_connection() -> Iterator[sqlite3.Connection]:
    """In-memory SQLite connection with the draws schema.

    Rolled back and closed after each test — no state leaks between tests.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE draws (
            draw_id    INTEGER PRIMARY KEY,
            draw_date  TEXT NOT NULL UNIQUE,
            numbers    TEXT NOT NULL,
            bonus      INTEGER CHECK (bonus BETWEEN 1 AND 40),
            powerball  INTEGER CHECK (powerball BETWEEN 1 AND 10)
        )
    """)
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def sample_draws() -> list[tuple[list[int], int, int, str]]:
    """50 synthetic draws with realistic patterns.

    Shape matches lotto_wheels.load_draws(): (numbers, powerball, bonus, date).
    Numbers 1-13 are weighted hot (like a warm streak), sums cluster in the
    typical 90-180 band, and consecutive pairs appear regularly.
    """
    rng = random.Random(42)
    weights = [3.0 if n <= 13 else 1.0 for n in range(1, 41)]

    draws = []
    for i in range(50):
        num_set: set[int] = set()
        while len(num_set) < 6:
            pick = rng.choices(range(1, 41), weights=weights, k=1)[0]
            num_set.add(pick)
        # Inject a consecutive pair into every third draw
        nums = sorted(num_set)
        if i % 3 == 0 and nums[-1] < 40:
            nums[-1] = nums[-2] + 1 if nums[-2] + 1 not in nums else nums[-1]
        draws.append(
            (
                sorted(nums),
                rng.randint(1, 10),  # powerball
                rng.randint(1, 40),  # bonus
                f"2024-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}",
            )
        )
    return draws


@pytest.fixture
def sample_wheel() -> list[tuple[int, ...]]:
    """A valid small wheel: 4 tickets of 6 unique numbers each (1-40)."""
    return [
        (1, 7, 13, 22, 28, 35),
        (2, 9, 15, 24, 30, 38),
        (3, 10, 17, 25, 33, 40),
        (5, 11, 19, 27, 32, 36),
    ]


@pytest.fixture
def client() -> Iterator[TestClient]:
    """FastAPI TestClient (runs the app lifespan)."""

    from api import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def authenticated_client(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, str]]:
    """TestClient with a valid JWT; users go to a temp DB, not lotto.db.

    Yields (client, username) with the Authorization header preset.
    """
    import auth

    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "test_users.db"))

    username = f"testuser_{uuid.uuid4().hex[:8]}"
    password = "Testpass123"

    resp = client.post("/register", json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text

    resp = client.post("/token", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]

    client.headers.update({"Authorization": f"Bearer {token}"})
    yield client, username
