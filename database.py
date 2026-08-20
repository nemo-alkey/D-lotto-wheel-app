## Modified By: Callam / CodeWhale
## Project: Lotto Generator
## Purpose of File: Database Initialization and Management
## Description:
## This file provides database functions using SQLAlchemy Core, supporting
## both SQLite (default) and PostgreSQL via the DATABASE_URL setting.
## All function signatures are backward-compatible with the old sqlite3 API.

from typing import Any

from sqlalchemy import (
    Column,
    Connection,
    Float,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    text,
)

from database_engine import get_engine

# ---------------------------------------------------------------------------
# Table metadata for schema introspection / creation
# ---------------------------------------------------------------------------
_metadata = MetaData()

_draws_table = Table(
    "draws",
    _metadata,
    Column("draw_id", Integer, primary_key=True),
    Column("draw_date", Text, nullable=False, unique=True),
    Column("numbers", Text, nullable=False),
    Column("bonus", Integer, nullable=False),
    Column("powerball", Integer, nullable=False),
)

_epochs_table = Table(
    "epochs",
    _metadata,
    Column("id", Integer, primary_key=True),
    Column("run_date", Text, nullable=False),
    Column("epoch", Integer, nullable=False),
    Column("loss", Float, nullable=False),
    Column("val_loss", Float, nullable=False),
    Column("binary_accuracy", Float, nullable=False),
    Column("val_binary_accuracy", Float, nullable=False),
    Column("auc", Float, nullable=False),
    Column("val_auc", Float, nullable=False),
    Column("mae", Float, nullable=False),
    Column("val_mae", Float, nullable=False),
)

# ---------------------------------------------------------------------------
# Syndicate tables (see syndicate.py)
# ---------------------------------------------------------------------------
_syndicates_table = Table(
    "syndicates",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("created_by", Integer, nullable=False),  # auth users.id
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("total_contribution", Float, nullable=False, server_default=text("0")),
)

_members_table = Table(
    "members",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("syndicate_id", Integer, nullable=False),
    Column("user_id", Integer, nullable=False),  # auth users.id
    Column("contribution_pct", Float, nullable=False),
    Column("email", Text),
    UniqueConstraint("syndicate_id", "user_id", name="uq_member_syndicate_user"),
)

_syndicate_tickets_table = Table(
    "syndicate_tickets",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("syndicate_id", Integer, nullable=False),
    Column("ticket_numbers", Text, nullable=False),  # JSON list of 6 ints
    Column("draw_id", Text, nullable=False),
    Column("contributor_splits", Text),  # JSON {user_id: pct}
)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------
def get_connection() -> Connection:
    """Return a SQLAlchemy Connection from the engine pool.

    Callers MUST call ``conn.close()`` or use a context manager.
    """
    engine = get_engine()
    return engine.connect()


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------
def initialize_database() -> None:
    """Ensure the 'draws' and 'epochs' tables exist (create if missing)."""
    engine = get_engine()
    # Create tables that don't exist yet
    _metadata.create_all(engine, checkfirst=True)


# ---------------------------------------------------------------------------
# Draw operations
# ---------------------------------------------------------------------------
def insert_draw(
    draw_date: str,
    numbers: list[int],
    bonus: int,
    powerball: int,
) -> int | None:
    """Insert a single draw record. Returns new draw_id, or None on error."""
    numbers_str = ",".join(str(n) for n in numbers)
    engine = get_engine()
    with engine.connect() as conn:
        try:
            # Get next draw_id
            result = conn.execute(text("SELECT COALESCE(MAX(draw_id), 0) FROM draws"))
            max_id = result.scalar()
            new_id = (max_id or 0) + 1

            conn.execute(
                text(
                    "INSERT INTO draws (draw_id, draw_date, numbers, bonus, powerball) "
                    "VALUES (:draw_id, :draw_date, :numbers, :bonus, :powerball)"
                ),
                {
                    "draw_id": new_id,
                    "draw_date": draw_date,
                    "numbers": numbers_str,
                    "bonus": bonus,
                    "powerball": powerball,
                },
            )
            conn.commit()
            return new_id
        except Exception as e:
            conn.rollback()
            print(f"Error inserting draw on {draw_date}: {e}")
            return None


def fetch_all_draws() -> list[dict[str, Any]]:
    """Fetch all draw records, ordered by date ascending."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT draw_date, numbers, bonus, powerball FROM draws ORDER BY draw_date ASC"
            )
        )
        rows = result.fetchall()
        draws_list = []
        for draw_date, nums_str, bonus, powerball in rows:
            try:
                num_list = [int(x) for x in str(nums_str).split(",")]
            except (ValueError, AttributeError):
                continue
            draws_list.append(
                {
                    "draw_date": draw_date,
                    "numbers": num_list,
                    "bonus": bonus,
                    "powerball": powerball,
                }
            )
        return draws_list


def fetch_recent_draws(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch the most recent `limit` draw records."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT draw_date, numbers, bonus, powerball "
                "FROM draws ORDER BY draw_date DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        rows = result.fetchall()
        draws_list = []
        for draw_date, nums_str, bonus, powerball in rows:
            try:
                num_list = [int(x) for x in str(nums_str).split(",")]
            except (ValueError, AttributeError):
                continue
            draws_list.append(
                {
                    "draw_date": draw_date,
                    "numbers": num_list,
                    "bonus": bonus,
                    "powerball": powerball,
                }
            )
        return draws_list


def fetch_draw_by_date(draw_date: str) -> dict[str, Any] | None:
    """Fetch a single draw by its date."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT draw_date, numbers, bonus, powerball "
                "FROM draws WHERE draw_date = :draw_date"
            ),
            {"draw_date": draw_date},
        )
        row = result.fetchone()
        if row:
            try:
                num_list = [int(x) for x in str(row[1]).split(",")]
            except (ValueError, AttributeError):
                return None
            return {
                "draw_date": row[0],
                "numbers": num_list,
                "bonus": row[2],
                "powerball": row[3],
            }
        return None


def draw_exists(draw_date: str) -> bool:
    """Return True if a draw with the given date already exists."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM draws WHERE draw_date = :draw_date"),
            {"draw_date": draw_date},
        )
        return result.fetchone() is not None


# ---------------------------------------------------------------------------
# Epoch metrics
# ---------------------------------------------------------------------------
def insert_epoch_metrics(
    run_date: str,
    epoch: int,
    loss: float,
    val_loss: float,
    binary_accuracy: float,
    val_binary_accuracy: float,
    auc: float,
    val_auc: float,
    mae: float,
    val_mae: float,
) -> int | None:
    """Insert a single epoch's training metrics. Returns row id or None."""
    engine = get_engine()
    with engine.connect() as conn:
        try:
            result = conn.execute(
                text(
                    "INSERT INTO epochs (run_date, epoch, loss, val_loss, "
                    "binary_accuracy, val_binary_accuracy, auc, val_auc, mae, val_mae) "
                    "VALUES (:run_date, :epoch, :loss, :val_loss, "
                    ":bin_acc, :val_bin_acc, :auc, :val_auc, :mae, :val_mae)"
                ),
                {
                    "run_date": run_date,
                    "epoch": epoch,
                    "loss": loss,
                    "val_loss": val_loss,
                    "bin_acc": binary_accuracy,
                    "val_bin_acc": val_binary_accuracy,
                    "auc": auc,
                    "val_auc": val_auc,
                    "mae": mae,
                    "val_mae": val_mae,
                },
            )
            conn.commit()
            return result.lastrowid
        except Exception as e:
            conn.rollback()
            print("Error inserting epoch metrics:", e)
            return None
