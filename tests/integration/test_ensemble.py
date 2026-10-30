"""Regression tests for ensemble Powerball probabilities."""

from __future__ import annotations

import pytest

from ensemble import EnsemblePredictor
from powerball_rules import POWERBALL_MAX_NEW


def test_powerball_probabilities_cover_all_fourteen_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Powerballs 11-14 must contribute to the current probability pool."""
    predictor = EnsemblePredictor.__new__(EnsemblePredictor)
    predictor.draws = [
        ([1, 2, 3, 4, 5, 6], 10, 0, "2026-09-16"),
        ([7, 8, 9, 10, 11, 12], 11, 0, "2026-09-19"),
        ([13, 14, 15, 16, 17, 18], 14, 0, "2026-09-23"),
    ]
    predictor.weights = {}
    monkeypatch.setattr(predictor, "predict_main_numbers", lambda top_n: [])

    result = predictor.predict_all(main_top=0, bonus_top=0, pb_top=POWERBALL_MAX_NEW)
    scores = dict(result["powerball"])

    assert set(scores) == set(range(1, POWERBALL_MAX_NEW + 1))
    assert scores[11] > 0
    assert scores[14] > 0
    assert sum(scores.values()) == pytest.approx(1.0, abs=1e-5)


def test_markov_sub_predictor_supports_fourteen_powerballs() -> None:
    """The ensemble's Markov sub-predictor handles the expanded PB matrix."""
    from predictions import markov

    draws = [
        ([1, 2, 3, 4, 5, 6], 14, 0, "2026-09-16"),
        ([7, 8, 9, 10, 11, 12], 11, 0, "2026-09-19"),
        ([13, 14, 15, 16, 17, 18], 14, 0, "2026-09-23"),
    ]

    result = markov(draws)

    assert 1 <= result["powerball"] <= POWERBALL_MAX_NEW
