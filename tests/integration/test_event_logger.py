"""EventLogger integration tests — real Postgres."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.db.event_logger import EventLogger
from backend.db.repository import SwarmRepository
from backend.events import EventBus

pytestmark = pytest.mark.db


async def test_event_logger_persists_events(db_engine):
    repo = SwarmRepository(db_engine)
    logger = EventLogger(db_engine)
    swarm_id = uuid4()

    await repo.create_swarm(swarm_id, goal="Test")
    await logger.log_event("task.created", {"task_id": "t1", "swarm_id": str(swarm_id)})

    events = await repo.get_events(swarm_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "task.created"


async def test_event_logger_as_bus_subscriber(db_engine):
    repo = SwarmRepository(db_engine)
    logger = EventLogger(db_engine)
    bus = EventBus()
    bus.subscribe(logger.on_event)
    swarm_id = uuid4()

    await repo.create_swarm(swarm_id, goal="Test")
    await bus.emit("task.created", {"swarm_id": str(swarm_id), "task": {"id": "t1"}})

    events = await repo.get_events(swarm_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "task.created"


async def test_event_logger_skips_sdk_events(db_engine):
    """sdk_event type should not be persisted (non-serializable)."""
    logger = EventLogger(db_engine)
    await logger.log_event("sdk_event", {"agent": "test"})

    SwarmRepository(db_engine)
    # No swarm_id to query, but we can check the events table is empty
    from sqlalchemy import text

    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM events"))
        assert result.scalar() == 0
