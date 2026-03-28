"""SwarmOrchestrator: manages the full swarm lifecycle (plan, spawn, execute, synthesize)."""

from __future__ import annotations

import asyncio
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
from backend.swarm.template_loader import LoadedTemplate
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
) -> Any:
    """Create a session with the given tools, compatible with real SDK and mocks."""
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
        return await client.create_session(**kwargs)
    except TypeError:
        # Fallback for mocks that don't accept all SDK kwargs
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
    ) -> None:
        self.client = client
        self.event_bus = event_bus
        self.task_board = TaskBoard()
        self.inbox = InboxSystem()
        self.registry = TeamRegistry()
        self.agents: dict[str, SwarmAgent] = {}
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event with swarm_id attached (if set)."""
        if self.swarm_id:
            data = {**data, "swarm_id": self.swarm_id}
        await self.event_bus.emit(event_type, data)

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

        log.info("chat_start", swarm_id=self.swarm_id,
                 session_id=self.synthesis_session_id, message_len=len(message))

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
                        self.event_bus.emit_sync("leader.chat_delta", {
                            "delta": str(content),
                            "message_id": message_id,
                            "swarm_id": self.swarm_id,
                        })
                # Stream deltas via EventBus.emit_sync and accumulate
                if "assistant.message_delta" in et:
                    data = getattr(event, "data", None)
                    delta = getattr(data, "content", "")
                    if delta:
                        delta_parts.append(str(delta))
                        self.event_bus.emit_sync("leader.chat_delta", {
                            "delta": str(delta),
                            "message_id": message_id,
                            "swarm_id": self.swarm_id,
                        })
                # Tool events
                if "tool.execution_start" in et:
                    data = getattr(event, "data", None)
                    tool_name = getattr(data, "tool_name", "")
                    tool_call_id = getattr(data, "tool_call_id", "")
                    tool_call_count[0] += 1
                    log.info("chat_tool_start", swarm_id=self.swarm_id,
                             tool_name=tool_name, tool_call_id=tool_call_id)
                    self.event_bus.emit_sync("leader.chat_tool_start", {
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "message_id": message_id,
                        "swarm_id": self.swarm_id,
                    })
                if "tool.execution_complete" in et:
                    data = getattr(event, "data", None)
                    tool_call_id = getattr(data, "tool_call_id", "")
                    success = str(getattr(data, "success", "")).lower() == "true"
                    log.info("chat_tool_result", swarm_id=self.swarm_id,
                             tool_call_id=tool_call_id, success=success)
                    self.event_bus.emit_sync("leader.chat_tool_result", {
                        "tool_call_id": tool_call_id,
                        "success": success,
                        "message_id": message_id,
                        "swarm_id": self.swarm_id,
                    })

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

            response = (
                "\n".join(text_content) if text_content
                else "".join(delta_parts) if delta_parts
                else ""
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log.info("chat_complete", swarm_id=self.swarm_id,
                     response_len=len(response), chunks=len(text_content),
                     tool_calls=tool_call_count[0], duration_ms=duration_ms)
            await self._emit("leader.chat_message", {
                "content": response,
                "message_id": message_id,
            })
            return response

    async def run(self, goal: str) -> str:
        """Full swarm lifecycle. Returns final report."""
        try:
            if self.work_dir:
                self.work_dir.mkdir(parents=True, exist_ok=True)
                log.info("work_dir_created", path=str(self.work_dir))
            plan = await self._plan(goal)
            await self._spawn(plan)
            await self._execute()
            report = await self._synthesize(goal)
            return report
        except Exception as e:
            await self._emit("swarm.error", {"message": str(e)})
            raise

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

        mcp_servers = self.template.mcp_servers if self.template else None
        skill_dirs = (
            [str(self.template.skills_dir)] if self.template and self.template.skills_dir else None
        )
        session = await _create_session_with_tools(
            self.client, leader_prompt, [plan_tool],
            mcp_servers=mcp_servers, skill_directories=skill_dirs,
        )

        # Event-driven: wait for turn_end (same pattern as SwarmAgent)
        done = asyncio.Event()

        def _on_event(event: Any) -> None:
            raw = getattr(event, "type", "")
            event_type = getattr(raw, "value", str(raw)).lower()
            if "turn_end" in event_type:
                done.set()
            elif "session" in event_type and "error" in event_type:
                done.set()
            elif "idle" in event_type:
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
        await self._emit("swarm.phase_changed", {"phase": "planning"})

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
            if self.template:
                agent_def = next((a for a in self.template.agents if a.name == name), None)
                if agent_def:
                    display_name = agent_def.display_name
                    role = agent_def.description or role
                    agent_available_tools = agent_def.tools  # None = all, list = built-in whitelist
                    agent_prompt_template = agent_def.prompt_template

            system_preamble = self.system_preamble

            # MCP servers and skills from template (if available)
            mcp_servers = self.template.mcp_servers if self.template else None
            skill_dirs = (
                [str(self.template.skills_dir)] if self.template and self.template.skills_dir else None
            )

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
            )
            await agent.create_session(self.client)
            self.agents[name] = agent

            await self.registry.register(name, role, display_name)
            self.inbox.register_agent(name)
            await self._emit("agent.spawned", {
                "agent": {"name": name, "role": role, "display_name": display_name, "status": "idle", "tasks_completed": 0}
            })

        await self._emit("swarm.phase_changed", {"phase": "spawning"})
        await self._emit(
            "swarm.spawn_complete", {"agent_count": len(self.agents)}
        )

    # ------------------------------------------------------------------
    # Phase 3: Round-based execution
    # ------------------------------------------------------------------

    async def _execute(self) -> None:
        """Round-based execution. One task per worker per round."""
        max_rounds = self.config.get("max_rounds", 3)
        timeout = self.config.get("timeout", 300)

        await self._emit("swarm.phase_changed", {"phase": "executing"})

        for round_num in range(1, max_rounds + 1):
            if self._cancelled:
                break

            runnable = await self.task_board.get_runnable_tasks()
            if not runnable:
                break

            await self._emit(
                "swarm.round_start",
                {"round": round_num, "runnable_count": len(runnable)},
            )

            assigned: dict[str, Task] = {}
            for task in runnable:
                if task.worker_name not in assigned and task.worker_name in self.agents:
                    assigned[task.worker_name] = task

            # Mark agents as working
            for worker_name in assigned:
                await self._emit("agent.status_changed", {
                    "agent_name": worker_name, "status": "working",
                })

            results = await asyncio.gather(
                *[
                    self.agents[worker_name].execute_task(task, timeout=timeout)
                    for worker_name, task in assigned.items()
                ],
                return_exceptions=True,
            )

            for (worker_name, task), result in zip(assigned.items(), results):
                if isinstance(result, Exception):
                    log.warning("agent_task_failed", agent=worker_name, task_id=task.id, error=str(result))
                    current_task = next(
                        (t for t in await self.task_board.get_tasks() if t.id == task.id),
                        None,
                    )
                    if current_task and current_task.status == TaskStatus.IN_PROGRESS:
                        await self.task_board.update_status(task.id, "failed", str(result))
                    await self._emit(
                        "swarm.task_failed",
                        {"task_id": task.id, "agent": worker_name, "error": str(result)},
                    )
                    await self._emit("agent.status_changed", {
                        "agent_name": worker_name, "status": "failed",
                    })
                else:
                    # Count completed tasks for this agent
                    all_tasks = await self.task_board.get_tasks()
                    completed_count = sum(
                        1 for t in all_tasks
                        if t.worker_name == worker_name and t.status == TaskStatus.COMPLETED
                    )
                    await self._emit("agent.status_changed", {
                        "agent_name": worker_name, "status": "idle",
                        "tasks_completed": completed_count,
                    })

            # Emit task.updated for all tasks that changed this round
            all_tasks = await self.task_board.get_tasks()
            for t in all_tasks:
                await self._emit("task.updated", {"task": t.to_dict()})

            await self._emit("swarm.round_end", {"round": round_num})

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
        all_tasks = await self.task_board.get_tasks()
        task_results = "\n\n".join(
            f"## {t.subject} (by {t.worker_name})\nStatus: {t.status.value}\nResult: {t.result}"
            for t in all_tasks
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
                except Exception:
                    pass
            if file_parts:
                work_dir_content = (
                    "\n\n---\n\n# Research Files from Work Directory\n\n"
                    + "\n\n---\n\n".join(file_parts)
                )

        synthesis_template = self.template.synthesis_prompt if self.template else SYNTHESIS_PROMPT_TEMPLATE
        synthesis_prompt = synthesis_template.format(
            task_results=task_results + work_dir_content,
            goal=goal,
        )

        synthesis_system = (
            self.template.leader_prompt if self.template
            else "You are a synthesis agent. Provide a comprehensive report."
        )

        synthesis_session_id = f"synth-{self.swarm_id}" if self.swarm_id else None
        synth_mcp = self.template.mcp_servers if self.template else None
        synth_skills = (
            [str(self.template.skills_dir)] if self.template and self.template.skills_dir else None
        )
        try:
            session = await _create_session_with_tools(
                self.client, synthesis_system, [],
                session_id=synthesis_session_id,
                mcp_servers=synth_mcp, skill_directories=synth_skills,
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

            if "idle" in et:
                done.set()
            elif "session" in et and "error" in et:
                done.set()
            # Stream deltas to frontend and accumulate
            if "assistant.message_delta" in et:
                data = getattr(event, "data", None)
                delta = getattr(data, "content", "") or getattr(data, "delta_content", "")
                if delta:
                    delta_parts.append(str(delta))
                    self.event_bus.emit_sync("leader.report_delta", {
                        "delta": str(delta),
                        "swarm_id": self.swarm_id,
                    })
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
            "\n".join(text_content) if text_content
            else "".join(delta_parts) if delta_parts
            else "(Synthesis produced no output)"
        )

        await self._emit("leader.report", {"content": report})
        await self._emit("swarm.phase_changed", {"phase": "complete"})
        await self._emit("swarm.synthesis_complete", {})
        return report
