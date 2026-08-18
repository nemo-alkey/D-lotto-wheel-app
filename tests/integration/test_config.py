"""Integration test for the /config endpoint (config dependency injection)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_config_endpoint(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app_name"] == "Lotto Wheel App"
    assert body["version"] == "2.0.0"
    assert body["debug"] is True  # tests set DEBUG=true in conftest
    # No secrets leak through the endpoint.
    assert "secret" not in {k.lower() for k in body}
