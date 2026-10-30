"""Add draw number and rule era to draws.

Revision ID: 006
Revises: 005
Create Date: 2026-10-30
"""

import sqlalchemy as sa

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text("PRAGMA table_info(draws)"))}


def upgrade() -> None:
    columns = _columns()
    if "draw_number" not in columns:
        op.add_column("draws", sa.Column("draw_number", sa.Integer, nullable=True))
    if "rule_era" not in columns:
        op.add_column("draws", sa.Column("rule_era", sa.Text, nullable=True))

    op.execute(
        "UPDATE draws SET rule_era = CASE "
        "WHEN draw_date >= '2026-09-16' THEN 'post_2026_09_16' "
        "ELSE 'pre_2026_09_16' END "
        "WHERE rule_era IS NULL OR rule_era = ''"
    )


def downgrade() -> None:
    columns = _columns()
    with op.batch_alter_table("draws") as batch_op:
        if "rule_era" in columns:
            batch_op.drop_column("rule_era")
        if "draw_number" in columns:
            batch_op.drop_column("draw_number")
