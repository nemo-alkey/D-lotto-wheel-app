"""Smoke test: the Streamlit dashboard boots and renders its landing page.

Uses streamlit.testing.v1.AppTest to execute dashboard.py headlessly and
asserts that the script runs to completion without an unhandled exception
or any st.error elements.
"""

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.slow

DASHBOARD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "dashboard.py",
)


@pytest.fixture(scope="module")
def app() -> "AppTest":
    """Run the dashboard script via AppTest with a stubbed API.

    The dashboard hits /health (JSON) and /metrics (Prometheus text) at
    load. We stub requests.get/post with a URL-aware fake so neither call
    hits the network: /health returns {"status":"ok"}, everything else
    returns an empty Prometheus body.
    """
    from unittest.mock import patch

    from streamlit.testing.v1 import AppTest

    def _make_response(url: str) -> object:
        is_health = "/health" in url
        return type(
            "FakeResponse",
            (),
            {
                "status_code": 200,
                "ok": True,
                "raise_for_status": lambda self: None,
                "json": (lambda self: {"status": "ok"}) if is_health else (lambda self: {}),
                "text": "ok" if is_health else "",
            },
        )()

    def fake_request(url, *args, **kwargs):
        return _make_response(str(url))

    with (
        patch("requests.get", side_effect=fake_request),
        patch("requests.post", side_effect=fake_request),
    ):
        at = AppTest.from_file(DASHBOARD_PATH, default_timeout=120)
        at.run(timeout=120)
        return at


def test_dashboard_file_exists() -> None:
    assert os.path.isfile(DASHBOARD_PATH), f"dashboard.py not found at {DASHBOARD_PATH}"


def test_dashboard_runs_without_exception(app: "AppTest") -> None:
    assert not app.exception, "dashboard.py raised an exception during run: " + "; ".join(
        str(e.value) for e in app.exception
    )


def test_dashboard_renders_no_error_elements(app: "AppTest") -> None:
    assert not app.error, "dashboard.py rendered st.error elements: " + "; ".join(
        e.value for e in app.error
    )


def test_dashboard_renders_landing_page(app: "AppTest") -> None:
    """The default page ('Wheels & Tickets') renders expected chrome."""
    # Main header rendered via st.markdown
    markdown_texts = [m.value for m in app.markdown]
    assert any(
        "NZ Lotto Powerball Wheel Dashboard" in t for t in markdown_texts
    ), "landing page header not found in rendered markdown"

    # Per-tab navigation radio; the Wheels tab is the default landing page
    nav_radios = [r for r in app.radio if r.label == "🎡 Wheels section"]
    assert nav_radios, "navigation radio 'Wheels section' not found"
    assert nav_radios[0].value == "Wheels & Tickets"
