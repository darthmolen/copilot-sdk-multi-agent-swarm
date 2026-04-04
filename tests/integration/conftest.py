"""Integration test fixtures — per-test Postgres database isolation.

Each test gets its own database with real migrations applied.
Databases are dropped on teardown. Session-scoped cleanup catches stragglers.

Requires: docker compose up -d postgres
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_URL",
    "postgresql+asyncpg://swarm:swarm@localhost:5432/postgres",
)
BASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://swarm:swarm@localhost:5432",
)
ALEMBIC_INI = str(Path(__file__).resolve().parents[2] / "alembic.ini")
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


def _run_alembic_upgrade(database_url: str) -> None:
    """Run alembic upgrade head against the given database (sync)."""
    from alembic import command
    from alembic.config import Config

    sync_url = database_url.replace("+asyncpg", "")
    config = Config(ALEMBIC_INI)
    config.set_main_option("sqlalchemy.url", sync_url)
    config.set_main_option("script_location", str(Path(PROJECT_ROOT) / "alembic"))
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db_engine():
    """Create ephemeral test database, run migrations, yield engine, drop on teardown."""
    db_name = f"test_{uuid4().hex[:12]}"
    test_url = f"{BASE_URL}/{db_name}"

    # Create test database
    admin_engine = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    # Run migrations
    _run_alembic_upgrade(test_url)

    # Yield engine for test
    engine = create_async_engine(test_url)
    yield engine
    await engine.dispose()

    # Drop test database
    admin_engine = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE "{db_name}" WITH (FORCE)'))
    await admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_databases():
    """Drop any leftover test_* databases after all tests complete."""
    yield
    sync_admin = ADMIN_URL.replace("+asyncpg", "")
    engine = create_engine(sync_admin, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT datname FROM pg_database WHERE datname LIKE 'test_%'"
        )).fetchall()
        for (db_name,) in rows:
            try:
                conn.execute(text(f'DROP DATABASE "{db_name}" WITH (FORCE)'))
            except Exception:
                pass
    engine.dispose()
