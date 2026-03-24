"""SwarmOrchestrator: manages the full swarm lifecycle (plan, spawn, execute, synthesize)."""

from __future__ import annotations

import asyncio
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
from backend.swarm.tools import create_plan_tool, create_report_tool

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
) -> Any:
    """Create a session with the given tools, compatible with real SDK and mocks."""
    try:
        return await client.create_session(
            on_permission_request=_approve_all,
            system_message={"mode": "replace", "content": system_prompt},
            tools=tools,
        )
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
    ) -> None:
        self.client = client
        self.event_bus = event_bus
        self.task_board = TaskBoard()
        self.inbox = InboxSystem()
        self.registry = TeamRegistry()
        self.agents: dict[str, SwarmAgent] = {}
        self.config = config or {"max_rounds": 3, "timeout": 300}
        self.template = template
        self.system_preamble = system_preamble
        self.system_tools = system_tools or []
        self.model = model
        self._cancelled = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def cancel(self) -> None:
        """Cancel the swarm execution."""
        self._cancelled = True
        await self.event_bus.emit("swarm.cancelled", {})

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    async def run(self, goal: str) -> str:
        """Full swarm lifecycle. Returns final report."""
        try:
            plan = await self._plan(goal)
            await self._spawn(plan)
            await self._execute()
            report = await self._synthesize(goal)
            return report
        except Exception as e:
            await self.event_bus.emit("swarm.error", {"message": str(e)})
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

        session = await _create_session_with_tools(
            self.client, leader_prompt, [plan_tool],
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
        await self.event_bus.emit("swarm.phase_changed", {"phase": "planning"})

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
            await self.event_bus.emit("task.created", {"task": task.to_dict()})

        await self.event_bus.emit("swarm.plan_complete", {"task_count": len(tasks_data)})
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
            )
            await agent.create_session(self.client)
            self.agents[name] = agent

            await self.registry.register(name, role, display_name)
            self.inbox.register_agent(name)
            await self.event_bus.emit("agent.spawned", {
                "agent": {"name": name, "role": role, "display_name": display_name, "status": "idle", "tasks_completed": 0}
            })

        await self.event_bus.emit("swarm.phase_changed", {"phase": "spawning"})
        await self.event_bus.emit(
            "swarm.spawn_complete", {"agent_count": len(self.agents)}
        )

    # ------------------------------------------------------------------
    # Phase 3: Round-based execution
    # ------------------------------------------------------------------

    async def _execute(self) -> None:
        """Round-based execution. One task per worker per round."""
        max_rounds = self.config.get("max_rounds", 3)
        timeout = self.config.get("timeout", 300)

        await self.event_bus.emit("swarm.phase_changed", {"phase": "executing"})

        for round_num in range(1, max_rounds + 1):
            if self._cancelled:
                break

            runnable = await self.task_board.get_runnable_tasks()
            if not runnable:
                break

            await self.event_bus.emit(
                "swarm.round_start",
                {"round": round_num, "runnable_count": len(runnable)},
            )

            assigned: dict[str, Task] = {}
            for task in runnable:
                if task.worker_name not in assigned and task.worker_name in self.agents:
                    assigned[task.worker_name] = task

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
                    await self.event_bus.emit(
                        "swarm.task_failed",
                        {"task_id": task.id, "agent": worker_name, "error": str(result)},
                    )

            # Emit task.updated for all tasks that changed this round
            all_tasks = await self.task_board.get_tasks()
            for t in all_tasks:
                await self.event_bus.emit("task.updated", {"task": t.to_dict()})

            await self.event_bus.emit("swarm.round_end", {"round": round_num})

    # ------------------------------------------------------------------
    # Phase 4: Synthesis (tool-based structured output)
    # ------------------------------------------------------------------

    async def _synthesize(self, goal: str) -> str:
        """Synthesize final report using event-driven pattern (no send_and_wait).

        Uses session.send() + session.on() to capture assistant.message text.
        Waits for turn_end/idle instead of a fixed timeout — the CLI emits
        session.idle when truly done, so we don't miss late responses.
        """
        await self.event_bus.emit("swarm.phase_changed", {"phase": "synthesizing"})
        all_tasks = await self.task_board.get_tasks()
        task_results = "\n\n".join(
            f"## {t.subject} (by {t.worker_name})\nStatus: {t.status.value}\nResult: {t.result}"
            for t in all_tasks
        )

        synthesis_template = self.template.synthesis_prompt if self.template else SYNTHESIS_PROMPT_TEMPLATE
        synthesis_prompt = synthesis_template.format(
            task_results=task_results,
            goal=goal,
        )

        synthesis_system = (
            self.template.leader_prompt if self.template
            else "You are a synthesis agent. Provide a comprehensive report."
        )

        try:
            session = await _create_session_with_tools(self.client, synthesis_system, [])
        except TypeError:
            session = await self.client.create_session()

        # Event-driven: capture text from assistant.message, wait for turn_end/idle
        done = asyncio.Event()
        text_content: list[str] = []

        def _on_event(event: Any) -> None:
            raw = getattr(event, "type", "")
            et = getattr(raw, "value", str(raw)).lower()

            if "turn_end" in et:
                done.set()
            elif "idle" in et:
                done.set()
            elif "session" in et and "error" in et:
                done.set()
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

        report = "\n".join(text_content) if text_content else "(Synthesis produced no output)"

        await self.event_bus.emit("leader.report", {"content": report})
        await self.event_bus.emit("swarm.phase_changed", {"phase": "complete"})
        await self.event_bus.emit("swarm.synthesis_complete", {})
        return report
