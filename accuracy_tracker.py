from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

DB_PATH = Path("data/lotto.db")
LEADERBOARD_WINDOWS = [10, 20, 50]
TOP_K_VALUES = [10, 15, 20]


@dataclass
class PredictionRecord:
    draw_id: str
    draw_date: str
    predictor_name: str
    recommended_numbers: list[int]
    recommended_probs: list[float] | None
    actual_drawn_numbers: list[int]
    actual_bonus: int | None = None
    timestamp: str = ""


@dataclass
class ScoreCard:
    predictor_name: str
    window_size: int
    last_updated: str
    draws_evaluated: int
    brier_score: float
    hit_rate: float
    top10_accuracy: float
    top15_accuracy: float
    top20_accuracy: float
    mean_reciprocal_rank: float
    exact_match_3: float
    exact_match_4: float
    exact_match_5: float
    exact_match_6: float


def brier_score(probs: list[float] | None, actual: list[int], pool_size: int = 40) -> float:
    if not probs or len(probs) != pool_size:
        return float("nan")
    y = np.zeros(pool_size)
    for num in actual:
        if 1 <= num <= pool_size:
            y[num - 1] = 1.0
    p = np.array(probs, dtype=float)
    return float(np.mean((p - y) ** 2))


def hit_rate(recommended: list[int], actual: list[int]) -> float:
    if not actual:
        return 0.0
    return len(set(recommended) & set(actual)) / len(actual)


def top_k_accuracy(recommended: list[int], actual: list[int], k: int) -> float:
    return 1.0 if (set(recommended[:k]) & set(actual)) else 0.0


def mean_reciprocal_rank(recommended: list[int], actual: list[int]) -> float:
    for rank, num in enumerate(recommended, start=1):
        if num in actual:
            return 1.0 / rank
    return 0.0


def exact_match_counts(recommended: list[int], actual: list[int]) -> tuple[int, int, int, int]:
    hits = len(set(recommended[:6]) & set(actual))
    return (
        1 if hits >= 3 else 0,
        1 if hits >= 4 else 0,
        1 if hits >= 5 else 0,
        1 if hits >= 6 else 0,
    )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS prediction_records (id INTEGER PRIMARY KEY, draw_id TEXT, draw_date TEXT, predictor_name TEXT, recommended_numbers TEXT, recommended_probs TEXT, actual_drawn_numbers TEXT, actual_bonus INTEGER, timestamp TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS scorecards (id INTEGER PRIMARY KEY, predictor_name TEXT, window_size INTEGER, last_updated TEXT, draws_evaluated INTEGER, brier_score REAL, hit_rate REAL, top10_accuracy REAL, top15_accuracy REAL, top20_accuracy REAL, mean_reciprocal_rank REAL, exact_match_3 REAL, exact_match_4 REAL, exact_match_5 REAL, exact_match_6 REAL, UNIQUE(predictor_name, window_size))"
    )
    conn.commit()


def store_prediction(record: PredictionRecord, db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(str(db_path))
    _ensure_schema(conn)
    conn.execute(
        "INSERT INTO prediction_records VALUES (NULL,?,?,?,?,?,?,?,?)",
        (
            record.draw_id,
            record.draw_date,
            record.predictor_name,
            json.dumps(record.recommended_numbers),
            json.dumps(record.recommended_probs) if record.recommended_probs else None,
            json.dumps(record.actual_drawn_numbers),
            record.actual_bonus,
            record.timestamp or datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def backfill_actuals(
    draw_id: str, actual_numbers: list[int], actual_bonus: int | None, db_path: Path = DB_PATH
) -> int:
    conn = sqlite3.connect(str(db_path))
    _ensure_schema(conn)
    cur = conn.execute(
        "UPDATE prediction_records SET actual_drawn_numbers=?, actual_bonus=? WHERE draw_id=? AND actual_drawn_numbers IS NULL",
        (json.dumps(actual_numbers), actual_bonus, draw_id),
    )
    conn.commit()
    updated = cur.rowcount
    conn.close()
    return updated


def score_predictor(
    predictor_name: str, window_size: int, db_path: Path = DB_PATH, pool_size: int = 40
) -> ScoreCard | None:
    conn = sqlite3.connect(str(db_path))
    _ensure_schema(conn)
    rows = conn.execute(
        "SELECT recommended_numbers, recommended_probs, actual_drawn_numbers FROM prediction_records WHERE predictor_name=? AND actual_drawn_numbers IS NOT NULL ORDER BY draw_date DESC LIMIT ?",
        (predictor_name, window_size),
    ).fetchall()
    conn.close()
    if not rows:
        return None
    briers: list[float] = []
    hits: list[float] = []
    top10s: list[float] = []
    top15s: list[float] = []
    top20s: list[float] = []
    mrrs: list[float] = []
    em3: list[int] = []
    em4: list[int] = []
    em5: list[int] = []
    em6: list[int] = []
    for rec_nums_json, rec_probs_json, actual_json in rows:
        rec_nums = json.loads(rec_nums_json)
        actual = json.loads(actual_json)
        rec_probs = json.loads(rec_probs_json) if rec_probs_json else None
        hits.append(hit_rate(rec_nums, actual))
        top10s.append(top_k_accuracy(rec_nums, actual, 10))
        top15s.append(top_k_accuracy(rec_nums, actual, 15))
        top20s.append(top_k_accuracy(rec_nums, actual, 20))
        mrrs.append(mean_reciprocal_rank(rec_nums, actual))
        if rec_probs:
            briers.append(brier_score(rec_probs, actual, pool_size))
        m3, m4, m5, m6 = exact_match_counts(rec_nums, actual)
        em3.append(m3)
        em4.append(m4)
        em5.append(m5)
        em6.append(m6)

    def _mean(vals: Sequence[float]) -> float:
        return float(np.mean(vals)) if vals else 0.0

    return ScoreCard(
        predictor_name,
        window_size,
        datetime.now().isoformat(),
        len(rows),
        _mean(briers),
        _mean(hits),
        _mean(top10s),
        _mean(top15s),
        _mean(top20s),
        _mean(mrrs),
        _mean(em3),
        _mean(em4),
        _mean(em5),
        _mean(em6),
    )


def _upsert_scorecard(card: ScoreCard, db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    _ensure_schema(conn)
    conn.execute(
        "INSERT INTO scorecards VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(predictor_name, window_size) DO UPDATE SET last_updated=excluded.last_updated, draws_evaluated=excluded.draws_evaluated, brier_score=excluded.brier_score, hit_rate=excluded.hit_rate, top10_accuracy=excluded.top10_accuracy, top15_accuracy=excluded.top15_accuracy, top20_accuracy=excluded.top20_accuracy, mean_reciprocal_rank=excluded.mean_reciprocal_rank, exact_match_3=excluded.exact_match_3, exact_match_4=excluded.exact_match_4, exact_match_5=excluded.exact_match_5, exact_match_6=excluded.exact_match_6",
        (
            card.predictor_name,
            card.window_size,
            card.last_updated,
            card.draws_evaluated,
            card.brier_score,
            card.hit_rate,
            card.top10_accuracy,
            card.top15_accuracy,
            card.top20_accuracy,
            card.mean_reciprocal_rank,
            card.exact_match_3,
            card.exact_match_4,
            card.exact_match_5,
            card.exact_match_6,
        ),
    )
    conn.commit()
    conn.close()


def update_all_scorecards(db_path: Path = DB_PATH) -> list[ScoreCard]:
    conn = sqlite3.connect(str(db_path))
    _ensure_schema(conn)
    names = [
        r[0]
        for r in conn.execute("SELECT DISTINCT predictor_name FROM prediction_records").fetchall()
    ]
    conn.close()
    cards: list[ScoreCard] = []
    for name in names:
        for w in LEADERBOARD_WINDOWS:
            card = score_predictor(name, w, db_path)
            if card:
                cards.append(card)
                _upsert_scorecard(card, db_path)
    return cards


def get_leaderboard(window_size: int = 20, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT * FROM scorecards WHERE window_size=? ORDER BY hit_rate DESC, top15_accuracy DESC, brier_score ASC",
        (window_size,),
    ).fetchall()
    conn.close()
    cols = [
        "predictor_name",
        "window_size",
        "last_updated",
        "draws_evaluated",
        "brier_score",
        "hit_rate",
        "top10_accuracy",
        "top15_accuracy",
        "top20_accuracy",
        "mean_reciprocal_rank",
        "exact_match_3",
        "exact_match_4",
        "exact_match_5",
        "exact_match_6",
    ]
    return [dict(zip(cols, row[1:], strict=False)) for row in rows]


def get_hot_predictor(window_size: int = 20, db_path: Path = DB_PATH) -> str | None:
    board = get_leaderboard(window_size, db_path)
    return board[0]["predictor_name"] if board else None


def on_new_draw_fetched(
    draw_id: str, actual_numbers: list[int], actual_bonus: int | None, db_path: Path = DB_PATH
) -> dict[str, Any]:
    backfilled = backfill_actuals(draw_id, actual_numbers, actual_bonus, db_path)
    scorecards = update_all_scorecards(db_path)
    hot = get_hot_predictor(20, db_path)
    return {
        "draw_id": draw_id,
        "backfilled_predictions": backfilled,
        "scorecards_updated": len(scorecards),
        "hot_predictor_20": hot,
    }


if __name__ == "__main__":
    import tempfile

    tmp_db = Path(tempfile.mktemp(suffix=".db"))
    for i in range(1, 6):
        store_prediction(
            PredictionRecord(
                f"D{i:03d}",
                f"2026-01-{i:02d}",
                "dummy_freq",
                [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
                None,
                [3, 7, 12, 18, 25, 33],
                40,
            ),
            tmp_db,
        )
    result = on_new_draw_fetched("D005", [3, 7, 12, 18, 25, 33], 40, tmp_db)
    print("Self-test result:", result)
    print("Leaderboard (20):", get_leaderboard(20, tmp_db))
    tmp_db.unlink()
