"""Add user_selected_wheels table (wheel_explorer.py).

Revision ID: 004
Revises: 003
Create Date: 2026-08-06
"""

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "user_selected_wheels" not in existing:
        op.create_table(
            "user_selected_wheels",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("wheel_key", sa.Text, nullable=False),
            sa.Column("system_number", sa.Integer),
            sa.Column("pool_size", sa.Integer, nullable=False),
            sa.Column("user_numbers", sa.Text),
            sa.Column("tickets_json", sa.Text, nullable=False),
            sa.Column("selected_at", sa.Text, nullable=False),
        )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "user_selected_wheels" in existing:
        op.drop_table("user_selected_wheels")
