"""Smoke test: verify per-test DB fixture + migrations work."""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db


async def test_db_engine_creates_isolated_database(db_engine):
    """Fixture creates a fresh DB with all tables from migrations."""
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
        )
        tables = [row[0] for row in result]

    assert "swarms" in tables
    assert "tasks" in tables
    assert "agents" in tables
    assert "messages" in tables
    assert "events" in tables
    assert "files" in tables
    assert "alembic_version" in tables


async def test_two_tests_get_different_databases(db_engine):
    """Each test gets its own DB — inserting here doesn't affect other tests."""
    async with db_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO swarms (id, goal) VALUES ('00000000-0000-0000-0000-000000000001', 'test')")
        )
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM swarms"))
        count = result.scalar()
    assert count == 1
