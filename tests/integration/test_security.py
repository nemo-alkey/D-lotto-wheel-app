"""Integration tests for the security hardening layer.

Covers:
  - password complexity rules on /register
  - refresh token issuance and rotation (/token, /token/refresh)
  - refresh tokens rejected as access tokens
  - account lockout after 5 failed logins (30 min cooldown -> HTTP 423)
  - security headers middleware
  - pydantic input validators (unique/sorted numbers, past-only dates,
    sanitized strings)
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import ValidationError

import api
import auth

pytestmark = pytest.mark.integration

PASSWORD = "Testpass123"


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Generator[None, None, None]:
    """Clear slowapi's in-memory storage so per-IP limits don't accumulate."""
    try:
        storage = api.limiter.limiter.storage
        reset = getattr(storage, "reset", None)
        if callable(reset):
            reset()
    except Exception:
        pass
    yield


def _reset_limiter_now() -> None:
    storage = api.limiter.limiter.storage
    reset = getattr(storage, "reset", None)
    if callable(reset):
        reset()


@pytest.fixture
def temp_user_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point auth.DB_PATH at a temp DB and return a unique username."""
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "test_users.db"))
    return f"secuser_{uuid.uuid4().hex[:8]}"


def _register(client: TestClient, username: str) -> Response:
    return client.post("/register", json={"username": username, "password": PASSWORD})


# ---------------------------------------------------------------------------
# Password complexity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "weak",
    [
        "short1A",  # too short
        "alllowercase1",  # no uppercase
        "ALLUPPERCASE1",  # no lowercase
        "NoDigitsHere",  # no digit
    ],
)
def test_register_weak_password_422(client: TestClient, temp_user_db: str, weak: str) -> None:
    resp = client.post("/register", json={"username": temp_user_db, "password": weak})
    assert resp.status_code == 422


def test_register_strong_password_201(client: TestClient, temp_user_db: str) -> None:
    assert _register(client, temp_user_db).status_code == 201


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------


def test_login_returns_refresh_token(client: TestClient, temp_user_db: str) -> None:
    _register(client, temp_user_db)
    resp = client.post("/token", json={"username": temp_user_db, "password": PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_refresh_returns_new_pair(client: TestClient, temp_user_db: str) -> None:
    _register(client, temp_user_db)
    tokens = client.post("/token", json={"username": temp_user_db, "password": PASSWORD}).json()

    resp = client.post("/token/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]

    # The refreshed access token authenticates against /me.
    me = client.get("/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["username"] == temp_user_db


def test_refresh_with_garbage_token_401(client: TestClient) -> None:
    resp = client.post("/token/refresh", json={"refresh_token": "not-a-jwt"})
    assert resp.status_code == 401


def test_refresh_token_rejected_as_access_token(client: TestClient, temp_user_db: str) -> None:
    _register(client, temp_user_db)
    tokens = client.post("/token", json={"username": temp_user_db, "password": PASSWORD}).json()

    me = client.get("/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert me.status_code == 200
    assert me.json()["authenticated"] is False


def test_access_token_rejected_as_refresh_token(client: TestClient, temp_user_db: str) -> None:
    _register(client, temp_user_db)
    tokens = client.post("/token", json={"username": temp_user_db, "password": PASSWORD}).json()

    resp = client.post("/token/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------


def test_lockout_after_five_failed_logins(client: TestClient, temp_user_db: str) -> None:
    _register(client, temp_user_db)
    payload = {"username": temp_user_db, "password": "WrongPass1"}

    for _ in range(5):
        resp = client.post("/token", json=payload)
        assert resp.status_code == 401

    # 6th attempt: reset the per-IP rate limit so the lockout (423), not
    # the login rate limit (429), is what answers.
    _reset_limiter_now()
    resp = client.post("/token", json=payload)
    assert resp.status_code == 423

    # Even the correct password is rejected while locked.
    _reset_limiter_now()
    resp = client.post("/token", json={"username": temp_user_db, "password": PASSWORD})
    assert resp.status_code == 423


def test_successful_login_clears_failure_count(client: TestClient, temp_user_db: str) -> None:
    _register(client, temp_user_db)
    bad = {"username": temp_user_db, "password": "WrongPass1"}
    good = {"username": temp_user_db, "password": PASSWORD}

    # 4 failures (below the threshold), then a success resets the counter.
    for _ in range(4):
        _reset_limiter_now()
        assert client.post("/token", json=bad).status_code == 401
    _reset_limiter_now()
    assert client.post("/token", json=good).status_code == 200

    # 4 more failures must not trigger the lockout (counter was reset).
    for _ in range(4):
        _reset_limiter_now()
        assert client.post("/token", json=bad).status_code == 401
    _reset_limiter_now()
    assert client.post("/token", json=good).status_code == 200


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


def test_security_headers_on_api_response(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-XSS-Protection"] == "1; mode=block"
    assert resp.headers["Strict-Transport-Security"] == ("max-age=31536000; includeSubDomains")
    assert resp.headers["Content-Security-Policy"] == "default-src 'self'"


def test_docs_page_gets_cdn_friendly_csp(client: TestClient) -> None:
    resp = client.get("/docs/custom")
    csp = resp.headers["Content-Security-Policy"]
    assert "cdn.redoc.ly" in csp


# ---------------------------------------------------------------------------
# Input validators (model level)
# ---------------------------------------------------------------------------


def test_draw_create_rejects_duplicate_numbers() -> None:
    with pytest.raises(ValidationError):
        api.DrawCreate(
            draw_number=1,
            date="2024-01-01",
            main_numbers=[3, 3, 11, 19, 27, 33],
            bonus=7,
        )


def test_draw_create_sorts_numbers() -> None:
    draw = api.DrawCreate(
        draw_number=1,
        date="2024-01-01",
        main_numbers=[40, 3, 33, 11, 27, 19],
        bonus=7,
    )
    assert draw.main_numbers == [3, 11, 19, 27, 33, 40]


def test_draw_create_rejects_future_date() -> None:
    with pytest.raises(ValidationError):
        api.DrawCreate(
            draw_number=1,
            date="2999-01-01",
            main_numbers=[3, 11, 19, 27, 33, 40],
            bonus=7,
        )


def test_wheel_request_rejects_html_in_guarantee() -> None:
    with pytest.raises(ValidationError):
        api.WheelRequest(pool_size=10, guarantee_type="<script>alert(1)</script>")


def test_backtest_rejects_future_dates() -> None:
    with pytest.raises(ValidationError):
        api.BacktestRequest(start_date="2999-01-01", wheel_type="single1")


def test_check_request_strips_and_sanitizes_wheel_name() -> None:
    req = api.CheckRequest(wheel="  single1  ", draw=[3, 11, 19, 27, 33, 40], powerball=5)
    assert req.wheel == "single1"
    with pytest.raises(ValidationError):
        api.CheckRequest(wheel="<b>single1</b>", draw=[3, 11, 19, 27, 33, 40], powerball=5)
