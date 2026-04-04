"""Alembic environment configuration.

Supports DATABASE_URL env var override for the connection string,
falling back to alembic.ini's sqlalchemy.url.
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from backend.db.tables import metadata as target_metadata

config = context.config

# Override sqlalchemy.url from environment if set
db_url = os.environ.get("DATABASE_URL", "")
if db_url:
    # Alembic needs sync driver — strip +asyncpg
    config.set_main_option("sqlalchemy.url", db_url.replace("+asyncpg", ""))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
