"""Expand rotation_history Powerball CHECK to 1-14.

Revision ID: 005
Revises: 004
Create Date: 2026-10-30
"""

import sqlalchemy as sa

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def _rebuild_with_powerball_max(max_powerball: int) -> None:
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())
    if "rotation_history" not in existing:
        return

    sql = conn.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name='rotation_history'")
    ).scalar_one()
    target = f"BETWEEN 1 AND {max_powerball}"
    if target in sql:
        return

    old_count = conn.execute(sa.text("SELECT COUNT(*) FROM rotation_history")).scalar_one()
    op.create_table(
        "rotation_history_new",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("period", sa.Integer, nullable=False),
        sa.Column("numbers", sa.Text, nullable=False),
        sa.Column("powerball", sa.Integer, nullable=False),
        sa.CheckConstraint("period >= 1"),
        sa.CheckConstraint(f"powerball BETWEEN 1 AND {max_powerball}"),
    )
    op.execute(
        "INSERT INTO rotation_history_new (id, created_at, period, numbers, powerball) "
        "SELECT id, created_at, period, numbers, powerball FROM rotation_history"
    )
    new_count = conn.execute(sa.text("SELECT COUNT(*) FROM rotation_history_new")).scalar_one()
    if old_count != new_count:
        raise RuntimeError(f"rotation_history row count mismatch: {old_count} -> {new_count}")

    op.drop_table("rotation_history")
    op.rename_table("rotation_history_new", "rotation_history")


def upgrade() -> None:
    _rebuild_with_powerball_max(14)


def downgrade() -> None:
    _rebuild_with_powerball_max(10)
