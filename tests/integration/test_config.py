"""Integration test for the /config endpoint (config dependency injection)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_config_endpoint(client: TestClient) -> None:
    resp = client.get("/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app_name"] == "Lotto Wheel App"
    assert body["version"] == "2.0.0"
    assert body["debug"] is True  # tests set DEBUG=true in conftest
    # No secrets leak through the endpoint.
    assert "secret" not in {k.lower() for k in body}


def test_config_health_endpoint(client: TestClient) -> None:
    resp = client.get("/config/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app_name"] == "Lotto Wheel App"
    assert body["version"] == "2.0.0"
    assert body["environment"] == "development"
    assert isinstance(body["features"], dict)
    assert "payments" in body["features"]
    assert body["database"]["backend"] == "sqlite"
    # No secrets leak through the endpoint.
    assert not [k for k in body if "secret" in k.lower()]


def test_admin_config_requires_auth(client: TestClient) -> None:
    assert client.get("/admin/config").status_code == 401


def test_admin_config_forbidden_for_non_admin(
    authenticated_client: tuple[TestClient, str],
) -> None:
    client, _username = authenticated_client
    assert client.get("/admin/config").status_code == 403


def test_admin_config_masks_secrets(client: TestClient) -> None:
    import auth

    token = auth.create_access_token("test_admin", True)
    resp = client.get("/admin/config", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["requested_by"] == "test_admin"
    config = body["config"]
    assert config["SECRET_KEY"] == "********"
    assert config["APP_NAME"] == "Lotto Wheel App"
    # The raw secret must not appear anywhere in the payload.
    from config_manager import get_settings

    assert get_settings().SECRET_KEY not in str(body)
