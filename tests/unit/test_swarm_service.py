"""SwarmService unit tests — cache-only, no database."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from backend.services.swarm_service import SwarmService


async def test_service_cache_only_task_crud():
    """Service with no repo: CRUD works via cache."""
    service = SwarmService()
    await service.create_swarm(str(uuid4()), goal="Test")

    task = await service.add_task(
        task_id="task-0",
        subject="Analyze",
        description="Do analysis",
        worker_role="analyst",
        worker_name="analyst",
    )
    assert task.id == "task-0"

    tasks = await service.get_tasks()
    assert len(tasks) == 1


async def test_service_update_task_status():
    service = SwarmService()
    await service.create_swarm(str(uuid4()), goal="Test")
    await service.add_task(
        task_id="task-0",
        subject="Work",
        description="Do it",
        worker_role="dev",
        worker_name="dev",
    )
    updated = await service.update_task_status("task-0", "completed", "Done!")
    assert updated.status.value == "completed"
    assert updated.result == "Done!"


async def test_service_reads_from_cache():
    """Get methods read from cache, not repo."""
    service = SwarmService()
    await service.create_swarm(str(uuid4()), goal="Test")
    await service.add_task(
        task_id="t1",
        subject="X",
        description="Y",
        worker_role="r",
        worker_name="w",
    )
    tasks = await service.get_tasks()
    assert len(tasks) == 1
    assert tasks[0].id == "t1"


async def test_service_register_agent():
    service = SwarmService()
    await service.register_agent("analyst", "Data Analyst", "Analyst")
    info = await service.get_agent_info("analyst")
    assert info is not None
    assert info.role == "Data Analyst"


async def test_service_send_and_receive_message():
    service = SwarmService()
    swarm_id = str(uuid4())
    await service.create_swarm(swarm_id, goal="Test")
    service.inbox.register_agent("writer")
    await service.send_message(swarm_id, "analyst", "writer", "Hello")
    messages = await service.inbox.peek("writer")
    assert len(messages) == 1
    assert messages[0].content == "Hello"


async def test_service_add_task_without_create_swarm_raises():
    """add_task() raises if create_swarm() wasn't called first."""
    service = SwarmService()
    with pytest.raises(RuntimeError, match="create_swarm"):
        await service.add_task(
            task_id="t1",
            subject="X",
            description="Y",
            worker_role="r",
            worker_name="w",
        )


# ---------------------------------------------------------------
# Suspend
# ---------------------------------------------------------------


class TestSwarmServiceSuspend:
    async def test_suspend_updates_phase(self) -> None:
        """suspend() sets phase to 'suspended' in cache."""
        service = SwarmService()
        swarm_id = str(uuid4())
        await service.create_swarm(swarm_id, goal="Test")

        await service.suspend("rounds_exhausted")

        assert service._phase == "suspended"

    async def test_suspend_calls_repo_when_available(self) -> None:
        """suspend() calls repo.suspend_swarm() if repo is set."""
        mock_repo = AsyncMock()
        service = SwarmService(repo=mock_repo)
        swarm_id = str(uuid4())
        await service.create_swarm(swarm_id, goal="Test")

        await service.suspend("rounds_exhausted")

        mock_repo.suspend_swarm.assert_awaited_once_with(UUID(swarm_id))

    async def test_suspend_without_repo_still_works(self) -> None:
        """suspend() works in memory-only mode (no repo)."""
        service = SwarmService()
        swarm_id = str(uuid4())
        await service.create_swarm(swarm_id, goal="Test")

        await service.suspend("rounds_exhausted")

        assert service._phase == "suspended"


# ---------------------------------------------------------------
# Round tracking
# ---------------------------------------------------------------


class TestSwarmServiceRoundTracking:
    async def test_update_round(self) -> None:
        """update_round() persists round number."""
        mock_repo = AsyncMock()
        service = SwarmService(repo=mock_repo)
        swarm_id = str(uuid4())
        await service.create_swarm(swarm_id, goal="Test")

        await service.update_round(3)

        assert service._current_round == 3
        mock_repo.update_round.assert_awaited_once_with(UUID(swarm_id), 3)

    async def test_update_round_without_repo(self) -> None:
        """update_round() works in memory-only mode."""
        service = SwarmService()
        swarm_id = str(uuid4())
        await service.create_swarm(swarm_id, goal="Test")

        await service.update_round(3)

        assert service._current_round == 3
