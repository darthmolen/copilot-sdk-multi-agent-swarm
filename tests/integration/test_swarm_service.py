"""SwarmService integration tests — with real Postgres repo."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.db.repository import SwarmRepository
from backend.services.swarm_service import SwarmService


pytestmark = pytest.mark.db


async def test_service_writes_through_to_repo(db_engine):
    """Mutations persist to DB via repo."""
    repo = SwarmRepository(db_engine)
    service = SwarmService(repo=repo)
    swarm_id = str(uuid4())

    await service.create_swarm(swarm_id, goal="Test", template_key="azure")
    await service.add_task(
        task_id="task-0", subject="Work",
        description="Do it", worker_role="dev", worker_name="dev",
    )

    # Verify in DB directly
    from uuid import UUID
    db_swarm = await repo.get_swarm(UUID(swarm_id))
    assert db_swarm is not None
    assert db_swarm["goal"] == "Test"

    db_tasks = await repo.get_tasks(UUID(swarm_id))
    assert len(db_tasks) == 1
    assert db_tasks[0]["subject"] == "Work"


async def test_service_load_hydrates_cache_from_repo(db_engine):
    """load() populates empty cache from DB."""
    repo = SwarmRepository(db_engine)
    swarm_id = uuid4()

    # Populate DB directly via repo
    await repo.create_swarm(swarm_id, goal="Hydration test")
    await repo.create_task(
        swarm_id, task_id="task-0", subject="Loaded",
        description="From DB", worker_role="dev", worker_name="dev",
    )
    await repo.register_agent(swarm_id, name="dev", role="Developer", display_name="Dev")

    # Create fresh service and load
    service = SwarmService(repo=repo)
    await service.load(str(swarm_id))

    # Cache should now have the data
    tasks = await service.get_tasks()
    assert len(tasks) == 1
    assert tasks[0].subject == "Loaded"

    info = await service.get_agent_info("dev")
    assert info is not None


async def test_service_cache_matches_repo_after_mutations(db_engine):
    """Cache and DB stay in sync after writes."""
    repo = SwarmRepository(db_engine)
    service = SwarmService(repo=repo)
    swarm_id = str(uuid4())

    await service.create_swarm(swarm_id, goal="Sync test")
    await service.add_task(
        task_id="task-0", subject="Sync",
        description="Check", worker_role="dev", worker_name="dev",
    )
    await service.update_task_status("task-0", "completed", "Synced!")

    # Cache
    cache_tasks = await service.get_tasks()
    assert cache_tasks[0].status.value == "completed"

    # DB
    from uuid import UUID
    db_tasks = await repo.get_tasks(UUID(swarm_id))
    assert db_tasks[0]["status"] == "completed"
    assert db_tasks[0]["result"] == "Synced!"
