"""Tests for NZ Powerball era rules and scraper Powerball validation.

Covers the September 2026 rule change (Powerball pool 1-10 -> 1-14 from the
2026-09-16 draw) and the "fail loudly, never clamp" behaviour of the draw
fetchers.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from bs4 import BeautifulSoup

import update_draws
from powerball_rules import (
    POWERBALL_CHANGE_DATE,
    parse_draw_date,
    powerball_max_for_date,
    validate_powerball,
)


# ---------------------------------------------------------------------------
# Era boundaries
# ---------------------------------------------------------------------------


class TestEraBoundaries:
    def test_change_date_constant(self):
        assert POWERBALL_CHANGE_DATE == date(2026, 9, 16)

    def test_max_old_era(self):
        assert powerball_max_for_date("2026-09-12") == 10
        assert powerball_max_for_date("2020-01-01") == 10

    def test_max_new_era(self):
        assert powerball_max_for_date("2026-09-16") == 14
        assert powerball_max_for_date("2030-01-01") == 14

    def test_old_era_accepts_10(self):
        assert validate_powerball(10, "2026-09-12") == 10

    def test_old_era_rejects_11(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_powerball(11, "2026-09-12")

    def test_new_era_accepts_14(self):
        assert validate_powerball(14, "2026-09-16") == 14
        assert validate_powerball(11, "2026-09-16") == 11

    def test_new_era_rejects_15(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_powerball(15, "2026-09-16")

    def test_zero_rejected_in_both_eras(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_powerball(0, "2026-09-12")
        with pytest.raises(ValueError, match="out of range"):
            validate_powerball(0, "2026-09-16")

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_powerball(-3, "2026-09-16")

    def test_non_integer_rejected(self):
        with pytest.raises(ValueError, match="must be an integer"):
            validate_powerball("7", "2026-09-16")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="must be an integer"):
            validate_powerball(True, "2026-09-16")

    def test_accepts_date_and_datetime_objects(self):
        assert validate_powerball(13, date(2026, 9, 19)) == 13
        assert validate_powerball(4, datetime(2026, 9, 19, 20, 0)) == 4
        with pytest.raises(ValueError, match="out of range"):
            validate_powerball(13, date(2026, 9, 12))

    def test_page_style_date_strings(self):
        # MyLotto page format with weekday name.
        assert validate_powerball(13, "Wednesday, 16 September 2026") == 13
        with pytest.raises(ValueError, match="out of range"):
            validate_powerball(13, "Saturday, 12 September 2026")


class TestParseDrawDate:
    def test_iso(self):
        assert parse_draw_date("2026-09-16") == date(2026, 9, 16)

    def test_weekday_format(self):
        assert parse_draw_date("Wednesday, 16 September 2026") == date(2026, 9, 16)

    def test_unparseable_raises(self):
        with pytest.raises(ValueError, match="Unparseable draw date"):
            parse_draw_date("not a date")

    def test_none_raises(self):
        with pytest.raises(ValueError, match="Unparseable draw date"):
            parse_draw_date(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# update_draws.fetch_draw — era-aware API validation
# ---------------------------------------------------------------------------


def _api_payload(powerball: int, draw_date: str) -> dict:
    return {
        "lotto": {
            "drawDate": draw_date,
            "lottoWinningNumbers": {
                "numbers": [1, 2, 3, 4, 5, 6],
                "bonusBalls": "7",
            },
        },
        "powerBall": {"powerballWinningNumber": str(powerball)},
    }


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, payload: dict):
        self._payload = payload
        self.headers: dict = {}

    def get(self, url: str, timeout: int = 15) -> _FakeResponse:
        return _FakeResponse(self._payload)


class TestFetchDrawEraValidation:
    def test_new_era_powerball_13_accepted(self, monkeypatch):
        """A post-change draw with Powerball 13 must flow through, not fail."""
        monkeypatch.setattr(
            update_draws, "_get_session", lambda: _FakeSession(_api_payload(13, "2026-09-16"))
        )
        draw = update_draws.fetch_draw("2026-09-16")
        assert draw is not None
        assert draw["powerball"] == 13

    def test_new_era_powerball_14_accepted(self, monkeypatch):
        monkeypatch.setattr(
            update_draws, "_get_session", lambda: _FakeSession(_api_payload(14, "2026-10-10"))
        )
        draw = update_draws.fetch_draw("2026-10-10")
        assert draw is not None
        assert draw["powerball"] == 14

    def test_old_era_powerball_11_rejected(self, monkeypatch):
        """Pre-change draw claiming PB 11 is invalid data: no silent clamp."""
        fallback_calls: list = []
        monkeypatch.setattr(
            update_draws, "_get_session", lambda: _FakeSession(_api_payload(11, "2026-09-12"))
        )
        monkeypatch.setattr(
            update_draws,
            "_scraper_fallback",
            lambda date=None: fallback_calls.append(date) or None,
        )
        draw = update_draws.fetch_draw("2026-09-12")
        assert draw is None  # API data rejected; fallback found nothing
        assert fallback_calls == ["2026-09-12"]

    def test_new_era_powerball_15_rejected(self, monkeypatch):
        monkeypatch.setattr(
            update_draws, "_get_session", lambda: _FakeSession(_api_payload(15, "2026-09-19"))
        )
        monkeypatch.setattr(update_draws, "_scraper_fallback", lambda date=None: None)
        assert update_draws.fetch_draw("2026-09-19") is None


# ---------------------------------------------------------------------------
# html_scraper._parse_draw_card — loud validation, no clamping
# ---------------------------------------------------------------------------


def _card_html(draw_date_display: str, powerball: int) -> BeautifulSoup:
    balls = "".join(f'<span class="ball">{n}</span>' for n in (5, 12, 18, 24, 31, 37))
    html = (
        f"<article><time>{draw_date_display}</time>"
        f"{balls}"
        f'<span class="bonus-label">Bonus 9</span>'
        f'<span class="pb">Powerball {powerball}</span>'
        f"</article>"
    )
    return BeautifulSoup(html, "html.parser").find("article")


class TestHtmlScraperCard:
    def test_old_era_card_pb_10_ok(self):
        from html_scraper import _parse_draw_card

        card = _card_html("Saturday, 12 September 2026", 10)
        result = _parse_draw_card(card)
        assert result["powerball"] == 10
        assert result["bonus"] == 9

    def test_old_era_card_pb_13_raises(self):
        from html_scraper import _parse_draw_card

        card = _card_html("Saturday, 12 September 2026", 13)
        with pytest.raises(ValueError, match="out of range"):
            _parse_draw_card(card)

    def test_new_era_card_pb_13_ok(self):
        from html_scraper import _parse_draw_card

        card = _card_html("Wednesday, 16 September 2026", 13)
        result = _parse_draw_card(card)
        assert result["powerball"] == 13

    def test_new_era_card_pb_14_ok(self):
        from html_scraper import _parse_draw_card

        card = _card_html("Saturday, 10 October 2026", 14)
        result = _parse_draw_card(card)
        assert result["powerball"] == 14

    def test_new_era_card_pb_15_raises(self):
        from html_scraper import _parse_draw_card

        card = _card_html("Saturday, 10 October 2026", 15)
        with pytest.raises(ValueError):
            _parse_draw_card(card)

    def test_card_without_powerball_keeps_zero(self):
        """Pre-Powerball-era cards have no Powerball element: absence, not a clamp."""
        from html_scraper import _parse_draw_card

        balls = "".join(f'<span class="ball">{n}</span>' for n in (5, 12, 18, 24, 31, 37))
        html = (
            "<article><time>Saturday, 15 July 2000</time>"
            f"{balls}"
            '<span class="bonus-label">Bonus 9</span>'
            "</article>"
        )
        card = BeautifulSoup(html, "html.parser").find("article")
        result = _parse_draw_card(card)
        assert result["powerball"] == 0
