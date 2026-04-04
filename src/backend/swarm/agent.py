"""SwarmAgent: wraps a CopilotSession with event-driven task execution."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Callable

import structlog

from backend.events import EventBus
from backend.swarm.event_bridge import SessionEvent, SessionEventType
from backend.swarm.inbox_system import InboxSystem
from backend.swarm.models import Task, TaskStatus
from backend.swarm.task_board import TaskBoard
from backend.swarm.team_registry import TeamRegistry
from backend.swarm.tools import create_swarm_tools

log = structlog.get_logger()

DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_MODEL = os.environ.get("SWARM_MODEL", "gemini-3-pro-preview")


def _approve_all(*_args: Any, **_kwargs: Any) -> Any:
    """Auto-approve every permission request from the SDK."""
    try:
        from copilot.session import PermissionRequestResult  # type: ignore[import-not-found]
        return PermissionRequestResult(kind="approved")
    except ImportError:
        return True  # Mock fallback


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
        work_dir: Path | None = None,
        swarm_id: str | None = None,
        mcp_servers: dict | None = None,
        skill_directories: list[str] | None = None,
        disabled_skills: list[str] | None = None,
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
        self.work_dir = work_dir
        self.swarm_id = swarm_id
        self.mcp_servers = mcp_servers
        self.skill_directories = skill_directories
        self.disabled_skills = disabled_skills
        self.session: Any = None  # Set by create_session
        self.session_id: str | None = None  # Captured after create_session
        self._client: Any = None  # Set by create_session if owns_client
        self._owns_client: bool = False
        self._monitor_tasks: list[asyncio.Task[None]] = []

    async def create_session(self, client: Any, *, owns_client: bool = False) -> None:
        """Create a CopilotSession with system_message mode:replace.

        No customAgents — uses direct system_message override for better
        custom tool compliance (see spike_no_custom_agents.py).
        """
        from backend.swarm.prompts import assemble_worker_prompt

        def _tool_event_callback(event_data: dict) -> None:
            """Forward tool events to EventBus for frontend consumption."""
            if self.swarm_id:
                event_data = {**event_data, "swarm_id": self.swarm_id}
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
            work_dir=self.work_dir,
        )

        # Merge system tools with template available_tools for the session whitelist
        if self.available_tools is not None:
            merged_available = list(set(self.available_tools + self.system_tools))
        else:
            merged_available = None

        kwargs: dict[str, Any] = {
            "on_permission_request": _approve_all,
            "model": self.model,
            "system_message": {"mode": "replace", "content": full_prompt},
            "tools": tools,
            "available_tools": merged_available,
            "on_event": self._on_event,
        }
        if self.mcp_servers:
            kwargs["mcp_servers"] = self.mcp_servers
        if self.skill_directories:
            kwargs["skill_directories"] = self.skill_directories
        if self.disabled_skills:
            kwargs["disabled_skills"] = self.disabled_skills

        self.session = await client.create_session(**kwargs)
        self.session_id = getattr(self.session, 'session_id', None)
        if owns_client:
            self._client = client
            self._owns_client = True

    async def cleanup(self) -> None:
        """Stop the owned client if this agent has one."""
        if self._owns_client and self._client is not None:
            try:
                await self._client.stop()
            except Exception:
                log.warning("agent_client_stop_failed", agent=self.name)
            self._client = None

    def _on_event(self, event: Any) -> None:
        """Forward SDK events to the EventBus."""
        self.event_bus.emit_sync("sdk_event", {"agent": self.name, "event": event})

    MAX_TOOL_FAILURES = 5

    async def execute_task(
        self, task: Task, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        """Execute a task using event-driven session interaction."""
        await self.task_board.update_status(task.id, "in_progress")

        done: asyncio.Event = asyncio.Event()
        error_holder: list[str] = []
        text_content: list[str] = []
        delta_parts: list[str] = []
        consecutive_tool_failures = 0

        def _handler(event: Any) -> None:
            nonlocal consecutive_tool_failures
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
            # Circuit breaker: track consecutive tool failures
            if "tool.execution_complete" in et or "tool_execution_complete" in et:
                data = getattr(event, "data", None)
                success = getattr(data, "success", None)
                if success is False:
                    consecutive_tool_failures += 1
                    if consecutive_tool_failures >= self.MAX_TOOL_FAILURES:
                        error_msg = getattr(data, "error", "") or ""
                        error_holder.append(
                            f"Circuit breaker: {consecutive_tool_failures} consecutive "
                            f"tool failures. Last error: {error_msg}"
                        )
                        log.warning("circuit_breaker_tripped",
                                    agent=self.name, task_id=task.id,
                                    failures=consecutive_tool_failures)
                        done.set()
                elif success is True:
                    consecutive_tool_failures = 0
            # Accumulate streamed deltas as fallback
            if "assistant.message_delta" in et:
                data = getattr(event, "data", None)
                delta = getattr(data, "content", "") or getattr(data, "delta_content", "")
                if delta:
                    delta_parts.append(str(delta))
            # Capture ALL assistant text (even mid-thought with tool_requests)
            elif "assistant.message" in et and "delta" not in et:
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

        monitoring = False
        try:
            task_prompt = (
                f"Your task ID is: {task.id}\n"
                f"Subject: {task.subject}\n\n"
                f"{task.description}"
            )
            await self.session.send(task_prompt)

            try:
                await asyncio.wait_for(done.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                await self.task_board.update_status(task.id, "timeout")
                monitoring = True
                t = asyncio.create_task(self._monitor_late_completion(
                    task, done, text_content, delta_parts, error_holder, unsubscribe,
                ))
                self._monitor_tasks.append(t)
                t.add_done_callback(lambda task_ref: self._monitor_tasks.remove(task_ref) if task_ref in self._monitor_tasks else None)
                return

            if error_holder:
                await self.task_board.update_status(task.id, "failed", error_holder[0])
                return

            # Check if agent already completed via task_update tool
            current_tasks = await self.task_board.get_tasks()
            current = next((t for t in current_tasks if t.id == task.id), None)
            if current and current.status == TaskStatus.IN_PROGRESS:
                # Agent didn't call task_update — use captured text as result
                # Prefer full messages; fall back to accumulated deltas
                result = (
                    "\n".join(text_content) if text_content
                    else "".join(delta_parts) if delta_parts
                    else ""
                )
                await self.task_board.update_status(task.id, "completed", result)
        finally:
            if not monitoring:
                unsubscribe()

    async def _monitor_late_completion(
        self,
        task: Task,
        done: asyncio.Event,
        text_content: list[str],
        delta_parts: list[str],
        error_holder: list[str],
        unsubscribe: Callable[[], None],
        monitor_timeout: float = 3600,
    ) -> None:
        """Background monitor: wait for a timed-out task's SDK session to complete."""
        try:
            await asyncio.wait_for(done.wait(), timeout=monitor_timeout)

            # Session finished — check if it was an error or success
            current_tasks = await self.task_board.get_tasks()
            current = next((t for t in current_tasks if t.id == task.id), None)
            if current and current.status == TaskStatus.TIMEOUT:
                if error_holder:
                    updated = await self.task_board.update_status(task.id, "failed", error_holder[0])
                    log.info("task_late_failed", task_id=task.id, agent=self.name)
                else:
                    result = (
                        "\n".join(text_content) if text_content
                        else "".join(delta_parts) if delta_parts
                        else ""
                    )
                    updated = await self.task_board.update_status(task.id, "completed", result)
                    log.info("task_late_completed", task_id=task.id, agent=self.name,
                             result_len=len(result))
                if self.swarm_id:
                    await self.event_bus.emit("task.updated", {
                        "task": updated.to_dict(),
                        "swarm_id": self.swarm_id,
                    })
        except asyncio.CancelledError:
            log.info("monitor_cancelled", task_id=task.id, agent=self.name)
        except asyncio.TimeoutError:
            log.info("monitor_expired", task_id=task.id, agent=self.name)
        finally:
            unsubscribe()
