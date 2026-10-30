import sqlite3

from rotation_scheduler import powerball_rotation, save_plan_db


def test_powerball_rotation_six_periods() -> None:
    assert powerball_rotation(6) == [3, 4, 5, 6, 7, 8]


def test_powerball_rotation_wraps_at_fourteen() -> None:
    assert powerball_rotation(4, start=13) == [13, 14, 1, 2]


def test_save_plan_db_uses_per_period_powerballs(tmp_path) -> None:
    schedule = [list(range(1, 12)) for _ in range(6)]
    db_path = tmp_path / "rotation.db"

    save_plan_db(schedule, db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        actual = [
            row[0] for row in conn.execute("SELECT powerball FROM rotation_history ORDER BY period")
        ]
    finally:
        conn.close()

    assert actual == [3, 4, 5, 6, 7, 8]
