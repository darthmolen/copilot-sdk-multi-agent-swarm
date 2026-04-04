"""SwarmOrchestrator: manages the full swarm lifecycle (plan, spawn, execute, synthesize)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import structlog

from backend.events import EventBus
from backend.swarm.agent import SwarmAgent
from backend.swarm.inbox_system import InboxSystem
from backend.swarm.models import Task, TaskStatus
from backend.swarm.prompts import (
    LEADER_SYSTEM_PROMPT,
    SYNTHESIS_PROMPT_TEMPLATE,
)
from backend.swarm.task_board import TaskBoard
from backend.swarm.team_registry import TeamRegistry
from backend.swarm.template_loader import AgentDefinition, LoadedTemplate
from backend.swarm.tools import create_plan_tool

log = structlog.get_logger()


def _approve_all(*_args: Any, **_kwargs: Any) -> Any:
    """Auto-approve every permission request."""
    try:
        from copilot.session import PermissionRequestResult  # type: ignore[import-not-found]

        return PermissionRequestResult(kind="approved")
    except ImportError:
        return True


async def _create_session_with_tools(
    client: Any,
    system_prompt: str,
    tools: list[Any],
    session_id: str | None = None,
    mcp_servers: dict | None = None,
    skill_directories: list[str] | None = None,
    model: str | None = None,
) -> Any:
    """Create a session with the given tools, compatible with real SDK and mocks."""
    tool_names = [t.name for t in tools] if tools else []
    log.info(
        "session_creating",
        session_id=session_id,
        model=model,
        tool_count=len(tools) if tools else 0,
        tool_names=tool_names,
        has_mcp=mcp_servers is not None,
        has_skills=skill_directories is not None,
        prompt_len=len(system_prompt),
    )
    try:
        kwargs: dict[str, Any] = {
            "on_permission_request": _approve_all,
            "system_message": {"mode": "replace", "content": system_prompt},
            "tools": tools,
        }
        if session_id:
            kwargs["session_id"] = session_id
        if mcp_servers:
            kwargs["mcp_servers"] = mcp_servers
        if skill_directories:
            kwargs["skill_directories"] = skill_directories
        if model:
            kwargs["model"] = model
        session = await client.create_session(**kwargs)
        log.info("session_created", session_id=session_id)
        return session
    except TypeError:
        # Fallback for mocks that don't accept all SDK kwargs
        log.debug("session_create_fallback", session_id=session_id)
        return await client.create_session(tools=tools)


class SwarmOrchestrator:
    """Orchestrates the full swarm lifecycle: plan -> spawn -> execute -> synthesize."""

    def __init__(
        self,
        client: Any,
        event_bus: EventBus,
        config: dict[str, Any] | None = None,
        template: LoadedTemplate | None = None,
        system_preamble: str = "",
        system_tools: list[str] | None = None,
        model: str = "gemini-3-pro-preview",
        swarm_id: str | None = None,
        work_base: Path | None = None,
        client_factory: Any | None = None,
        service: Any | None = None,
    ) -> None:
        self.client = client
        self.client_factory = client_factory
        self.event_bus = event_bus
        self.service = service
        if service is not None:
            self.task_board = service.task_board
            self.inbox = service.inbox
            self.registry = service.registry
        else:
            self.task_board = TaskBoard()
            self.inbox = InboxSystem()
            self.registry = TeamRegistry()
        self.agents: dict[str, SwarmAgent] = {}
        self._agent_defs: dict[str, AgentDefinition] = {}
        default_config: dict[str, Any] = {"max_rounds": 3, "timeout": 1800}
        self.config = {**default_config, **(config or {})}
        self.template = template
        self.system_preamble = system_preamble
        self.system_tools = system_tools or []
        self.model = model
        self.swarm_id = swarm_id
        self.work_dir: Path | None = None
        if swarm_id and work_base:
            self.work_dir = work_base / swarm_id
        self.synthesis_session_id: str | None = None
        self._chat_lock = asyncio.Lock()
        self._cancelled = False
        self._continue_event: asyncio.Event | None = None
        self._continue_action: str = ""
        self.qa_session: Any = None
        self.qa_complete = asyncio.Event()
        self.qa_refined_goal: str | None = None
        self._known_files: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _get_mcp_servers(self) -> dict | None:
        """Merge template MCP servers with the in-process swarm-state server."""
        template_mcp = self.template.mcp_servers if self.template else None
        host = os.environ.get("SWARM_MCP_HOST", "0.0.0.0")  # noqa: S104
        port = os.environ.get("PORT", "8000")
        swarm_mcp_url = os.environ.get("SWARM_MCP_URL", f"http://{host}:{port}/mcp/")
        api_key = os.environ.get("SWARM_API_KEY", "")
        swarm_state_mcp: dict[str, Any] = {
            "swarm-state": {
                "type": "http",
                "url": swarm_mcp_url,
                "tools": ["*"],
                **({"headers": {"X-API-Key": api_key}} if api_key else {}),
            }
        }
        if template_mcp:
            return {**template_mcp, **swarm_state_mcp}
        return swarm_state_mcp

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event with swarm_id attached (if set)."""
        if self.swarm_id:
            data = {**data, "swarm_id": self.swarm_id}
        await self.event_bus.emit(event_type, data)

    async def _cleanup_agents(self) -> None:
        """Stop per-agent clients after execution completes."""
        for agent in self.agents.values():
            await agent.cleanup()
        log.info("agent_clients_cleaned_up", swarm_id=self.swarm_id, agent_count=len(self.agents))

    async def cancel(self) -> None:
        """Cancel the swarm execution."""
        self._cancelled = True
        await self._emit("swarm.phase_changed", {"phase": "cancelled"})
        await self._emit("swarm.cancelled", {})

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    async def chat(self, message: str, active_file: str | None = None) -> str:
        """Resume synthesis session and send a refinement message."""
        start_time = time.monotonic()

        if not self.synthesis_session_id:
            raise ValueError("No synthesis session available")

        log.info("chat_start", swarm_id=self.swarm_id, session_id=self.synthesis_session_id, message_len=len(message))

        async with self._chat_lock:
            log.info("chat_resuming_session", session_id=self.synthesis_session_id)
            try:
                session = await self.client.resume_session(
                    self.synthesis_session_id,
                    on_permission_request=_approve_all,
                )
                log.info("chat_session_resumed", session_id=self.synthesis_session_id)
            except (TypeError, AttributeError) as exc:
                log.warning("chat_resume_fallback", error=str(exc))
                # Mock fallback — create a new session for testing
                session = await _create_session_with_tools(
                    self.client,
                    "You are a synthesis agent. Refine the report based on user feedback.",
                    [],
                )

            done = asyncio.Event()
            text_content: list[str] = []
            delta_parts: list[str] = []
            message_id = f"chat-{id(message)}"
            tool_call_count = [0]

            def _on_event(event: Any) -> None:
                raw = getattr(event, "type", "")
                et = getattr(raw, "value", str(raw)).lower()
                log.debug("chat_sdk_event", event_type=et, swarm_id=self.swarm_id)
                if "idle" in et:
                    log.info("chat_session_idle", swarm_id=self.swarm_id)
                    done.set()
                elif "session" in et and "error" in et:
                    log.error("chat_session_error", event_type=et, swarm_id=self.swarm_id)
                    done.set()
                if "assistant.message" in et and "delta" not in et:
                    data = getattr(event, "data", None)
                    content = getattr(data, "content", None)
                    if content and str(content).strip():
                        text_content.append(str(content))
                        # Also emit as delta so frontend gets streaming content
                        # even when SDK only sends complete messages (no deltas)
                        self.event_bus.emit_sync(
                            "leader.chat_delta",
                            {
                                "delta": str(content),
                                "message_id": message_id,
                                "swarm_id": self.swarm_id,
                            },
                        )
                # Stream deltas via EventBus.emit_sync and accumulate
                if "assistant.message_delta" in et:
                    data = getattr(event, "data", None)
                    delta = getattr(data, "content", "")
                    if delta:
                        delta_parts.append(str(delta))
                        self.event_bus.emit_sync(
                            "leader.chat_delta",
                            {
                                "delta": str(delta),
                                "message_id": message_id,
                                "swarm_id": self.swarm_id,
                            },
                        )
                # Tool events
                if "tool.execution_start" in et:
                    data = getattr(event, "data", None)
                    tool_name = getattr(data, "tool_name", "")
                    tool_call_id = getattr(data, "tool_call_id", "")
                    tool_call_count[0] += 1
                    log.info("chat_tool_start", swarm_id=self.swarm_id, tool_name=tool_name, tool_call_id=tool_call_id)
                    self.event_bus.emit_sync(
                        "leader.chat_tool_start",
                        {
                            "tool_name": tool_name,
                            "tool_call_id": tool_call_id,
                            "message_id": message_id,
                            "swarm_id": self.swarm_id,
                        },
                    )
                if "tool.execution_complete" in et:
                    data = getattr(event, "data", None)
                    tool_call_id = getattr(data, "tool_call_id", "")
                    success = str(getattr(data, "success", "")).lower() == "true"
                    log.info("chat_tool_result", swarm_id=self.swarm_id, tool_call_id=tool_call_id, success=success)
                    self.event_bus.emit_sync(
                        "leader.chat_tool_result",
                        {
                            "tool_call_id": tool_call_id,
                            "success": success,
                            "message_id": message_id,
                            "swarm_id": self.swarm_id,
                        },
                    )

            unsubscribe = session.on(_on_event)
            timeout = self.config.get("timeout", 300)

            try:
                refinement_prompt = (
                    "You are in REFINEMENT MODE. You are the synthesis agent. "
                    "You CANNOT spawn other agents or delegate to a team. "
                    "Answer the user's question directly using the report and worker outputs "
                    "already in your conversation context. "
                    "If you need to revise a section, produce the revised text directly.\n\n"
                    f"User feedback: {message}"
                )
                if active_file:
                    file_path = f"workdir/{self.swarm_id}/{active_file}"
                    refinement_prompt += (
                        f"\n\nThe user has '{active_file}' open. "
                        f"The file is at '{file_path}'. "
                        "Read it if relevant to their question."
                    )
                log.info("chat_sending", swarm_id=self.swarm_id, timeout=timeout)
                await session.send(refinement_prompt)
                log.info("chat_send_returned", swarm_id=self.swarm_id)
                await asyncio.wait_for(done.wait(), timeout=timeout)
            except (TimeoutError, asyncio.TimeoutError):
                log.warning("chat_timeout", swarm_id=self.swarm_id, timeout=timeout)
            finally:
                unsubscribe()

            response = "\n".join(text_content) if text_content else "".join(delta_parts) if delta_parts else ""
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log.info(
                "chat_complete",
                swarm_id=self.swarm_id,
                response_len=len(response),
                chunks=len(text_content),
                tool_calls=tool_call_count[0],
                duration_ms=duration_ms,
            )
            await self._emit(
                "leader.chat_message",
                {
                    "content": response,
                    "message_id": message_id,
                },
            )
            return response

    async def start_qa(self, goal: str) -> str:
        """Start a Q&A session with the leader. Returns the refined goal.

        Creates a leader session with the begin_swarm tool, sends the user's
        goal, then waits for the leader to call begin_swarm (triggered by
        user chat messages via qa_chat).
        """
        from backend.swarm.tools import create_begin_swarm_tool

        leader_prompt = self.template.leader_prompt if self.template else ""
        goal_holder: list[str] = []
        begin_tool = create_begin_swarm_tool(goal_holder, self.qa_complete)

        mcp_servers = self._get_mcp_servers()
        skill_dirs = [str(self.template.skills_dir)] if self.template and self.template.skills_dir else None

        log.info("qa_session_creating", swarm_id=self.swarm_id)
        self.qa_session = await _create_session_with_tools(
            self.client,
            leader_prompt,
            [begin_tool],
            mcp_servers=mcp_servers,
            skill_directories=skill_dirs,
            model=self.model,
        )

        await self._emit("swarm.phase_changed", {"phase": "qa"})

        # Stream the leader's initial response (opening interview question)
        message_id = f"qa-init-{self.swarm_id}"
        done = asyncio.Event()
        delta_parts: list[str] = []

        def _on_init_event(event: Any) -> None:
            raw = getattr(event, "type", "")
            et = getattr(raw, "value", str(raw)).lower()
            if "idle" in et or ("session" in et and "error" in et):
                done.set()
            if "assistant.message" in et and "delta" not in et:
                data = getattr(event, "data", None)
                content = getattr(data, "content", None)
                if content and str(content).strip():
                    delta_parts.append(str(content))
                    self.event_bus.emit_sync(
                        "leader.chat_delta",
                        {
                            "delta": str(content),
                            "message_id": message_id,
                            "swarm_id": self.swarm_id,
                        },
                    )
            if "assistant.message_delta" in et:
                data = getattr(event, "data", None)
                delta = getattr(data, "content", "")
                if delta:
                    delta_parts.append(str(delta))
                    self.event_bus.emit_sync(
                        "leader.chat_delta",
                        {
                            "delta": str(delta),
                            "message_id": message_id,
                            "swarm_id": self.swarm_id,
                        },
                    )

        unsubscribe = self.qa_session.on(_on_init_event)
        timeout = self.config.get("timeout", 300)

        # Send the user's goal — the leader will read it and start asking questions
        log.info("qa_goal_sent", swarm_id=self.swarm_id, goal_len=len(goal))
        try:
            await self.qa_session.send(
                f"A user has submitted the following goal. Interview them to gather "
                f"enough context to right-size the solution, then call begin_swarm "
                f"with a refined goal.\n\nUser's goal:\n{goal}"
            )
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            log.warning("qa_init_response_timeout", swarm_id=self.swarm_id)
        finally:
            unsubscribe()

        # Emit complete message for the initial response
        if delta_parts:
            await self._emit(
                "leader.chat_message",
                {
                    "content": "".join(delta_parts),
                    "message_id": message_id,
                },
            )

        # Wait for begin_swarm tool call (set by qa_chat messages or leader auto-completing)
        timeout = self.config.get("timeout", 300)
        try:
            await asyncio.wait_for(self.qa_complete.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            log.warning("qa_timeout", swarm_id=self.swarm_id)

        refined = goal_holder[0] if goal_holder else self.qa_refined_goal or goal
        self.qa_refined_goal = refined
        log.info("qa_complete", swarm_id=self.swarm_id, refined_len=len(refined))
        return refined

    async def qa_chat(self, message: str) -> str:
        """Send a user message to the Q&A session and return the leader's response."""
        if not self.qa_session:
            raise ValueError("No Q&A session available")

        log.info("qa_chat_start", swarm_id=self.swarm_id, message_len=len(message))

        async with self._chat_lock:
            done = asyncio.Event()
            text_content: list[str] = []
            delta_parts: list[str] = []
            message_id = f"qa-{id(message)}"

            def _on_event(event: Any) -> None:
                raw = getattr(event, "type", "")
                et = getattr(raw, "value", str(raw)).lower()
                if "idle" in et or ("session" in et and "error" in et):
                    done.set()
                if "assistant.message" in et and "delta" not in et:
                    data = getattr(event, "data", None)
                    content = getattr(data, "content", None)
                    if content and str(content).strip():
                        text_content.append(str(content))
                        self.event_bus.emit_sync(
                            "leader.chat_delta",
                            {
                                "delta": str(content),
                                "message_id": message_id,
                                "swarm_id": self.swarm_id,
                            },
                        )
                if "assistant.message_delta" in et:
                    data = getattr(event, "data", None)
                    delta = getattr(data, "content", "")
                    if delta:
                        delta_parts.append(str(delta))
                        self.event_bus.emit_sync(
                            "leader.chat_delta",
                            {
                                "delta": str(delta),
                                "message_id": message_id,
                                "swarm_id": self.swarm_id,
                            },
                        )

            unsubscribe = self.qa_session.on(_on_event)
            timeout = self.config.get("timeout", 300)

            try:
                await self.qa_session.send(message)
                await asyncio.wait_for(done.wait(), timeout=timeout)
            except (TimeoutError, asyncio.TimeoutError):
                log.warning("qa_chat_timeout", swarm_id=self.swarm_id)
            finally:
                unsubscribe()

            response = "\n".join(text_content) if text_content else "".join(delta_parts) if delta_parts else ""
            log.info("qa_chat_complete", swarm_id=self.swarm_id, response_len=len(response))
            await self._emit(
                "leader.chat_message",
                {
                    "content": response,
                    "message_id": message_id,
                },
            )
            return response

    async def run(self, goal: str) -> str:
        """Full swarm lifecycle. Returns final report."""
        try:
            if self.work_dir:
                self.work_dir.mkdir(parents=True, exist_ok=True)
                log.info("work_dir_created", path=str(self.work_dir))
                (self.work_dir / "goal.md").write_text(f"# Goal\n\n{goal}\n", encoding="utf-8")

            log.info(
                "swarm_phase_planning",
                swarm_id=self.swarm_id,
                goal_len=len(goal),
                template=self.template.key if self.template else None,
                client_type=type(self.client).__name__ if self.client else "None",
            )
            await self._emit("swarm.phase_changed", {"phase": "planning"})
            if self.service:
                await self.service.update_phase("planning")
            plan = await self._plan(goal)
            task_count = len(plan.get("tasks", []))
            log.info("swarm_plan_received", swarm_id=self.swarm_id, task_count=task_count)

            log.info("swarm_phase_spawning", swarm_id=self.swarm_id)
            await self._spawn(plan)
            log.info("swarm_agents_spawned", swarm_id=self.swarm_id, agent_count=len(self.agents))

            log.info("swarm_phase_executing", swarm_id=self.swarm_id)
            await self._execute()

            # Pause/continue loop — re-pause if continue also exhausts rounds
            while True:
                all_tasks_post = await self.task_board.get_tasks()
                actionable = [
                    t
                    for t in all_tasks_post
                    if t.status in (TaskStatus.BLOCKED, TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
                ]
                if not actionable:
                    break

                self._continue_event = asyncio.Event()
                self._continue_action = ""
                await self._emit(
                    "swarm.suspended",
                    {
                        "remaining_tasks": len(actionable),
                        "max_rounds": self.config.get("max_rounds", 8),
                        "reason": "rounds_exhausted",
                    },
                )

                suspend_timeout: float = self.config.get("suspend_timeout", 1800)
                try:
                    await asyncio.wait_for(
                        self._continue_event.wait(),
                        timeout=suspend_timeout,
                    )
                except asyncio.TimeoutError:
                    self._continue_action = "suspend"

                if self._continue_action == "continue":
                    await self._execute()
                    continue  # re-check for remaining actionable tasks
                elif self._continue_action == "suspend":
                    if self.service and hasattr(self.service, "suspend"):
                        await self.service.suspend("rounds_exhausted")
                    await self._cleanup_agents()
                    await self._emit("swarm.phase_changed", {"phase": "suspended"})
                    if self.service:
                        await self.service.update_phase("suspended")
                    return ""
                else:
                    break  # "skip" — fall through to synthesis

            await self._cleanup_agents()

            log.info("swarm_phase_synthesizing", swarm_id=self.swarm_id)
            report = await self._synthesize(goal)
            log.info("swarm_complete", swarm_id=self.swarm_id, report_len=len(report) if report else 0)
            return report
        except Exception as e:
            log.error("swarm_lifecycle_error", swarm_id=self.swarm_id, error=str(e), exc_info=True)
            await self._emit("swarm.error", {"message": str(e)})
            raise

    # ------------------------------------------------------------------
    # Resume: parallel entry point (skips plan/spawn)
    # ------------------------------------------------------------------

    async def resume(self, goal: str) -> str:
        """Resume swarm from persisted state. Skips plan/spawn, rebuilds from DB."""
        if not self.service:
            raise RuntimeError("Cannot resume without a service")

        await self.service.load(self.swarm_id)

        # Rebuild agents from DB state
        await self._rebuild_agents()

        # Execute
        await self._execute()

        # Same pause/continue loop as run()
        while True:
            all_tasks = await self.task_board.get_tasks()
            actionable = [
                t for t in all_tasks if t.status in (TaskStatus.BLOCKED, TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
            ]
            if not actionable:
                break

            self._continue_event = asyncio.Event()
            self._continue_action = ""
            await self._emit(
                "swarm.suspended",
                {
                    "remaining_tasks": len(actionable),
                    "max_rounds": self.config.get("max_rounds", 8),
                    "reason": "rounds_exhausted",
                },
            )

            suspend_timeout: float = self.config.get("suspend_timeout", 1800)
            try:
                await asyncio.wait_for(
                    self._continue_event.wait(),
                    timeout=suspend_timeout,
                )
            except asyncio.TimeoutError:
                self._continue_action = "suspend"

            if self._continue_action == "continue":
                await self._execute()
                continue  # re-check for remaining actionable tasks
            elif self._continue_action == "suspend":
                if self.service and hasattr(self.service, "suspend"):
                    await self.service.suspend("rounds_exhausted")
                await self._cleanup_agents()
                await self._emit("swarm.phase_changed", {"phase": "suspended"})
                if self.service:
                    await self.service.update_phase("suspended")
                return ""
            else:
                break  # "skip" — fall through to synthesis

        await self._cleanup_agents()
        report = await self._synthesize(goal)
        return report

    async def _rebuild_agents(self) -> None:
        """Recreate SwarmAgent instances from persisted registry and resume sessions."""
        self.agents.clear()
        agent_entries = await self.registry.get_all()
        for info in agent_entries:
            name = info.name

            # Look up template agent def if available
            agent_def: AgentDefinition | None = None
            if self.template:
                agent_def = next((a for a in self.template.agents if a.name == name), None)

            agent = SwarmAgent(
                name=name,
                role=info.role,
                display_name=info.display_name,
                task_board=self.task_board,
                inbox=self.inbox,
                registry=self.registry,
                event_bus=self.event_bus,
                available_tools=agent_def.tools if agent_def else None,
                prompt_template=agent_def.prompt_template if agent_def else None,
                system_preamble=self.system_preamble,
                system_tools=self.system_tools,
                model=self.model,
                work_dir=self.work_dir,
                swarm_id=self.swarm_id,
                mcp_servers=self._get_mcp_servers(),
            )

            # Create a fresh session — true session resume requires
            # session_id from DB agents table (future enhancement)
            if self.client_factory:
                client = await self.client_factory()
                await agent.create_session(client, owns_client=True)
            else:
                await agent.create_session(self.client)

            self.agents[name] = agent

        await self._emit("swarm.phase_changed", {"phase": "spawning"})
        if self.service:
            await self.service.update_phase("spawning")
        await self._emit("swarm.spawn_complete", {"agent_count": len(self.agents)})

    # ------------------------------------------------------------------
    # Phase 1: Planning (tool-based structured output)
    # ------------------------------------------------------------------

    async def _plan(self, goal: str) -> dict[str, Any]:
        """Leader calls create_plan tool to submit structured plan.

        The plan is captured via the tool handler, not parsed from text.
        """
        leader_prompt = self.template.leader_prompt if self.template else LEADER_SYSTEM_PROMPT
        plan_holder: list[dict[str, Any]] = []
        plan_tool = create_plan_tool(plan_holder)

        mcp_servers = self._get_mcp_servers()
        skill_dirs = [str(self.template.skills_dir)] if self.template and self.template.skills_dir else None
        session = await _create_session_with_tools(
            self.client,
            leader_prompt,
            [plan_tool],
            mcp_servers=mcp_servers,
            skill_directories=skill_dirs,
            model=self.model,
        )

        # Event-driven: wait for turn_end (same pattern as SwarmAgent)
        done = asyncio.Event()

        def _on_event(event: Any) -> None:
            raw = getattr(event, "type", "")
            event_type = getattr(raw, "value", str(raw)).lower()
            if "turn_end" in event_type or ("session" in event_type and "error" in event_type) or "idle" in event_type:
                done.set()

        unsubscribe = session.on(_on_event)
        timeout = self.config.get("timeout", 300)

        try:
            await session.send(goal)
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            pass  # Check plan_holder below
        finally:
            unsubscribe()

        if not plan_holder:
            raise ValueError("Leader did not submit a plan via create_plan tool")

        plan = plan_holder[0]

        # Create tasks on the board
        tasks_data = plan.get("tasks", [])
        task_ids: list[str] = [f"task-{idx}" for idx in range(len(tasks_data))]

        for idx, t in enumerate(tasks_data):
            blocked_by = [task_ids[i] for i in t.get("blocked_by_indices", [])]
            task = await self.task_board.add_task(
                id=task_ids[idx],
                subject=t["subject"],
                description=t["description"],
                worker_role=t["worker_role"],
                worker_name=t["worker_name"],
                blocked_by=blocked_by,
            )
            await self._emit("task.created", {"task": task.to_dict()})

        await self._emit("swarm.plan_complete", {"task_count": len(tasks_data)})
        return plan

    # ------------------------------------------------------------------
    # Phase 2: Spawning workers
    # ------------------------------------------------------------------

    async def _spawn(self, plan: dict[str, Any]) -> None:
        """Create SwarmAgents for each unique worker in the plan."""
        seen: set[str] = set()
        for t in plan.get("tasks", []):
            name = t["worker_name"]
            if name in seen:
                continue
            seen.add(name)

            role = t["worker_role"]
            display_name = name.replace("_", " ").title()

            # Use template-specific agent config if available
            agent_available_tools: list[str] | None = None
            agent_prompt_template: str | None = None
            system_preamble = ""
            agent_def: AgentDefinition | None = None
            if self.template:
                agent_def = next((a for a in self.template.agents if a.name == name), None)
                if agent_def:
                    self._agent_defs[name] = agent_def
                    display_name = agent_def.display_name
                    role = agent_def.description or role
                    agent_available_tools = agent_def.tools  # None = all, list = built-in whitelist
                    agent_prompt_template = agent_def.prompt_template

            system_preamble = self.system_preamble

            # MCP servers and skills from template (if available)
            mcp_servers = self._get_mcp_servers()
            skill_dirs = [str(self.template.skills_dir)] if self.template and self.template.skills_dir else None

            # Compute per-worker disabled_skills from skills allowlist
            disabled_skills: list[str] | None = None
            if self.template and agent_def and agent_def.skills is not None:
                if agent_def.skills == ["*"] or not agent_def.skills:
                    # Wildcard = no filtering; empty = disable all
                    if not agent_def.skills:
                        disabled_skills = (
                            sorted(self.template.all_skill_names) if self.template.all_skill_names else None
                        )
                else:
                    # Map directory names to actual skill names
                    worker_skill_names = {
                        self.template.skill_name_map[dir_name]
                        for dir_name in agent_def.skills
                        if dir_name in self.template.skill_name_map
                    }
                    to_disable = self.template.all_skill_names - worker_skill_names
                    disabled_skills = sorted(to_disable) if to_disable else None

            agent = SwarmAgent(
                name=name,
                role=role,
                display_name=display_name,
                task_board=self.task_board,
                inbox=self.inbox,
                registry=self.registry,
                event_bus=self.event_bus,
                available_tools=agent_available_tools,
                prompt_template=agent_prompt_template,
                system_preamble=system_preamble,
                system_tools=self.system_tools,
                model=self.model,
                work_dir=self.work_dir,
                swarm_id=self.swarm_id,
                mcp_servers=mcp_servers,
                skill_directories=skill_dirs,
                disabled_skills=disabled_skills,
            )
            # Resolve max_retries: worker override > template default > hardcoded 2
            if agent_def and agent_def.max_retries is not None:
                agent.max_retries = agent_def.max_retries
            elif self.template:
                agent.max_retries = self.template.max_retries

            if self.client_factory:
                agent_client = await self.client_factory()
                await agent.create_session(agent_client, owns_client=True)
            else:
                await agent.create_session(self.client)
            self.agents[name] = agent

            await self.registry.register(name, role, display_name)
            self.inbox.register_agent(name)
            await self._emit(
                "agent.spawned",
                {
                    "agent": {
                        "name": name,
                        "role": role,
                        "display_name": display_name,
                        "status": "idle",
                        "tasks_completed": 0,
                    }
                },
            )

        await self._emit("swarm.phase_changed", {"phase": "spawning"})
        if self.service:
            await self.service.update_phase("spawning")
        await self._emit("swarm.spawn_complete", {"agent_count": len(self.agents)})

    # ------------------------------------------------------------------
    # Work directory file watcher
    # ------------------------------------------------------------------

    async def _scan_work_dir(self) -> None:
        """Scan work directory for new files and emit file.created events."""
        if not self.work_dir or not self.work_dir.is_dir():
            return
        for f in sorted(self.work_dir.rglob("*")):
            if not f.is_file():
                continue
            rel_path = str(f.relative_to(self.work_dir))
            if rel_path not in self._known_files:
                self._known_files.add(rel_path)
                await self._emit(
                    "file.created",
                    {
                        "filename": rel_path,
                        "size_bytes": f.stat().st_size,
                    },
                )

    # ------------------------------------------------------------------
    # Swarm lifecycle signals (for suspend/resume UI)
    # ------------------------------------------------------------------

    def signal_continue(self) -> None:
        """Signal the orchestrator to continue execution after pause."""
        self._continue_action = "continue"
        if self._continue_event:
            self._continue_event.set()

    def signal_skip(self) -> None:
        """Signal the orchestrator to skip to synthesis after pause."""
        self._continue_action = "skip"
        if self._continue_event:
            self._continue_event.set()

    # ------------------------------------------------------------------
    # Agent session resume (for failed agent retry)
    # ------------------------------------------------------------------

    async def resume_agent(self, agent_name: str, nudge: str = "") -> None:
        """Resume a failed agent's session, preserving conversation history."""
        if agent_name not in self.agents:
            raise KeyError(f"Agent '{agent_name}' not found")
        agent = self.agents[agent_name]
        client = agent._client or self.client
        default_nudge = "Your previous attempt failed. Try a different approach."
        await agent.resume_session(client, nudge or default_nudge)
        await self._emit("agent.resumed", {"agent_name": agent_name})

    async def _mark_task_failed(self, task_id: str, worker_name: str, error: str) -> None:
        """Mark a task as FAILED and emit failure events."""
        log.warning("agent_task_failed", agent=worker_name, task_id=task_id, error=error)
        current_task = next(
            (t for t in await self.task_board.get_tasks() if t.id == task_id),
            None,
        )
        if current_task and current_task.status == TaskStatus.IN_PROGRESS:
            await self.task_board.update_status(task_id, "failed", error)
        await self._emit(
            "swarm.task_failed",
            {"task_id": task_id, "agent": worker_name, "error": error},
        )
        await self._emit(
            "agent.status_changed",
            {"agent_name": worker_name, "status": "failed"},
        )

    # ------------------------------------------------------------------
    # Ephemeral agent creation (for scalable workers)
    # ------------------------------------------------------------------

    async def _create_ephemeral_agent(self, worker_name: str) -> SwarmAgent:
        """Create an ephemeral SwarmAgent with its own session for a scalable worker."""
        base = self.agents[worker_name]
        ephemeral = SwarmAgent(
            name=base.name,
            role=base.role,
            display_name=base.display_name,
            task_board=base.task_board,
            inbox=base.inbox,
            registry=base.registry,
            event_bus=base.event_bus,
            available_tools=base.available_tools,
            prompt_template=base.prompt_template,
            system_preamble=base.system_preamble,
            system_tools=base.system_tools,
            model=base.model,
            work_dir=base.work_dir,
            swarm_id=base.swarm_id,
            mcp_servers=base.mcp_servers,
            skill_directories=base.skill_directories,
            disabled_skills=base.disabled_skills,
        )
        if self.client_factory:
            agent_client = await self.client_factory()
            await ephemeral.create_session(agent_client, owns_client=True)
        else:
            await ephemeral.create_session(self.client)
        return ephemeral

    # ------------------------------------------------------------------
    # Phase 3: Round-based execution
    # ------------------------------------------------------------------

    async def _execute(self) -> None:
        """Round-based execution with max_instances support.

        Workers with max_instances > 1 can run multiple tasks concurrently
        via ephemeral agent sessions.
        """
        max_rounds = self.config.get("max_rounds", 3)
        timeout = self.config.get("timeout", 300)

        await self._emit("swarm.phase_changed", {"phase": "executing"})
        if self.service:
            await self.service.update_phase("executing")

        for round_num in range(1, max_rounds + 1):
            if self._cancelled:
                break

            if self.service and hasattr(self.service, "update_round"):
                await self.service.update_round(round_num)

            runnable = await self.task_board.get_runnable_tasks()
            if not runnable:
                break

            await self._emit(
                "swarm.round_start",
                {"round": round_num, "runnable_count": len(runnable)},
            )

            # Build per-worker assignment lists, respecting max_instances
            assigned: dict[str, list[Task]] = {}
            for task in runnable:
                worker_name = task.worker_name
                if worker_name not in self.agents:
                    continue
                agent_def = self._agent_defs.get(worker_name)
                max_inst = agent_def.max_instances if agent_def else 1
                worker_tasks = assigned.setdefault(worker_name, [])
                if len(worker_tasks) < max_inst:
                    worker_tasks.append(task)

            # Mark agents as working
            for worker_name in assigned:
                await self._emit(
                    "agent.status_changed",
                    {
                        "agent_name": worker_name,
                        "status": "working",
                    },
                )

            # Prepare execution: base agent for first task, ephemeral for rest
            task_agent_pairs: list[tuple[str, Task]] = []
            ephemeral_agents: list[SwarmAgent] = []

            # Phase 1: Collect ephemeral agent creation coroutines
            creation_coros: list[Any] = []
            execution_plan: list[tuple[SwarmAgent | None, str, Task]] = []
            for worker_name, tasks in assigned.items():
                base_agent = self.agents[worker_name]
                for idx, task in enumerate(tasks):
                    if idx == 0:
                        execution_plan.append((base_agent, worker_name, task))
                    else:
                        creation_coros.append(self._create_ephemeral_agent(worker_name))
                        execution_plan.append((None, worker_name, task))

            # Phase 2: Create all ephemeral agents in parallel
            created = await asyncio.gather(*creation_coros) if creation_coros else []
            ephemeral_agents.extend(created)

            # Phase 3: Assign agents and build execution coroutines
            coros = []
            ephemeral_idx = 0
            for agent_or_none, worker_name, task in execution_plan:
                if agent_or_none is not None:
                    coros.append(agent_or_none.execute_task(task, timeout=timeout))
                else:
                    coros.append(ephemeral_agents[ephemeral_idx].execute_task(task, timeout=timeout))
                    ephemeral_idx += 1
                task_agent_pairs.append((worker_name, task))

            results = await asyncio.gather(*coros, return_exceptions=True)

            # Cleanup ephemeral agents (stop owned clients to avoid CLI subprocess leaks)
            for eph in ephemeral_agents:
                await eph.cleanup()
            ephemeral_agents.clear()

            for (worker_name, task), result in zip(task_agent_pairs, results, strict=False):
                if isinstance(result, Exception):
                    agent = self.agents.get(worker_name)
                    last_error = result

                    # Retry loop: per-task budget, consume before marking FAILED
                    retry_succeeded = False
                    task_retries = 0
                    max_task_retries = agent.max_retries if agent is not None else 0
                    while agent is not None and task_retries < max_task_retries:
                        task_retries += 1
                        agent.retries_used += 1  # observability: total retries across tasks
                        log.info(
                            "task_retry",
                            agent=worker_name,
                            task_id=task.id,
                            attempt=task_retries,
                            max_retries=max_task_retries,
                            error=str(last_error),
                        )
                        client = agent._client or self.client
                        nudge = (
                            f"Your previous attempt failed with: {last_error}. "
                            f"Attempt {task_retries} of {max_task_retries}. "
                            f"Try a different approach."
                        )
                        try:
                            await agent.resume_session(client, nudge)
                            await self.task_board.update_status(task.id, "in_progress")
                            await agent.execute_task(task, timeout=timeout)
                            # Check post-execution status — execute_task can
                            # set FAILED/TIMEOUT without raising
                            refreshed = next(
                                (t for t in await self.task_board.get_tasks() if t.id == task.id),
                                task,
                            )
                            if refreshed.status == TaskStatus.COMPLETED:
                                retry_succeeded = True
                                break
                            last_error = RuntimeError(
                                f"Task {task.id} ended retry with status {refreshed.status.value}"
                            )
                        except Exception as retry_err:
                            last_error = retry_err
                            log.warning(
                                "retry_failed",
                                agent=worker_name,
                                task_id=task.id,
                                attempt=task_retries,
                                error=str(retry_err),
                            )

                    if retry_succeeded:
                        all_tasks_now = await self.task_board.get_tasks()
                        completed_count = sum(
                            1
                            for t in all_tasks_now
                            if t.worker_name == worker_name and t.status == TaskStatus.COMPLETED
                        )
                        await self._emit(
                            "agent.status_changed",
                            {
                                "agent_name": worker_name,
                                "status": "idle",
                                "tasks_completed": completed_count,
                            },
                        )
                    else:
                        await self._mark_task_failed(task.id, worker_name, str(last_error))
                else:
                    # Count completed tasks for this agent
                    all_tasks = await self.task_board.get_tasks()
                    completed_count = sum(
                        1 for t in all_tasks if t.worker_name == worker_name and t.status == TaskStatus.COMPLETED
                    )
                    await self._emit(
                        "agent.status_changed",
                        {
                            "agent_name": worker_name,
                            "status": "idle",
                            "tasks_completed": completed_count,
                        },
                    )

            # Emit task.updated for all tasks that changed this round
            all_tasks = await self.task_board.get_tasks()
            for t in all_tasks:
                await self._emit("task.updated", {"task": t.to_dict()})

            await self._emit("swarm.round_end", {"round": round_num})
            await self._scan_work_dir()

        # Warn if tasks remain after all rounds exhausted
        all_tasks = await self.task_board.get_tasks()
        unfinished = [t for t in all_tasks if t.status not in (TaskStatus.COMPLETED,)]
        if unfinished:
            log.warning(
                "swarm_rounds_exhausted", swarm_id=self.swarm_id, remaining_tasks=len(unfinished), max_rounds=max_rounds
            )
            await self._emit(
                "swarm.rounds_exhausted",
                {
                    "remaining_tasks": len(unfinished),
                    "max_rounds": max_rounds,
                },
            )

    # ------------------------------------------------------------------
    # Phase 4: Synthesis (tool-based structured output)
    # ------------------------------------------------------------------

    async def _synthesize(self, goal: str) -> str:
        """Synthesize final report using event-driven pattern (no send_and_wait).

        Uses session.send() + session.on() to capture assistant.message text.
        Waits for turn_end/idle instead of a fixed timeout — the CLI emits
        session.idle when truly done, so we don't miss late responses.
        """
        await self._emit("swarm.phase_changed", {"phase": "synthesizing"})
        if self.service:
            await self.service.update_phase("synthesizing")
        all_tasks = await self.task_board.get_tasks()
        task_results = "\n\n".join(
            f"## {t.subject} (by {t.worker_name})\nStatus: {t.status.value}\nResult: {t.result}" for t in all_tasks
        )

        # Include work directory files so synthesis agent has full research content
        work_dir_content = ""
        if self.work_dir and self.work_dir.is_dir():
            file_parts: list[str] = []
            for f in sorted(self.work_dir.rglob("*.md")):
                try:
                    text = f.read_text(encoding="utf-8")
                    if text.strip():
                        file_parts.append(f"### File: {f.name}\n\n{text}")
                except Exception:  # noqa: S110
                    pass  # Skip unreadable files (binary, encoding issues)
            if file_parts:
                work_dir_content = "\n\n---\n\n# Research Files from Work Directory\n\n" + "\n\n---\n\n".join(
                    file_parts
                )

        synthesis_template = self.template.synthesis_prompt if self.template else SYNTHESIS_PROMPT_TEMPLATE
        synthesis_prompt = synthesis_template.format(
            task_results=task_results + work_dir_content,
            goal=goal,
        )

        synthesis_system = (
            self.template.leader_prompt
            if self.template
            else "You are a synthesis agent. Provide a comprehensive report."
        )

        synthesis_session_id = f"synth-{self.swarm_id}" if self.swarm_id else None
        synth_mcp = self._get_mcp_servers()
        synth_skills = [str(self.template.skills_dir)] if self.template and self.template.skills_dir else None
        try:
            session = await _create_session_with_tools(
                self.client,
                synthesis_system,
                [],
                session_id=synthesis_session_id,
                mcp_servers=synth_mcp,
                skill_directories=synth_skills,
                model=self.model,
            )
        except TypeError:
            session = await self.client.create_session()
        self.synthesis_session_id = synthesis_session_id

        # Event-driven: capture text from assistant.message, wait for session.idle
        # NOT turn_end — agents do multiple turns per task; idle = truly done
        done = asyncio.Event()
        text_content: list[str] = []
        delta_parts: list[str] = []

        def _on_event(event: Any) -> None:
            raw = getattr(event, "type", "")
            et = getattr(raw, "value", str(raw)).lower()

            if "idle" in et or ("session" in et and "error" in et):
                done.set()
            # Stream deltas to frontend and accumulate
            if "assistant.message_delta" in et:
                data = getattr(event, "data", None)
                delta = getattr(data, "content", "") or getattr(data, "delta_content", "")
                if delta:
                    delta_parts.append(str(delta))
                    self.event_bus.emit_sync(
                        "leader.report_delta",
                        {
                            "delta": str(delta),
                            "swarm_id": self.swarm_id,
                        },
                    )
            # Capture assistant text
            if "assistant.message" in et and "delta" not in et:
                data = getattr(event, "data", None)
                content = getattr(data, "content", None)
                if content and str(content).strip():
                    text_content.append(str(content))

        unsubscribe = session.on(_on_event)
        timeout = self.config.get("timeout", 300)

        try:
            await session.send(synthesis_prompt)
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            log.warning("synthesis_timeout", timeout=timeout)
        finally:
            unsubscribe()

        report = (
            "\n".join(text_content)
            if text_content
            else "".join(delta_parts)
            if delta_parts
            else "(Synthesis produced no output)"
        )

        await self._emit("leader.report", {"content": report})
        await self._emit("swarm.phase_changed", {"phase": "complete"})
        if self.service:
            await self.service.update_phase("complete")
        await self._scan_work_dir()
        await self._emit("swarm.synthesis_complete", {})
        return report
