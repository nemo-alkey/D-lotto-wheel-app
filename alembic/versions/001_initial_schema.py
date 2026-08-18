"""Initial schema — all core tables.

Revision ID: 001
Revises: None
Create Date: 2026-06-08
"""

import sqlalchemy as sa

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NZ Lotto draws
    op.create_table(
        "draws",
        sa.Column("draw_id", sa.Integer, primary_key=True),
        sa.Column("draw_date", sa.Text, nullable=False, unique=True),
        sa.Column("numbers", sa.Text, nullable=False),
        sa.Column("bonus", sa.Integer, nullable=False),
        sa.Column("powerball", sa.Integer, nullable=False),
    )

    # Deep learning epoch metrics
    op.create_table(
        "epochs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_date", sa.Text, nullable=False),
        sa.Column("epoch", sa.Integer, nullable=False),
        sa.Column("loss", sa.Float, nullable=False),
        sa.Column("val_loss", sa.Float, nullable=False),
        sa.Column("binary_accuracy", sa.Float, nullable=False),
        sa.Column("val_binary_accuracy", sa.Float, nullable=False),
        sa.Column("auc", sa.Float, nullable=False),
        sa.Column("val_auc", sa.Float, nullable=False),
        sa.Column("mae", sa.Float, nullable=False),
        sa.Column("val_mae", sa.Float, nullable=False),
    )

    # International lottery draws
    op.create_table(
        "intl_draws",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("draw_date", sa.Text),
        sa.Column("lottery_name", sa.Text),
        sa.Column("numbers", sa.Text),
        sa.Column("bonus", sa.Integer),
        sa.Column("powerball", sa.Integer),
        sa.Column("fetched_at", sa.Text, server_default=sa.text("datetime('now')")),
    )

    # Data pipeline stats
    op.create_table(
        "pipeline_stats",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_time", sa.Text, server_default=sa.text("datetime('now')")),
        sa.Column("source_used", sa.Text),
        sa.Column("draw_date", sa.Text),
        sa.Column("success", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("pipeline_stats")
    op.drop_table("intl_draws")
    op.drop_table("epochs")
    op.drop_table("draws")
