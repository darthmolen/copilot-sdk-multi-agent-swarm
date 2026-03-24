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
        available_tools: list[str] | None = None,
        prompt_template: str | None = None,
        system_preamble: str = "",
        system_tools: list[str] | None = None,
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
        self.session: Any = None  # Set by create_session

    async def create_session(self, client: Any) -> None:
        """Create a CopilotSession with custom_agents config."""
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

        # Merge system tools (always-available) with template tools (per-agent)
        # null = no restriction (agent sees everything including custom tools)
        # list = restricted — merge system tools so they're always accessible
        if self.available_tools is not None:
            merged_agent_tools = list(set(self.available_tools + self.system_tools))
        else:
            merged_agent_tools = None  # null = all tools

        self.session = await client.create_session(
            custom_agents=[
                {
                    "name": self.name,
                    "display_name": self.display_name,
                    "description": self.role,
                    "prompt": full_prompt,
                    "tools": merged_agent_tools,
                    "infer": False,
                }
            ],
            agent=self.name,
            tools=tools,
            available_tools=self.available_tools,
            on_event=self._on_event,
            on_permission_request=_approve_all,
        )

        # Explicitly select the agent — required for customAgents[n].tools enforcement.
        # The `agent=` param in create_session registers but does NOT activate the agent.
        try:
            from copilot.generated.rpc import SessionAgentSelectParams  # type: ignore[import-not-found]
            await self.session.rpc.agent.select(SessionAgentSelectParams(name=self.name))
        except (ImportError, AttributeError):
            # Mock sessions or SDK not installed — try dict fallback
            try:
                await self.session.rpc.agent.select({"name": self.name})
            except (AttributeError, TypeError):
                pass  # Mock without rpc support

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
        text_content: list[str] = []  # Capture assistant text as fallback result

        def _handler(event: Any) -> None:
            raw = getattr(event, "type", "")
            # Use .value (dot notation like "assistant.turn_end") if available,
            # otherwise fall back to str() (like "SessionEventType.ASSISTANT_TURN_END")
            et = getattr(raw, "value", str(raw)).lower()

            if "turn_end" in et:
                done.set()
            elif "idle" in et:
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
