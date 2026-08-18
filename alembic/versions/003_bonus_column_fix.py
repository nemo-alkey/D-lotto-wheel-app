"""Bonus column fix for legacy draws tables.

Revision ID: 003
Revises: 002
Create Date: 2026-08-05

PROJECT_REVIEW.txt §4.2 [CRITICAL] — "Missing Bonus Column":
init_working_db() created the draws table WITHOUT a bonus column, causing
KeyError in load_draws() and 18 test failures. Databases created by that
legacy code path need the column added after the fact.

This migration inspects the draws table and, only if ``bonus`` is absent,
adds it as ``INTEGER`` with the CHECK (bonus BETWEEN 1 AND 40) constraint
from the canonical schema. The column is nullable so pre-existing rows
(which never recorded a bonus) remain valid; new inserts always provide
one. Databases already on the 001 schema are untouched.
"""

import sqlalchemy as sa

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def _draws_columns() -> list[str]:
    return [c["name"] for c in sa.inspect(op.get_bind()).get_columns("draws")]


def upgrade() -> None:
    if "bonus" in _draws_columns():
        return  # canonical schema already has it — nothing to fix

    # batch mode recreates the table on SQLite so the CHECK constraint
    # can be applied alongside the new column.
    with op.batch_alter_table("draws") as batch_op:
        batch_op.add_column(
            sa.Column(
                "bonus",
                sa.Integer,
                sa.CheckConstraint("bonus BETWEEN 1 AND 40"),
                nullable=True,
            )
        )


def downgrade() -> None:
    if "bonus" not in _draws_columns():
        return
    with op.batch_alter_table("draws") as batch_op:
        batch_op.drop_column("bonus")
