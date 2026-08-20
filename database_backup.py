#!/usr/bin/env python3
"""
database_backup.py — Automated backup and restore for the lotto SQLite DB.

Backup uses SQLite's Online Backup API (Connection.backup), so a consistent
snapshot is taken even while the API is writing to the live database
(WAL-safe). Every backup is integrity-checked before it is considered
valid. Old backups are gzip-compressed after 7 days and deleted after
BACKUP_RETENTION_DAYS (default 30).

Configuration (environment variables):
  BACKUP_DIR                  Backup destination (default: backups/)
  BACKUP_RETENTION_DAYS       Delete backups older than this (default: 30)
  BACKUP_COMPRESS_AFTER_DAYS  Gzip backups older than this (default: 7)
  BACKUP_SCHEDULE             Daily backup time "HH:MM" (default: 02:00)
  BACKUP_S3_BUCKET            S3 bucket for off-site copies (optional)
  BACKUP_AZURE_CONTAINER      Azure Blob container for off-site copies (optional)

CLI:
  python database_backup.py backup [--now]
  python database_backup.py restore <backup_file>
  python database_backup.py list [--days 30]
  python database_backup.py verify <backup_file>
  python database_backup.py daemon        # loop honoring BACKUP_SCHEDULE

All operations are logged to data/logs/backup.log; failures trigger an
email alert via notifier.py when SMTP is configured.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", _ROOT / "backups"))
COMPRESS_AFTER_DAYS = int(os.environ.get("BACKUP_COMPRESS_AFTER_DAYS", "7"))
BACKUP_SCHEDULE = os.environ.get("BACKUP_SCHEDULE", "02:00")

# Canonical app config (config/settings.py).
from config_manager import get_settings

_app_cfg = get_settings()
RETENTION_DAYS = _app_cfg.BACKUP_RETENTION_DAYS

_S3_BUCKET = os.environ.get("BACKUP_S3_BUCKET", "")
_S3_PREFIX = "lotto-backups/"
_AZURE_CONTAINER = os.environ.get("BACKUP_AZURE_CONTAINER", "")

try:
    from settings import settings

    DEFAULT_DB = Path(settings.db_path)
except ImportError:
    DEFAULT_DB = Path(os.environ.get("DB_PATH", _ROOT / "lotto.db"))

# ---------------------------------------------------------------------------
# Logging — data/logs/backup.log (rotating)
# ---------------------------------------------------------------------------

_LOG_DIR = _ROOT / "data" / "logs"


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("backup")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        _LOG_DIR / "backup.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
        )
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


log = _get_logger()


def _alert_failure(subject: str, body: str) -> None:
    """Email alert on backup failure (no-op when SMTP isn't configured)."""
    try:
        from notifier import send_email_alert

        send_email_alert(subject, body)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _verify_integrity(db_path: Path) -> bool:
    """Run PRAGMA integrity_check; True when the database is consistent."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        return bool(result) and result[0] == "ok"
    except sqlite3.Error:
        return False


def _is_sqlite_db(path: Path) -> bool:
    """Check the SQLite magic header ('SQLite format 3\\0')."""
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _table_row_counts(db_path: Path) -> dict[str, int]:
    """Row counts for every user table in the database."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables
        }
    finally:
        conn.close()


def _decompress_if_needed(path: Path, work_dir: Path) -> Path:
    """Return a plain .db path; decompresses .gz inputs into work_dir."""
    if path.suffix != ".gz":
        return path
    out = work_dir / path.stem  # strip .gz
    with gzip.open(path, "rb") as src, open(out, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return out


# ---------------------------------------------------------------------------
# A) Backup
# ---------------------------------------------------------------------------


def create_backup(source_db: Path, backup_dir: Path) -> Path:
    """Create a timestamped, integrity-verified backup of source_db.

    Uses the SQLite Online Backup API for a consistent snapshot, then runs
    maintenance: gzip-compresses backups older than COMPRESS_AFTER_DAYS and
    deletes backups older than RETENTION_DAYS.

    Args:
        source_db: Path to the live SQLite database.
        backup_dir: Directory for backup files (created if missing).

    Returns:
        Path to the new backup file (backups/lotto_YYYYMMDD_HHMMSS.db).

    Raises:
        FileNotFoundError: if source_db does not exist.
        RuntimeError: if the backup fails its integrity check.
    """
    source_db = Path(source_db)
    backup_dir = Path(backup_dir)
    if not source_db.exists():
        raise FileNotFoundError(f"Source database not found: {source_db}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"lotto_{_timestamp()}.db"

    log.info("backup_start source=%s dest=%s", source_db, dest)
    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)  # Online Backup API: consistent live copy
        finally:
            dst.close()
    finally:
        src.close()

    if not _verify_integrity(dest):
        dest.unlink(missing_ok=True)
        log.error("backup_integrity_failed dest=%s", dest)
        raise RuntimeError(f"Backup failed integrity check: {dest}")

    size_kb = dest.stat().st_size / 1024
    log.info("backup_complete dest=%s size_kb=%.1f", dest, size_kb)

    _maintain_backups(backup_dir)
    return dest


def _maintain_backups(backup_dir: Path) -> None:
    """Gzip backups older than COMPRESS_AFTER_DAYS; delete past retention."""
    now = time.time()
    compress_before = now - COMPRESS_AFTER_DAYS * 86400
    delete_before = now - RETENTION_DAYS * 86400

    for path in sorted(backup_dir.glob("lotto_*.db")):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < delete_before:
            path.unlink(missing_ok=True)
            log.info("backup_expired_deleted path=%s", path)
        elif mtime < compress_before:
            gz_path = path.with_suffix(path.suffix + ".gz")
            with open(path, "rb") as src, gzip.open(gz_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
            log.info("backup_compressed path=%s", gz_path)

    for path in sorted(backup_dir.glob("lotto_*.db.gz")):
        try:
            if path.stat().st_mtime < delete_before:
                path.unlink(missing_ok=True)
                log.info("backup_expired_deleted path=%s", path)
        except OSError:
            continue


# ---------------------------------------------------------------------------
# B) Restore
# ---------------------------------------------------------------------------


def restore_backup(backup_path: Path, target_db: Path) -> bool:
    """Restore target_db from a backup file (.db or .db.gz).

    Validates the backup (exists, SQLite magic header, integrity check),
    snapshots the current database to <name>.restore-<timestamp> before
    overwriting, restores via the Online Backup API, and verifies that
    per-table row counts match the backup.

    Returns:
        True on success, False on any validation/verification failure.
    """
    backup_path = Path(backup_path)
    target_db = Path(target_db)

    if not backup_path.exists():
        log.error("restore_failed reason=missing backup=%s", backup_path)
        return False

    with tempfile.TemporaryDirectory(prefix="lotto_restore_") as tmp:
        source = _decompress_if_needed(backup_path, Path(tmp))

        if not _is_sqlite_db(source):
            log.error("restore_failed reason=not_sqlite backup=%s", backup_path)
            return False
        if not _verify_integrity(source):
            log.error("restore_failed reason=corrupt backup=%s", backup_path)
            return False

        expected_counts = _table_row_counts(source)

        # Safety copy of the current database before overwriting.
        if target_db.exists():
            safety = target_db.with_name(f"{target_db.name}.restore-{_timestamp()}")
            shutil.copy2(target_db, safety)
            log.info("restore_presnapshot path=%s", safety)

        log.info("restore_start backup=%s target=%s", backup_path, target_db)
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(str(target_db))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

    actual_counts = _table_row_counts(target_db)
    if actual_counts != expected_counts:
        log.error(
            "restore_failed reason=row_count_mismatch expected=%s actual=%s",
            expected_counts,
            actual_counts,
        )
        return False

    log.info(
        "restore_complete target=%s tables=%d rows=%d",
        target_db,
        len(actual_counts),
        sum(actual_counts.values()),
    )
    return True


# ---------------------------------------------------------------------------
# C) Scheduled backups
# ---------------------------------------------------------------------------


def run_scheduled_backup(
    source_db: Path | None = None, backup_dir: Path | None = None
) -> Path | None:
    """Run one backup cycle — the entry point for cron/scheduler invocations.

    Logs the outcome and emails an alert on failure. Also attempts the
    optional cloud upload (S3/Azure) when credentials are configured.

    Returns:
        The backup path on success, None on failure.
    """
    source_db = Path(source_db or DEFAULT_DB)
    backup_dir = Path(backup_dir or BACKUP_DIR)
    if not _app_cfg.BACKUP_ENABLED:
        log.info("scheduled_backup_skipped reason=BACKUP_ENABLED=false")
        return None
    try:
        dest = create_backup(source_db, backup_dir)
    except Exception as exc:
        log.error("scheduled_backup_failed source=%s error=%s", source_db, exc)
        _alert_failure(
            "Lotto DB backup failed",
            f"Scheduled backup of {source_db} failed:\n{exc}",
        )
        return None

    uploaded = upload_to_cloud(dest)
    if uploaded:
        log.info("backup_uploaded dest=%s targets=%s", dest, uploaded)
    return dest


def parse_schedule(schedule: str = BACKUP_SCHEDULE) -> tuple[int, int]:
    """Parse BACKUP_SCHEDULE ('HH:MM', daily) into (hour, minute)."""
    try:
        hour_str, minute_str = schedule.strip().split(":")
        hour, minute = int(hour_str), int(minute_str)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except ValueError:
        log.warning("invalid BACKUP_SCHEDULE=%r, falling back to 02:00", schedule)
        return 2, 0


def next_run_time(schedule: str = BACKUP_SCHEDULE) -> datetime:
    """Next local datetime the schedule fires (daily at HH:MM)."""
    hour, minute = parse_schedule(schedule)
    now = datetime.now()
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def schedule_loop() -> None:
    """Run backups forever at the BACKUP_SCHEDULE time each day."""
    log.info("backup_daemon_started schedule=%s", BACKUP_SCHEDULE)
    while True:
        wait = (next_run_time() - datetime.now()).total_seconds()
        log.info("backup_daemon_next_run in_seconds=%d", int(wait))
        time.sleep(max(wait, 1))
        run_scheduled_backup()


# ---------------------------------------------------------------------------
# E) Optional cloud upload (S3 / Azure Blob, exponential backoff)
# ---------------------------------------------------------------------------


def _with_retry(fn: Callable[[], Any], description: str, attempts: int = 3) -> bool:
    """Run fn() with exponential backoff (1s, 2s, 4s). True on success."""
    for attempt in range(1, attempts + 1):
        try:
            fn()
            return True
        except Exception as exc:
            log.warning(
                "cloud_upload_retry target=%s attempt=%d/%d error=%s",
                description,
                attempt,
                attempts,
                exc,
            )
            if attempt < attempts:
                time.sleep(2 ** (attempt - 1))
    log.error("cloud_upload_failed target=%s", description)
    return False


def upload_to_cloud(backup_path: Path) -> list[str]:
    """Upload to S3 and/or Azure when credentials are present.

    Requires BACKUP_S3_BUCKET + AWS credentials (boto3) and/or
    BACKUP_AZURE_CONTAINER + AZURE_STORAGE_CONNECTION_STRING
    (azure-storage-blob). Missing SDKs or credentials are skipped quietly.

    Returns:
        List of upload targets that succeeded (e.g. ["s3", "azure"]).
    """
    backup_path = Path(backup_path)
    succeeded: list[str] = []

    if _S3_BUCKET and os.environ.get("AWS_ACCESS_KEY_ID"):
        try:
            import boto3
        except ImportError:
            log.warning("s3_upload_skipped reason=boto3_not_installed")
        else:
            key = f"{_S3_PREFIX}{backup_path.name}"

            def _s3() -> None:
                boto3.client("s3").upload_file(str(backup_path), _S3_BUCKET, key)

            if _with_retry(_s3, f"s3://{_S3_BUCKET}/{key}"):
                succeeded.append("s3")

    azure_conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if _AZURE_CONTAINER and azure_conn:
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError:
            log.warning("azure_upload_skipped reason=sdk_not_installed")
        else:

            def _azure() -> None:
                service = BlobServiceClient.from_connection_string(azure_conn)
                blob = service.get_blob_client(
                    container=_AZURE_CONTAINER, blob=backup_path.name
                )
                with open(backup_path, "rb") as fh:
                    blob.upload_blob(fh, overwrite=True)

            if _with_retry(_azure, f"azure://{_AZURE_CONTAINER}/{backup_path.name}"):
                succeeded.append("azure")

    return succeeded


# ---------------------------------------------------------------------------
# Listing / verification (CLI support)
# ---------------------------------------------------------------------------


def list_backups(
    backup_dir: Path | None = None, days: int | None = None
) -> list[dict[str, Any]]:
    """List backups newest-first with size and age metadata.

    Args:
        backup_dir: Directory to scan (default BACKUP_DIR).
        days: Only include backups from the last N days (None = all).
    """
    backup_dir = Path(backup_dir or BACKUP_DIR)
    cutoff = time.time() - days * 86400 if days is not None else None
    entries: list[dict[str, Any]] = []
    for pattern in ("lotto_*.db", "lotto_*.db.gz"):
        for path in backup_dir.glob(pattern):
            try:
                stat = path.stat()
            except OSError:
                continue
            if cutoff is not None and stat.st_mtime < cutoff:
                continue
            entries.append(
                {
                    "path": path,
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_mtime),
                    "compressed": path.suffix == ".gz",
                }
            )
    entries.sort(key=lambda e: e["created"], reverse=True)
    return entries


def verify_backup(backup_path: Path) -> bool:
    """True when the file is a valid, integrity-checked SQLite database."""
    backup_path = Path(backup_path)
    if not backup_path.exists():
        return False
    with tempfile.TemporaryDirectory(prefix="lotto_verify_") as tmp:
        source = _decompress_if_needed(backup_path, Path(tmp))
        return _is_sqlite_db(source) and _verify_integrity(source)


# ---------------------------------------------------------------------------
# D) CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backup and restore for the lotto SQLite database."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="Create a backup now")
    p_backup.add_argument(
        "--now",
        action="store_true",
        help="Run immediately (default behavior; flag accepted for clarity)",
    )

    p_restore = sub.add_parser("restore", help="Restore from a backup file")
    p_restore.add_argument("backup_file", type=Path)
    p_restore.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_DB,
        help=f"Database to overwrite (default: {DEFAULT_DB})",
    )

    p_list = sub.add_parser("list", help="List available backups")
    p_list.add_argument(
        "--days", type=int, default=None, help="Only show backups from the last N days"
    )

    p_verify = sub.add_parser("verify", help="Integrity-check a backup file")
    p_verify.add_argument("backup_file", type=Path)

    sub.add_parser("daemon", help="Run forever, backing up daily at BACKUP_SCHEDULE")

    args = parser.parse_args(argv)

    if args.command == "backup":
        dest = run_scheduled_backup()
        if dest is None:
            print("Backup FAILED — see data/logs/backup.log", file=sys.stderr)
            return 1
        print(f"Backup created: {dest}")
        return 0

    if args.command == "restore":
        ok = restore_backup(args.backup_file, args.target)
        print("Restore OK" if ok else "Restore FAILED — see data/logs/backup.log")
        return 0 if ok else 1

    if args.command == "list":
        entries = list_backups(days=args.days)
        if not entries:
            print("No backups found.")
            return 0
        for e in entries:
            size_kb = e["size_bytes"] / 1024
            tag = " (gzipped)" if e["compressed"] else ""
            print(
                f"{e['created']:%Y-%m-%d %H:%M:%S}  {size_kb:9.1f} KB  "
                f"{e['name']}{tag}"
            )
        return 0

    if args.command == "verify":
        ok = verify_backup(args.backup_file)
        print(f"{args.backup_file}: {'VALID' if ok else 'INVALID'}")
        return 0 if ok else 1

    if args.command == "daemon":
        schedule_loop()
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
