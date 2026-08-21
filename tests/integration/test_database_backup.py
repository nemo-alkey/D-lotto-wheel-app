"""Integration tests for database_backup.py (backup/restore/CLI)."""

from __future__ import annotations

import gzip
import os
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import database_backup as dbk

pytestmark = pytest.mark.integration


@pytest.fixture
def source_db(tmp_path: Path) -> Path:
    """A small valid SQLite database with known row counts."""
    db = tmp_path / "lotto.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE draws (draw_id INTEGER PRIMARY KEY, numbers TEXT)")
    conn.executemany(
        "INSERT INTO draws VALUES (?, ?)",
        [(i, f"1,2,3,4,5,{i}") for i in range(1, 11)],
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def backup_dir(tmp_path: Path) -> Path:
    return tmp_path / "backups"


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def test_create_backup_copies_and_verifies(source_db: Path, backup_dir: Path) -> None:
    dest = dbk.create_backup(source_db, backup_dir)
    assert dest.exists()
    assert dest.name.startswith("lotto_") and dest.suffix == ".db"
    assert dbk.verify_backup(dest)
    assert dbk._table_row_counts(dest) == {"draws": 10}


def test_create_backup_missing_source_raises(backup_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        dbk.create_backup(tmp_path / "nope.db", backup_dir)


def test_maintenance_compresses_old_backups(source_db: Path, backup_dir: Path) -> None:
    dest = dbk.create_backup(source_db, backup_dir)
    # Age the backup past the compression window.
    old = time.time() - (dbk.COMPRESS_AFTER_DAYS + 1) * 86400
    os.utime(dest, (old, old))

    dbk._maintain_backups(backup_dir)
    assert not dest.exists()
    gz = Path(str(dest) + ".gz")
    assert gz.exists()
    with gzip.open(gz, "rb") as fh:
        assert fh.read(16) == b"SQLite format 3\x00"


def test_maintenance_deletes_past_retention(source_db: Path, backup_dir: Path) -> None:
    dest = dbk.create_backup(source_db, backup_dir)
    old = time.time() - (dbk.RETENTION_DAYS + 1) * 86400
    os.utime(dest, (old, old))

    dbk._maintain_backups(backup_dir)
    assert list(backup_dir.glob("lotto_*.db*")) == []


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def test_restore_roundtrip(source_db: Path, backup_dir: Path) -> None:
    backup = dbk.create_backup(source_db, backup_dir)

    # Damage the "live" DB, then restore.
    conn = sqlite3.connect(source_db)
    conn.execute("DELETE FROM draws")
    conn.commit()
    conn.close()
    assert dbk._table_row_counts(source_db) == {"draws": 0}

    assert dbk.restore_backup(backup, source_db) is True
    assert dbk._table_row_counts(source_db) == {"draws": 10}

    # A .restore-<timestamp> safety copy was left next to the target.
    safety = list(source_db.parent.glob("lotto.db.restore-*"))
    assert len(safety) == 1


def test_restore_from_gzipped(source_db: Path, backup_dir: Path) -> None:
    backup = dbk.create_backup(source_db, backup_dir)
    gz = Path(str(backup) + ".gz")
    with open(backup, "rb") as src, gzip.open(gz, "wb") as dst:
        dst.write(src.read())

    target = source_db.parent / "restored.db"
    assert dbk.restore_backup(gz, target) is True
    assert dbk._table_row_counts(target) == {"draws": 10}


def test_restore_rejects_invalid_file(source_db: Path, backup_dir: Path, tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.db"
    bogus.write_text("not a database")
    assert dbk.restore_backup(bogus, source_db) is False


def test_restore_missing_file(source_db: Path, tmp_path: Path) -> None:
    assert dbk.restore_backup(tmp_path / "missing.db", source_db) is False


# ---------------------------------------------------------------------------
# Verify / list / schedule parsing
# ---------------------------------------------------------------------------


def test_verify_rejects_garbage(tmp_path: Path) -> None:
    bogus = tmp_path / "x.db"
    bogus.write_bytes(b"garbage")
    assert dbk.verify_backup(bogus) is False


def test_list_backups_days_filter(source_db: Path, backup_dir: Path) -> None:
    fresh = dbk.create_backup(source_db, backup_dir)
    stale = backup_dir / "lotto_20200101_000000.db"
    stale.write_bytes(fresh.read_bytes())
    old = time.time() - 40 * 86400
    os.utime(stale, (old, old))

    all_entries = dbk.list_backups(backup_dir)
    assert {e["name"] for e in all_entries} == {fresh.name, stale.name}

    recent = dbk.list_backups(backup_dir, days=30)
    assert {e["name"] for e in recent} == {fresh.name}


def test_parse_schedule() -> None:
    assert dbk.parse_schedule("02:00") == (2, 0)
    assert dbk.parse_schedule("23:45") == (23, 45)
    assert dbk.parse_schedule("bogus") == (2, 0)  # fallback


def test_next_run_time_is_future() -> None:
    assert dbk.next_run_time() > __import__("datetime").datetime.now()


# ---------------------------------------------------------------------------
# run_scheduled_backup + failure alerting
# ---------------------------------------------------------------------------


def test_run_scheduled_backup_success(source_db: Path, backup_dir: Path) -> None:
    dest = dbk.run_scheduled_backup(source_db, backup_dir)
    assert dest is not None and dest.exists()


def test_run_scheduled_backup_failure_alerts(
    backup_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(dbk, "_alert_failure", lambda s, b: sent.append(s))
    dest = dbk.run_scheduled_backup(tmp_path / "missing.db", backup_dir)
    assert dest is None
    assert sent, "failure should trigger an alert"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_backup_list_verify(
    source_db: Path,
    backup_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(dbk, "DEFAULT_DB", source_db)
    monkeypatch.setattr(dbk, "BACKUP_DIR", backup_dir)

    assert dbk.main(["backup", "--now"]) == 0
    out = capsys.readouterr().out
    assert "Backup created:" in out

    assert dbk.main(["list", "--days", "30"]) == 0
    out = capsys.readouterr().out
    assert "lotto_" in out

    backup_file = next(backup_dir.glob("lotto_*.db"))
    assert dbk.main(["verify", str(backup_file)]) == 0
    assert "VALID" in capsys.readouterr().out


def test_cli_restore(
    source_db: Path,
    backup_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backup = dbk.create_backup(source_db, backup_dir)
    target = source_db.parent / "cli_restored.db"
    assert dbk.main(["restore", str(backup), "--target", str(target)]) == 0
    assert dbk._table_row_counts(target) == {"draws": 10}


# ---------------------------------------------------------------------------
# /health integration
# ---------------------------------------------------------------------------


def test_health_includes_backup_check(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "backup" in resp.json()["checks"]
