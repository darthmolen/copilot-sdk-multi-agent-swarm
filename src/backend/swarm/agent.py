"""SwarmAgent: wraps a CopilotSession with event-driven task execution."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from backend.events import EventBus
from backend.swarm.event_bridge import SessionEvent, SessionEventType
from backend.swarm.inbox_system import InboxSystem
from backend.swarm.models import Task
from backend.swarm.task_board import TaskBoard
from backend.swarm.team_registry import TeamRegistry
from backend.swarm.tools import create_swarm_tools

DEFAULT_TIMEOUT_SECONDS = 300


def _approve_all(_: Any) -> bool:
    """Auto-approve every permission request from the SDK."""
    return True


class SwarmAgent:
    """Agent that wraps a CopilotSession with custom_agents config and
    event-driven task execution via session.on()."""

    def __init__(
        self,
        name: str,
        role: str,
        display_name: str,
        task_board: TaskBoard,
        inbox: InboxSystem,
        registry: TeamRegistry,
        event_bus: EventBus,
    ) -> None:
        self.name = name
        self.role = role
        self.display_name = display_name
        self.task_board = task_board
        self.inbox = inbox
        self.registry = registry
        self.event_bus = event_bus
        self.session: Any = None  # Set by create_session

    async def create_session(self, client: Any) -> None:
        """Create a CopilotSession with custom_agents config."""
        tools = create_swarm_tools(
            agent_name=self.name,
            task_board=self.task_board,
            inbox=self.inbox,
        )

        self.session = await client.create_session(
            custom_agents=[
                {
                    "name": self.name,
                    "display_name": self.display_name,
                    "description": self.role,
                    "prompt": self.role,
                    "tools": None,
                    "infer": False,
                }
            ],
            agent=self.name,
            tools=tools,
            on_event=self._on_event,
            on_permission_request=_approve_all,
        )

    def _on_event(self, event: Any) -> None:
        """Forward SDK events to the EventBus."""
        self.event_bus.emit_sync("sdk_event", {"agent": self.name, "event": event})

    async def execute_task(
        self, task: Task, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        """Execute a task using event-driven session interaction.

        1. Mark task IN_PROGRESS
        2. Subscribe to session events via session.on()
        3. Send task prompt via session.send()
        4. Wait for ASSISTANT_TURN_END or SESSION_ERROR
        5. On timeout: mark task "timeout"
        6. On error: mark task "failed"
        7. Always unsubscribe in finally block
        """
        await self.task_board.update_status(task.id, "in_progress")

        done: asyncio.Event = asyncio.Event()
        error_holder: list[str] = []

        def _handler(event: Any) -> None:
            event_type = str(getattr(event, "type", "")).lower()
            if "turn_end" in event_type:
                done.set()
            elif "idle" in event_type:
                done.set()
            elif "session" in event_type and "error" in event_type:
                data = getattr(event, "data", None)
                error_holder.append(
                    getattr(data, "error", None) or getattr(data, "message", "unknown error")
                )
                done.set()

        unsubscribe: Callable[[], None] = self.session.on(_handler)

        try:
            await self.session.send(task.description)

            try:
                await asyncio.wait_for(done.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                await self.task_board.update_status(task.id, "timeout")
                return

            if error_holder:
                await self.task_board.update_status(task.id, "failed")
                return

            await self.task_board.update_status(task.id, "completed")
        finally:
            unsubscribe()
