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
    """Run the dashboard script once via AppTest and return the result."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(DASHBOARD_PATH, default_timeout=120)
    at.run(timeout=120)
    return at


def test_dashboard_file_exists() -> None:
    assert os.path.isfile(DASHBOARD_PATH), f"dashboard.py not found at {DASHBOARD_PATH}"


def test_dashboard_runs_without_exception(app: "AppTest") -> None:
    assert not app.exception, (
        "dashboard.py raised an exception during run: "
        + "; ".join(str(e.value) for e in app.exception)
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

    # Sidebar navigation radio defaults to 'Wheels & Tickets'
    nav_radios = [r for r in app.radio if r.label == "Go to"]
    assert nav_radios, "navigation radio 'Go to' not found"
    assert nav_radios[0].value == "Wheels & Tickets"
