"""Team registry for tracking agent metadata and status."""

from __future__ import annotations

import asyncio

from backend.swarm.models import AgentInfo, AgentStatus


class TeamRegistry:
    """Tracks registered agents and their current status.

    All mutations are protected by an asyncio.Lock to prevent
    concurrent-access corruption.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentInfo] = {}
        self._lock = asyncio.Lock()

    async def register(self, name: str, role: str, display_name: str = "") -> AgentInfo:
        """Register a new agent. Returns the created AgentInfo."""
        async with self._lock:
            agent = AgentInfo(
                name=name,
                role=role,
                display_name=display_name or name,
            )
            self._agents[name] = agent
            return agent

    async def get_agent(self, name: str) -> AgentInfo:
        """Return the agent with the given *name*, or raise KeyError."""
        async with self._lock:
            try:
                return self._agents[name]
            except KeyError as exc:
                raise KeyError(f"Agent '{name}' not found") from exc

    async def get_all(self) -> list[AgentInfo]:
        """Return a list of all registered agents."""
        async with self._lock:
            return list(self._agents.values())

    async def update_status(self, name: str, status: str) -> AgentInfo:
        """Set the status of *name* to the AgentStatus matching *status*."""
        async with self._lock:
            agent = self._agents[name]
            agent.status = AgentStatus(status)
            return agent

    async def increment_tasks_completed(self, name: str) -> AgentInfo:
        """Add 1 to the tasks_completed counter for *name*."""
        async with self._lock:
            agent = self._agents[name]
            agent.tasks_completed += 1
            return agent
