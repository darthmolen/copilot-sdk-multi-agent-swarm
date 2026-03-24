"""SwarmAgent: wraps a CopilotSession with event-driven task execution."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from backend.events import EventBus
from backend.swarm.event_bridge import SessionEvent, SessionEventType
from backend.swarm.inbox_system import InboxSystem
from backend.swarm.models import Task, TaskStatus
from backend.swarm.task_board import TaskBoard
from backend.swarm.team_registry import TeamRegistry
from backend.swarm.tools import create_swarm_tools

DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MODEL = "gemini-3-pro-preview"


def _approve_all(_: Any) -> bool:
    """Auto-approve every permission request from the SDK."""
    return True


class SwarmAgent:
    """Agent that wraps a CopilotSession with system_message mode:replace
    and event-driven task execution.

    Does NOT use customAgents — empirically proven to suppress custom tool
    compliance. Uses system_message + tools + available_tools instead.
    """

    def __init__(
        self,
        name: str,
        role: str,
        display_name: str,
        task_board: TaskBoard,
        inbox: InboxSystem,
        registry: TeamRegistry,
        event_bus: EventBus,
        available_tools: list[str] | None = None,
        prompt_template: str | None = None,
        system_preamble: str = "",
        system_tools: list[str] | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.name = name
        self.role = role
        self.display_name = display_name
        self.task_board = task_board
        self.inbox = inbox
        self.registry = registry
        self.event_bus = event_bus
        self.available_tools = available_tools
        self.prompt_template = prompt_template
        self.system_preamble = system_preamble
        self.system_tools = system_tools or []
        self.model = model
        self.session: Any = None  # Set by create_session

    async def create_session(self, client: Any) -> None:
        """Create a CopilotSession with system_message mode:replace.

        No customAgents — uses direct system_message override for better
        custom tool compliance (see spike_no_custom_agents.py).
        """
        from backend.swarm.prompts import assemble_worker_prompt

        def _tool_event_callback(event_data: dict) -> None:
            """Forward tool events to EventBus for frontend consumption."""
            event_name = event_data.get("event", "tool_event")
            self.event_bus.emit_sync(event_name, event_data)

        tools = create_swarm_tools(
            agent_name=self.name,
            task_board=self.task_board,
            inbox=self.inbox,
            event_callback=_tool_event_callback,
        )

        full_prompt = assemble_worker_prompt(
            system_preamble=self.system_preamble,
            display_name=self.display_name,
            role=self.role,
            template_prompt=self.prompt_template,
        )

        # Merge system tools with template available_tools for the session whitelist
        if self.available_tools is not None:
            merged_available = list(set(self.available_tools + self.system_tools))
        else:
            merged_available = None

        self.session = await client.create_session(
            on_permission_request=_approve_all,
            model=self.model,
            system_message={"mode": "replace", "content": full_prompt},
            tools=tools,
            available_tools=merged_available,
            on_event=self._on_event,
        )

    def _on_event(self, event: Any) -> None:
        """Forward SDK events to the EventBus."""
        self.event_bus.emit_sync("sdk_event", {"agent": self.name, "event": event})

    async def execute_task(
        self, task: Task, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        """Execute a task using event-driven session interaction."""
        await self.task_board.update_status(task.id, "in_progress")

        done: asyncio.Event = asyncio.Event()
        error_holder: list[str] = []
        text_content: list[str] = []

        def _handler(event: Any) -> None:
            raw = getattr(event, "type", "")
            et = getattr(raw, "value", str(raw)).lower()

            # Wait for session.idle — NOT turn_end.
            # turn_end fires after EVERY turn; agents do multiple turns per task.
            # session.idle fires when the agent is truly done (no more turns).
            if "idle" in et:
                done.set()
            elif "session" in et and "error" in et:
                data = getattr(event, "data", None)
                error_holder.append(
                    getattr(data, "error", None) or getattr(data, "message", "unknown error")
                )
                done.set()
            # Capture ALL assistant text (even mid-thought with tool_requests)
            if "assistant.message" in et and "delta" not in et:
                data = getattr(event, "data", None)
                content = getattr(data, "content", None)
                if content and str(content).strip():
                    text_content.append(str(content))
            # Also capture reasoning as context
            elif "assistant.reasoning" in et and "delta" not in et:
                data = getattr(event, "data", None)
                content = getattr(data, "content", None)
                if content and str(content).strip():
                    text_content.append(str(content))

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

            # Check if agent already completed via task_update tool
            current_tasks = await self.task_board.get_tasks()
            current = next((t for t in current_tasks if t.id == task.id), None)
            if current and current.status == TaskStatus.IN_PROGRESS:
                # Agent didn't call task_update — use captured text as result
                result = "\n".join(text_content) if text_content else ""
                await self.task_board.update_status(task.id, "completed", result)
        finally:
            unsubscribe()
