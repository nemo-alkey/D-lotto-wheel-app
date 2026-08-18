"""Alembic environment configuration for NZ Lotto project.

Uses SQLAlchemy and supports SQLite (default) and PostgreSQL.
Reads DATABASE_URL from settings or environment, falling back to sqlite:///lotto.db.
"""

import os
import sys
from logging.config import fileConfig
from typing import cast

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from alembic import context

# Alembic Config object
config = context.config

# Set up logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM metadata (we use Core table definitions in migrations)
target_metadata = None


def _get_url() -> str:
    """Resolve the database URL from settings or environment."""
    try:
        from settings import settings

        url = getattr(settings, "database_url", None)
        if url:
            return cast(str, url)
    except ImportError:
        pass
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lotto.db")
    return f"sqlite:///{db_path}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to live database)."""
    url = _get_url()

    # Override the ini URL with our resolved URL
    config.set_main_option("sqlalchemy.url", url)

    from sqlalchemy import create_engine

    connectable = create_engine(url)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
