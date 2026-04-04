"""Integration test fixtures — per-test Postgres database isolation + shared copilot fixtures.

Each test gets its own database with real migrations applied.
Databases are dropped on teardown. Session-scoped cleanup catches stragglers.

Requires: docker compose up -d postgres
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine


# ---------------------------------------------------------------------------
# Copilot / EventBus / Template fixtures (used by live integration tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def copilot_client():
    """Start a real Copilot CLI client backed by a subprocess.

    The client is shared across all tests in a single module to avoid
    paying the subprocess-startup cost per test.  Each test should create
    its own session.
    """
    from copilot import CopilotClient, SubprocessConfig  # type: ignore[import-not-found]

    cli_path = os.environ.get("COPILOT_CLI_PATH") or shutil.which("copilot")
    if not cli_path:
        pytest.skip("copilot-cli binary not found in PATH or COPILOT_CLI_PATH")

    client = CopilotClient(SubprocessConfig(cli_path=cli_path, use_stdio=True))
    try:
        await client.start()
    except Exception as exc:
        pytest.skip(f"copilot-cli not available: {exc}")
    yield client
    await client.stop()


@pytest.fixture
def event_bus():
    """A fresh EventBus for each test."""
    from backend.events import EventBus

    return EventBus()


@pytest.fixture
def template_loader():
    """TemplateLoader pointing at the project's templates directory."""
    from backend.swarm.template_loader import TemplateLoader

    return TemplateLoader(Path("src/templates"))


@pytest.fixture
def event_collector(event_bus):
    """Subscribe to an EventBus and accumulate (type, data) tuples."""
    events: list[tuple[str, dict]] = []
    event_bus.subscribe(lambda t, d: events.append((t, d)))
    return events


# ---------------------------------------------------------------------------
# Postgres database isolation fixtures
# ---------------------------------------------------------------------------

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
