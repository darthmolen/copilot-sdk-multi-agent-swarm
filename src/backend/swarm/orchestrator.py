"""SwarmOrchestrator: manages the full swarm lifecycle (plan, spawn, execute, synthesize)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from backend.events import EventBus
from backend.swarm.agent import SwarmAgent
from backend.swarm.inbox_system import InboxSystem
from backend.swarm.models import Task, TaskStatus
from backend.swarm.prompts import (
    LEADER_SYSTEM_PROMPT,
    SYNTHESIS_PROMPT_TEMPLATE,
    make_worker_prompt,
)
from backend.swarm.task_board import TaskBoard
from backend.swarm.team_registry import TeamRegistry

logger = logging.getLogger(__name__)


class SwarmOrchestrator:
    """Orchestrates the full swarm lifecycle: plan -> spawn -> execute -> synthesize."""

    def __init__(
        self,
        client: Any,
        event_bus: EventBus,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.event_bus = event_bus
        self.task_board = TaskBoard()
        self.inbox = InboxSystem()
        self.registry = TeamRegistry()
        self.agents: dict[str, SwarmAgent] = {}
        self.config = config or {"max_rounds": 3, "timeout": 300}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, goal: str) -> str:
        """Full swarm lifecycle. Returns final report."""
        plan = await self._plan(goal)
        await self._spawn(plan)
        await self._execute()
        report = await self._synthesize(goal)
        return report

    # ------------------------------------------------------------------
    # Phase 1: Planning
    # ------------------------------------------------------------------

    async def _plan(self, goal: str) -> dict[str, Any]:
        """Leader decomposes goal into tasks. Returns parsed JSON plan.

        Retries once on malformed JSON. Raises ValueError after two failures.
        """
        session = await self.client.create_session(system_prompt=LEADER_SYSTEM_PROMPT)
        max_attempts = 2

        plan: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            event = await session.send_and_wait(goal)
            raw = event.content
            try:
                plan = json.loads(raw)
                break
            except (json.JSONDecodeError, TypeError):
                if attempt == max_attempts - 1:
                    raise ValueError(
                        f"Leader returned invalid JSON after {max_attempts} attempts"
                    )
                logger.warning("Leader returned invalid JSON (attempt %d), retrying", attempt + 1)

        assert plan is not None  # guaranteed by the break/raise above

        # Create tasks on the board
        tasks_data = plan.get("tasks", [])
        task_ids: list[str] = []
        for idx, t in enumerate(tasks_data):
            task_id = f"task-{idx}"
            task_ids.append(task_id)

        for idx, t in enumerate(tasks_data):
            blocked_by = [task_ids[i] for i in t.get("blocked_by_indices", [])]
            await self.task_board.add_task(
                id=task_ids[idx],
                subject=t["subject"],
                description=t["description"],
                worker_role=t["worker_role"],
                worker_name=t["worker_name"],
                blocked_by=blocked_by,
            )

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

            agent = SwarmAgent(
                name=name,
                role=role,
                display_name=display_name,
                task_board=self.task_board,
                inbox=self.inbox,
                registry=self.registry,
                event_bus=self.event_bus,
            )
            await agent.create_session(self.client)
            self.agents[name] = agent

            await self.registry.register(name, role, display_name)
            self.inbox.register_agent(name)

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

        for round_num in range(1, max_rounds + 1):
            runnable = await self.task_board.get_runnable_tasks()
            if not runnable:
                break

            await self.event_bus.emit(
                "swarm.round_start",
                {"round": round_num, "runnable_count": len(runnable)},
            )

            # Assign at most one task per worker this round
            assigned: dict[str, Task] = {}
            for task in runnable:
                if task.worker_name not in assigned and task.worker_name in self.agents:
                    assigned[task.worker_name] = task

            # Execute all assigned tasks concurrently using event-driven SwarmAgent
            results = await asyncio.gather(
                *[
                    self.agents[worker_name].execute_task(task, timeout=timeout)
                    for worker_name, task in assigned.items()
                ],
                return_exceptions=True,
            )

            # Process failures
            for (worker_name, task), result in zip(assigned.items(), results):
                if isinstance(result, Exception):
                    logger.error(
                        "Agent %s failed on task %s: %s",
                        worker_name,
                        task.id,
                        result,
                    )
                    # Task may already be marked failed by SwarmAgent.execute_task;
                    # ensure it's marked in case the exception was unexpected
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

            await self.event_bus.emit("swarm.round_end", {"round": round_num})

    # ------------------------------------------------------------------
    # Phase 4: Synthesis
    # ------------------------------------------------------------------

    async def _synthesize(self, goal: str) -> str:
        """Leader synthesizes final report from task results."""
        all_tasks = await self.task_board.get_tasks()
        task_results = "\n\n".join(
            f"## {t.subject} (by {t.worker_name})\nStatus: {t.status.value}\nResult: {t.result}"
            for t in all_tasks
        )

        synthesis_prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            task_results=task_results,
            goal=goal,
        )

        session = await self.client.create_session(system_prompt="You are a synthesis agent.")
        event = await session.send_and_wait(synthesis_prompt)

        await self.event_bus.emit("swarm.synthesis_complete", {})
        return event.content
