"""SwarmRepository integration tests — real Postgres, real migrations."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.db.repository import SwarmRepository

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# Swarms
# ---------------------------------------------------------------------------


async def test_create_and_get_swarm(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Build a dashboard", template_key="deep-research")

    swarm = await repo.get_swarm(swarm_id)
    assert swarm is not None
    assert swarm["goal"] == "Build a dashboard"
    assert swarm["phase"] == "starting"
    assert swarm["template_key"] == "deep-research"


async def test_get_swarm_returns_none_for_missing(db_engine):
    repo = SwarmRepository(db_engine)
    assert await repo.get_swarm(uuid4()) is None


async def test_update_phase(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Test")
    await repo.update_phase(swarm_id, "planning")

    swarm = await repo.get_swarm(swarm_id)
    assert swarm["phase"] == "planning"


async def test_update_swarm_report(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Test")
    await repo.update_swarm(swarm_id, report="# Final Report", phase="complete")

    swarm = await repo.get_swarm(swarm_id)
    assert swarm["report"] == "# Final Report"
    assert swarm["phase"] == "complete"
    assert swarm["completed_at"] is not None


async def test_update_qa_refined_goal(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Original")
    await repo.update_swarm(swarm_id, qa_refined_goal="Refined after QA")

    swarm = await repo.get_swarm(swarm_id)
    assert swarm["qa_refined_goal"] == "Refined after QA"


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


async def test_create_and_get_tasks(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Test")
    await repo.create_task(
        swarm_id,
        task_id="task-0",
        subject="Analyze data",
        description="Run analysis",
        worker_role="analyst",
        worker_name="analyst",
        blocked_by=[],
    )
    await repo.create_task(
        swarm_id,
        task_id="task-1",
        subject="Write report",
        description="Write up",
        worker_role="writer",
        worker_name="writer",
        blocked_by=["task-0"],
    )

    tasks = await repo.get_tasks(swarm_id)
    assert len(tasks) == 2
    t0 = next(t for t in tasks if t["id"] == "task-0")
    t1 = next(t for t in tasks if t["id"] == "task-1")
    assert t0["blocked_by"] == []
    assert t1["blocked_by"] == ["task-0"]


async def test_update_task_status(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Test")
    await repo.create_task(
        swarm_id,
        task_id="task-0",
        subject="Work",
        description="Do it",
        worker_role="dev",
        worker_name="dev",
    )

    await repo.update_task_status(swarm_id, "task-0", "completed", result="Done!")

    tasks = await repo.get_tasks(swarm_id)
    assert tasks[0]["status"] == "completed"
    assert tasks[0]["result"] == "Done!"


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


async def test_register_and_get_agent(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Test")
    await repo.register_agent(
        swarm_id,
        name="analyst",
        role="Data Analyst",
        display_name="Analyst",
        session_id="sess-abc-123",
    )

    agent = await repo.get_agent(swarm_id, "analyst")
    assert agent is not None
    assert agent["session_id"] == "sess-abc-123"
    assert agent["status"] == "idle"
    assert agent["tasks_completed"] == 0


async def test_update_agent_status(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Test")
    await repo.register_agent(swarm_id, name="dev", role="Dev", display_name="Dev")
    await repo.update_agent(swarm_id, "dev", status="working", tasks_completed=2)

    agent = await repo.get_agent(swarm_id, "dev")
    assert agent["status"] == "working"
    assert agent["tasks_completed"] == 2


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


async def test_save_and_get_messages(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Test")
    await repo.save_message(swarm_id, sender="analyst", recipient="writer", content="Here are results")
    await repo.save_message(swarm_id, sender="writer", recipient="analyst", content="Thanks!")

    messages = await repo.get_messages(swarm_id)
    assert len(messages) == 2
    assert messages[0]["content"] == "Here are results"
    assert messages[1]["content"] == "Thanks!"


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


async def test_save_and_get_files(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Test")
    await repo.save_file(swarm_id, path="analysis.md", size_bytes=1024)
    await repo.save_file(swarm_id, path="report.md", size_bytes=2048)

    files = await repo.get_files(swarm_id)
    assert len(files) == 2
    paths = {f["path"] for f in files}
    assert paths == {"analysis.md", "report.md"}


async def test_save_file_unique_constraint(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Test")
    await repo.save_file(swarm_id, path="same.md", size_bytes=100)
    # Upsert or ignore — should not raise
    await repo.save_file(swarm_id, path="same.md", size_bytes=200)

    files = await repo.get_files(swarm_id)
    assert len(files) == 1


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


async def test_save_and_get_events(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.save_event(swarm_id, "task.created", {"task_id": "t1"})
    await repo.save_event(swarm_id, "task.updated", {"task_id": "t1", "status": "completed"})

    events = await repo.get_events(swarm_id)
    assert len(events) == 2
    assert events[0]["event_type"] == "task.created"


async def test_get_events_since(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.save_event(swarm_id, "first", {})

    # Get the timestamp of the first event
    events = await repo.get_events(swarm_id)
    first_ts = events[0]["created_at"]

    await repo.save_event(swarm_id, "second", {})
    await repo.save_event(swarm_id, "third", {})

    recent = await repo.get_events(swarm_id, since=first_ts)
    assert len(recent) == 2  # second + third (after first)


# ---------------------------------------------------------------------------
# Full state load
# ---------------------------------------------------------------------------


async def test_load_full_swarm_state(db_engine):
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()
    await repo.create_swarm(swarm_id, goal="Full test", template_key="azure")
    await repo.update_phase(swarm_id, "executing")
    await repo.create_task(
        swarm_id,
        task_id="task-0",
        subject="Analyze",
        description="Do analysis",
        worker_role="analyst",
        worker_name="analyst",
    )
    await repo.register_agent(
        swarm_id,
        name="analyst",
        role="Analyst",
        display_name="Analyst Agent",
        session_id="sess-1",
    )
    await repo.save_message(swarm_id, sender="leader", recipient="analyst", content="Go")
    await repo.save_file(swarm_id, path="output.md", size_bytes=500)

    state = await repo.load_swarm_state(swarm_id)

    assert state["swarm"]["phase"] == "executing"
    assert len(state["tasks"]) == 1
    assert len(state["agents"]) == 1
    assert state["agents"][0]["session_id"] == "sess-1"
    assert len(state["messages"]) == 1
    assert len(state["files"]) == 1


# ---------------------------------------------------------------------------
# List swarms
# ---------------------------------------------------------------------------


async def test_list_swarms(db_engine):
    repo = SwarmRepository(db_engine)
    id1, id2 = uuid4(), uuid4()
    await repo.create_swarm(id1, goal="First")
    await repo.create_swarm(id2, goal="Second")

    swarms = await repo.list_swarms()
    assert len(swarms) == 2
