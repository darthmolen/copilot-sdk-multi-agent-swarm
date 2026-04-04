"""Alembic environment configuration -- async SQLAlchemy (asyncpg).

Reads DATABASE_URL from the environment.  The URL must use the
``postgresql+asyncpg://`` scheme.  If not set, falls back to whatever
``sqlalchemy.url`` is in alembic.ini (which must use the *sync* driver
``postgresql://``).
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from backend.db.tables import metadata as target_metadata

# -- Alembic Config object ---------------------------------------------------
config = context.config

# Override sqlalchemy.url from environment if set
db_url = os.environ.get("DATABASE_URL", "")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# -- Offline (SQL-script) mode -----------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode -- emits SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# -- Online (async engine) mode ----------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    """Configure context and run migrations inside a sync callback."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode -- connects to the database."""
    asyncio.run(run_async_migrations())


# -- Entrypoint ---------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
