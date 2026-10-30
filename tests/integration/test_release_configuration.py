"""Regression tests for release-blocking path and deployment settings."""

from __future__ import annotations

from pathlib import Path

from config.settings import DB_PATH
from config_manager import get_settings
from database_engine import _absolute_sqlite_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_database_path_is_absolute_and_canonical() -> None:
    expected = PROJECT_ROOT / "data" / "lotto.db"
    assert Path(DB_PATH) == expected
    assert Path(DB_PATH).is_absolute()
    assert Path(get_settings().DB_PATH) == expected


def test_relative_sqlite_url_is_anchored_to_project_root() -> None:
    assert _absolute_sqlite_url("sqlite:///data/lotto.db") == f"sqlite:///{DB_PATH}"
    assert _absolute_sqlite_url("sqlite:///:memory:") == "sqlite:///:memory:"


def test_cd_mounts_persistent_volume_at_app_data() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "cd.yml").read_text(encoding="utf-8")
    entrypoint = (PROJECT_ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")

    assert workflow.count("-v lotto-data:/app/data") == 2
    assert "-v lotto-data:/data" not in workflow
    assert 'DATA_DIR="${DATA_DIR:-/app/data}"' in entrypoint


def test_check_numbers_ui_uses_current_powerball_pool() -> None:
    page = (
        PROJECT_ROOT / "mobile-frontend" / "src" / "pages" / "CheckNumbers.jsx"
    ).read_text(encoding="utf-8")

    assert "pb > 14" in page
    assert "Powerball (1-14)" in page
    assert 'max="14"' in page
    assert "pb > 10" not in page
