"""Complete schema — remaining application tables.

Revision ID: 002
Revises: 001
Create Date: 2026-08-05

Adds every table the application modules create lazily at runtime, so a
fresh install gets the full schema from migrations alone:

  - prediction_records, scorecards   (accuracy_tracker.py)
  - pos_neg_history                  (pos_neg_tracker.py)
  - syndicates, members, syndicate_tickets  (database.py / syndicate.py)
  - users                            (auth.py)
  - notifier_settings                (notifier.py)
  - rotation_history                 (rotation_scheduler.py)

Note: generated tickets/wheels are stored as JSON via scheduler.py
(settings.ticket_store), not in the database, so there are no
tickets/wheels tables here by design.

Each CREATE is guarded by an existence check: modules create these tables
themselves on first use, so databases that already ran them must not fail.
"""

import sqlalchemy as sa

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    # --- accuracy_tracker.py ---
    if "prediction_records" not in existing:
        op.create_table(
            "prediction_records",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("draw_id", sa.Text),
            sa.Column("draw_date", sa.Text),
            sa.Column("predictor_name", sa.Text),
            sa.Column("recommended_numbers", sa.Text),
            sa.Column("recommended_probs", sa.Text),
            sa.Column("actual_drawn_numbers", sa.Text),
            sa.Column("actual_bonus", sa.Integer),
            sa.Column("timestamp", sa.Text),
        )

    if "scorecards" not in existing:
        op.create_table(
            "scorecards",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("predictor_name", sa.Text),
            sa.Column("window_size", sa.Integer),
            sa.Column("last_updated", sa.Text),
            sa.Column("draws_evaluated", sa.Integer),
            sa.Column("brier_score", sa.Float),
            sa.Column("hit_rate", sa.Float),
            sa.Column("top10_accuracy", sa.Float),
            sa.Column("top15_accuracy", sa.Float),
            sa.Column("top20_accuracy", sa.Float),
            sa.Column("mean_reciprocal_rank", sa.Float),
            sa.Column("exact_match_3", sa.Float),
            sa.Column("exact_match_4", sa.Float),
            sa.Column("exact_match_5", sa.Float),
            sa.Column("exact_match_6", sa.Float),
            sa.UniqueConstraint("predictor_name", "window_size"),
        )

    # --- pos_neg_tracker.py ---
    if "pos_neg_history" not in existing:
        op.create_table(
            "pos_neg_history",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("draw_id", sa.Integer),
            sa.Column("classification_json", sa.Text, nullable=False),
            sa.Column("shift_detected", sa.Integer, nullable=False, server_default="0"),
            sa.Column("alert_message", sa.Text),
            sa.Column("timestamp", sa.Text, nullable=False),
        )

    # --- syndicate.py / database.py ---
    if "syndicates" not in existing:
        op.create_table(
            "syndicates",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("created_by", sa.Integer, nullable=False),
            sa.Column(
                "created_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")
            ),
            sa.Column(
                "total_contribution",
                sa.Float,
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if "members" not in existing:
        op.create_table(
            "members",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("syndicate_id", sa.Integer, nullable=False),
            sa.Column("user_id", sa.Integer, nullable=False),
            sa.Column("contribution_pct", sa.Float, nullable=False),
            sa.Column("email", sa.Text),
            sa.UniqueConstraint(
                "syndicate_id", "user_id", name="uq_member_syndicate_user"
            ),
        )

    if "syndicate_tickets" not in existing:
        op.create_table(
            "syndicate_tickets",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("syndicate_id", sa.Integer, nullable=False),
            sa.Column("ticket_numbers", sa.Text, nullable=False),
            sa.Column("draw_id", sa.Text, nullable=False),
            sa.Column("contributor_splits", sa.Text),
        )

    # --- auth.py ---
    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("username", sa.Text, nullable=False, unique=True),
            sa.Column("hashed_password", sa.Text, nullable=False),
            sa.Column("is_admin", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.Text, server_default=sa.text("datetime('now')")),
        )

    # --- notifier.py ---
    if "notifier_settings" not in existing:
        op.create_table(
            "notifier_settings",
            sa.Column("key", sa.Text, primary_key=True),
            sa.Column("value", sa.Text, nullable=False),
        )

    # --- rotation_scheduler.py ---
    if "rotation_history" not in existing:
        op.create_table(
            "rotation_history",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.Text, nullable=False),
            sa.Column("period", sa.Integer, nullable=False),
            sa.Column("numbers", sa.Text, nullable=False),
            sa.Column("powerball", sa.Integer, nullable=False),
            sa.CheckConstraint("period >= 1"),
            sa.CheckConstraint("powerball BETWEEN 1 AND 10"),
        )


def downgrade() -> None:
    existing = _existing_tables()
    for table in (
        "rotation_history",
        "notifier_settings",
        "users",
        "syndicate_tickets",
        "members",
        "syndicates",
        "pos_neg_history",
        "scorecards",
        "prediction_records",
    ):
        if table in existing:
            op.drop_table(table)
