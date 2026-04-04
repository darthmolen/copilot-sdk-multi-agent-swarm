"""SwarmService — single source of truth for swarm state.

Cache-first reads, write-through to optional repo.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from backend.swarm.inbox_system import InboxSystem
from backend.swarm.models import Task
from backend.swarm.task_board import TaskBoard
from backend.swarm.team_registry import TeamRegistry

log = structlog.get_logger()


class SwarmService:
    """Owns cache (in-memory stores) and optional persistence (repo).

    The orchestrator interacts with this service instead of directly
    with TaskBoard/InboxSystem/TeamRegistry. Reads come from cache.
    Writes go to cache + repo (if provided).
    """

    def __init__(self, repo: Any | None = None) -> None:
        self.task_board = TaskBoard()
        self.inbox = InboxSystem()
        self.registry = TeamRegistry()
        self._repo = repo
        self._swarm_id: str | None = None

    # ------------------------------------------------------------------
    # Swarm lifecycle
    # ------------------------------------------------------------------

    async def create_swarm(
        self, swarm_id: str, goal: str, template_key: str | None = None,
    ) -> None:
        self._swarm_id = swarm_id
        if self._repo:
            await self._repo.create_swarm(UUID(swarm_id), goal=goal, template_key=template_key)

    async def update_phase(self, phase: str) -> None:
        if self._repo and self._swarm_id:
            await self._repo.update_phase(UUID(self._swarm_id), phase)

    async def update_swarm(self, **kwargs: Any) -> None:
        if self._repo and self._swarm_id:
            await self._repo.update_swarm(UUID(self._swarm_id), **kwargs)

    # ------------------------------------------------------------------
    # Tasks — cache + optional persist
    # ------------------------------------------------------------------

    async def add_task(
        self, task_id: str, subject: str, description: str,
        worker_role: str, worker_name: str, blocked_by: list[str] | None = None,
    ) -> Task:
        if not self._swarm_id:
            raise RuntimeError("create_swarm() must be called before add_task()")
        task = await self.task_board.add_task(
            id=task_id, subject=subject, description=description,
            worker_role=worker_role, worker_name=worker_name,
            blocked_by=blocked_by or [],
        )
        if self._repo:
            await self._repo.create_task(
                UUID(self._swarm_id), task_id=task_id, subject=subject,
                description=description, worker_role=worker_role,
                worker_name=worker_name, blocked_by=blocked_by or [],
                status=task.status.value,
            )
        return task

    async def get_tasks(self, owner: str | None = None) -> list[Task]:
        return await self.task_board.get_tasks(owner)

    async def get_runnable_tasks(self, owner: str | None = None) -> list[Task]:
        return await self.task_board.get_runnable_tasks(owner)

    async def update_task_status(
        self, task_id: str, status: str, result: str = "",
    ) -> Task:
        updated = await self.task_board.update_status(task_id, status, result)
        if self._repo and self._swarm_id:
            await self._repo.update_task_status(
                UUID(self._swarm_id), task_id, status, result,
            )
        return updated

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    async def register_agent(
        self, name: str, role: str, display_name: str,
        session_id: str | None = None,
    ) -> None:
        await self.registry.register(name, role, display_name)
        if self._repo and self._swarm_id:
            await self._repo.register_agent(
                UUID(self._swarm_id), name=name, role=role,
                display_name=display_name, session_id=session_id,
            )

    async def get_agent_info(self, name: str) -> Any:
        try:
            return await self.registry.get_agent(name)
        except KeyError:
            return None

    async def update_agent_session_id(
        self, name: str, session_id: str,
    ) -> None:
        if self._repo and self._swarm_id:
            await self._repo.update_agent(
                UUID(self._swarm_id), name, session_id=session_id,
            )

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def send_message(
        self, swarm_id: str, sender: str, recipient: str, content: str,
    ) -> None:
        await self.inbox.send(sender, recipient, content)
        if self._repo:
            await self._repo.save_message(
                UUID(swarm_id), sender=sender, recipient=recipient, content=content,
            )

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    async def save_file(self, path: str, size_bytes: int = 0) -> None:
        if self._repo and self._swarm_id:
            await self._repo.save_file(UUID(self._swarm_id), path=path, size_bytes=size_bytes)

    # ------------------------------------------------------------------
    # Recovery: hydrate cache from repo
    # ------------------------------------------------------------------

    async def load(self, swarm_id: str) -> None:
        """Hydrate cache from repo. Called on cold start or swarm resume."""
        if not self._repo:
            raise ValueError("Cannot load without a repository")

        self._swarm_id = swarm_id
        state = await self._repo.load_swarm_state(UUID(swarm_id))

        # Hydrate task board
        for t in state["tasks"]:
            task = await self.task_board.add_task(
                id=t["id"], subject=t["subject"], description=t["description"],
                worker_role=t["worker_role"], worker_name=t["worker_name"],
                blocked_by=t.get("blocked_by", []),
            )
            if t["status"] != task.status.value:
                await self.task_board.update_status(t["id"], t["status"], t.get("result", ""))

        # Hydrate registry
        for a in state["agents"]:
            await self.registry.register(a["name"], a["role"], a.get("display_name", ""))

        # Hydrate inbox (messages are historical — add back for context)
        for agent in state["agents"]:
            self.inbox.register_agent(agent["name"])

        log.info("swarm_state_loaded", swarm_id=swarm_id,
                 tasks=len(state["tasks"]), agents=len(state["agents"]))
