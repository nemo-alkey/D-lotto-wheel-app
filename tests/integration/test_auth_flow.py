"""Integration tests for the full JWT auth flow (register/login/protected/me).

api.py has no endpoints gated by require_user (only /me uses optional
auth), so a throwaway FastAPI app with one route depending on
auth.require_user is built here and used as the protected-route stand-in.
Users are written to a temp DB via monkeypatched auth.DB_PATH — lotto.db
is never touched.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import api
import auth

pytestmark = pytest.mark.integration

PASSWORD = "Testpass123"


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


@pytest.fixture
def temp_user_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point auth.DB_PATH at a temp DB and return a unique username."""
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "test_users.db"))
    return f"flowuser_{uuid.uuid4().hex[:8]}"


def _protected_app() -> FastAPI:
    """Mini app with one route gated by auth.require_user."""
    app = FastAPI()

    @app.get("/protected")
    def protected(user: auth.User = Depends(auth.require_user)) -> dict[str, object]:
        return {"username": user.username, "is_admin": user.is_admin}

    return app


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_success(client: TestClient, temp_user_db: str) -> None:
    resp = client.post("/register", json={"username": temp_user_db, "password": PASSWORD})
    assert resp.status_code == 201


def test_register_duplicate_409(client: TestClient, temp_user_db: str) -> None:
    payload = {"username": temp_user_db, "password": PASSWORD}
    assert client.post("/register", json=payload).status_code == 201
    resp = client.post("/register", json=payload)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_success_returns_token(client: TestClient, temp_user_db: str) -> None:
    payload = {"username": temp_user_db, "password": PASSWORD}
    assert client.post("/register", json=payload).status_code == 201

    resp = client.post("/token", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_login_wrong_password_401(client: TestClient, temp_user_db: str) -> None:
    assert (
        client.post("/register", json={"username": temp_user_db, "password": PASSWORD}).status_code
        == 201
    )

    resp = client.post("/token", json={"username": temp_user_db, "password": "wrong-password"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Protected route (mini app stand-in using auth.require_user)
# ---------------------------------------------------------------------------


def test_protected_route_with_valid_token(client: TestClient, temp_user_db: str) -> None:
    payload = {"username": temp_user_db, "password": PASSWORD}
    assert client.post("/register", json=payload).status_code == 201
    token = client.post("/token", json=payload).json()["access_token"]

    protected_client = TestClient(_protected_app())
    resp = protected_client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == temp_user_db


def test_protected_route_without_token_401() -> None:
    protected_client = TestClient(_protected_app())
    resp = protected_client.get("/protected")
    assert resp.status_code == 401


def test_protected_route_garbage_token_401() -> None:
    protected_client = TestClient(_protected_app())
    resp = protected_client.get("/protected", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401


def test_logout_is_client_side_token_discard(client: TestClient, temp_user_db: str) -> None:
    """JWT logout = dropping the header; the route rejects us again."""
    payload = {"username": temp_user_db, "password": PASSWORD}
    assert client.post("/register", json=payload).status_code == 201
    token = client.post("/token", json=payload).json()["access_token"]

    protected_client = TestClient(_protected_app())
    protected_client.headers.update({"Authorization": f"Bearer {token}"})
    assert protected_client.get("/protected").status_code == 200

    # "Logout": discard the token client-side
    protected_client.headers.pop("Authorization")
    assert protected_client.get("/protected").status_code == 401


# ---------------------------------------------------------------------------
# /me with the fixture token
# ---------------------------------------------------------------------------


def test_me_with_fixture_token(authenticated_client: tuple[TestClient, str]) -> None:
    client, username = authenticated_client
    resp = client.get("/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True
    assert body["username"] == username
