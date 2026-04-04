"""SwarmService unit tests — cache-only, no database."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.services.swarm_service import SwarmService


async def test_service_cache_only_task_crud():
    """Service with no repo: CRUD works via cache."""
    service = SwarmService()
    swarm_id = str(uuid4())

    task = await service.add_task(
        swarm_id, task_id="task-0", subject="Analyze",
        description="Do analysis", worker_role="analyst", worker_name="analyst",
    )
    assert task.id == "task-0"

    tasks = await service.get_tasks()
    assert len(tasks) == 1


async def test_service_update_task_status():
    service = SwarmService()
    swarm_id = str(uuid4())
    await service.add_task(
        swarm_id, task_id="task-0", subject="Work",
        description="Do it", worker_role="dev", worker_name="dev",
    )
    updated = await service.update_task_status("task-0", "completed", "Done!")
    assert updated.status.value == "completed"
    assert updated.result == "Done!"


async def test_service_reads_from_cache():
    """Get methods read from cache, not repo."""
    service = SwarmService()
    await service.add_task(
        str(uuid4()), task_id="t1", subject="X",
        description="Y", worker_role="r", worker_name="w",
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
    service.inbox.register_agent("writer")
    await service.send_message(str(uuid4()), "analyst", "writer", "Hello")
    messages = await service.inbox.peek("writer")
    assert len(messages) == 1
    assert messages[0].content == "Hello"
