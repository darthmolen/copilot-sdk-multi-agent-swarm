"""TDD tests for TeamRegistry — Red/Green for each behaviour."""

from __future__ import annotations

import asyncio

import pytest

from backend.swarm.models import AgentInfo, AgentStatus
from backend.swarm.team_registry import TeamRegistry


# ---------------------------------------------------------------------------
# 1. register + get_all returns agent with correct name/role/status (IDLE)
# ---------------------------------------------------------------------------


async def test_register_and_get_all_returns_agent_with_defaults() -> None:
    registry = TeamRegistry()
    agent = await registry.register("planner", "orchestrator")

    assert isinstance(agent, AgentInfo)
    assert agent.name == "planner"
    assert agent.role == "orchestrator"
    assert agent.status == AgentStatus.IDLE
    assert agent.display_name == "planner"  # default = name

    all_agents = await registry.get_all()
    assert len(all_agents) == 1
    assert all_agents[0].name == "planner"


async def test_register_with_explicit_display_name() -> None:
    registry = TeamRegistry()
    agent = await registry.register("coder", "developer", display_name="The Coder")

    assert agent.display_name == "The Coder"


# ---------------------------------------------------------------------------
# 2. get_agent returns specific agent; raises KeyError when not found
# ---------------------------------------------------------------------------


async def test_get_agent_returns_specific_agent() -> None:
    registry = TeamRegistry()
    await registry.register("searcher", "researcher")

    agent = await registry.get_agent("searcher")
    assert agent.name == "searcher"
    assert agent.role == "researcher"


async def test_get_agent_raises_key_error_for_missing() -> None:
    registry = TeamRegistry()

    with pytest.raises(KeyError, match="not found"):
        await registry.get_agent("ghost")


# ---------------------------------------------------------------------------
# 3. update_status changes agent status
# ---------------------------------------------------------------------------


async def test_update_status_changes_status() -> None:
    registry = TeamRegistry()
    await registry.register("worker", "coder")

    updated = await registry.update_status("worker", "working")
    assert updated.status == AgentStatus.WORKING

    # Confirm it persisted
    agent = await registry.get_agent("worker")
    assert agent.status == AgentStatus.WORKING


# ---------------------------------------------------------------------------
# 4. increment_tasks_completed increments the counter
# ---------------------------------------------------------------------------


async def test_increment_tasks_completed() -> None:
    registry = TeamRegistry()
    await registry.register("worker", "coder")

    updated = await registry.increment_tasks_completed("worker")
    assert updated.tasks_completed == 1

    updated = await registry.increment_tasks_completed("worker")
    assert updated.tasks_completed == 2

    agent = await registry.get_agent("worker")
    assert agent.tasks_completed == 2


# ---------------------------------------------------------------------------
# 5. Multiple agents can be registered and retrieved
# ---------------------------------------------------------------------------


async def test_multiple_agents() -> None:
    registry = TeamRegistry()
    await registry.register("planner", "orchestrator")
    await registry.register("coder", "developer")
    await registry.register("reviewer", "qa")

    all_agents = await registry.get_all()
    assert len(all_agents) == 3

    names = {a.name for a in all_agents}
    assert names == {"planner", "coder", "reviewer"}

    coder = await registry.get_agent("coder")
    assert coder.role == "developer"


# ---------------------------------------------------------------------------
# 6. Concurrent access — two async updates don't corrupt state
# ---------------------------------------------------------------------------


async def test_concurrent_increments_are_safe() -> None:
    registry = TeamRegistry()
    await registry.register("worker", "coder")

    async def bump() -> None:
        for _ in range(50):
            await registry.increment_tasks_completed("worker")

    await asyncio.gather(bump(), bump())

    agent = await registry.get_agent("worker")
    assert agent.tasks_completed == 100


async def test_concurrent_status_updates_are_safe() -> None:
    registry = TeamRegistry()
    await registry.register("worker", "coder")

    async def toggle(status: str) -> None:
        for _ in range(20):
            await registry.update_status("worker", status)

    await asyncio.gather(toggle("working"), toggle("idle"))

    agent = await registry.get_agent("worker")
    assert agent.status in (AgentStatus.WORKING, AgentStatus.IDLE)
