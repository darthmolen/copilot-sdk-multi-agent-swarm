"""Tests for SwarmOrchestrator — strict TDD for the full swarm lifecycle."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.events import EventBus
from backend.swarm.event_bridge import SessionEvent, SessionEventData, SessionEventType
from backend.swarm.models import TaskStatus
from backend.swarm.orchestrator import SwarmOrchestrator


# ---------------------------------------------------------------------------
# Sample plan data
# ---------------------------------------------------------------------------

VALID_PLAN = {
    "team_description": "Test team",
    "tasks": [
        {
            "subject": "Task 1",
            "description": "Do thing 1",
            "worker_role": "Analyst",
            "worker_name": "analyst",
            "blocked_by_indices": [],
        },
        {
            "subject": "Task 2",
            "description": "Do thing 2",
            "worker_role": "Writer",
            "worker_name": "writer",
            "blocked_by_indices": [0],
        },
    ],
}

VALID_PLAN_JSON = json.dumps(VALID_PLAN)


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------


@dataclass
class MockEvent:
    """Mimics an SDK event with .content attribute."""

    content: str = ""


class MockLeaderSession:
    """Returns configurable JSON from send_and_wait."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def send_and_wait(self, prompt: str, **kwargs: Any) -> MockEvent:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return MockEvent(content=self._responses[idx])


class MockWorkerSession:
    """Auto-completes: fires turn_end after send()."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def on(self, handler: Any) -> Any:
        self._handler = handler
        return lambda: None

    async def send(self, prompt: str, **kwargs: Any) -> str:
        if self._fail:
            raise RuntimeError("Agent execution failed")
        return "msg-1"


class MockCopilotClient:
    """Mock client that routes session creation to leader or worker sessions."""

    def __init__(
        self,
        leader_responses: list[str] | None = None,
        worker_sessions: dict[str, MockWorkerSession] | None = None,
        synthesis_response: str = "Final report",
    ) -> None:
        self._leader_responses = leader_responses or [VALID_PLAN_JSON]
        self._synthesis_response = synthesis_response
        self._worker_sessions = worker_sessions or {}
        self._session_count = 0
        self._leader_session: MockLeaderSession | None = None
        self._synthesis_session: MockLeaderSession | None = None

    async def create_session(self, system_prompt: str = "", **kwargs: Any) -> Any:
        self._session_count += 1

        # Synthesis session (check before leader to handle isolated calls)
        if "synthesis" in system_prompt.lower() or "You are a synthesis" in system_prompt:
            self._synthesis_session = MockLeaderSession([self._synthesis_response])
            return self._synthesis_session

        # Check if this is a worker session by matching the worker prompt pattern
        for name, session in self._worker_sessions.items():
            display = name.replace("_", " ").title()
            if f"You are {display}" in system_prompt:
                return session

        # Leader session (planning) — created once
        if self._leader_session is None:
            self._leader_session = MockLeaderSession(self._leader_responses)
            return self._leader_session

        # Fallback: return a generic worker session
        return MockWorkerSession()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


def make_orchestrator(
    event_bus: EventBus,
    leader_responses: list[str] | None = None,
    worker_sessions: dict[str, MockWorkerSession] | None = None,
    synthesis_response: str = "Final report",
    config: dict[str, Any] | None = None,
) -> SwarmOrchestrator:
    client = MockCopilotClient(
        leader_responses=leader_responses,
        worker_sessions=worker_sessions,
        synthesis_response=synthesis_response,
    )
    return SwarmOrchestrator(client=client, event_bus=event_bus, config=config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlan:
    async def test_plan_parses_valid_json_into_tasks(self, event_bus: EventBus) -> None:
        """Leader returns valid JSON -> tasks created on TaskBoard with correct blocked_by."""
        orch = make_orchestrator(event_bus)
        plan = await orch._plan("Build something")

        assert plan == VALID_PLAN

        all_tasks = await orch.task_board.get_tasks()
        assert len(all_tasks) == 2

        t0 = all_tasks[0]
        assert t0.id == "task-0"
        assert t0.subject == "Task 1"
        assert t0.worker_name == "analyst"
        assert t0.status == TaskStatus.PENDING
        assert t0.blocked_by == []

        t1 = all_tasks[1]
        assert t1.id == "task-1"
        assert t1.subject == "Task 2"
        assert t1.worker_name == "writer"
        assert t1.status == TaskStatus.BLOCKED
        assert t1.blocked_by == ["task-0"]

    async def test_plan_retries_on_malformed_json(self, event_bus: EventBus) -> None:
        """Leader returns garbage first, valid JSON second -> tasks created (retry logic)."""
        orch = make_orchestrator(
            event_bus, leader_responses=["not valid json!!!", VALID_PLAN_JSON]
        )
        plan = await orch._plan("Build something")

        assert plan == VALID_PLAN
        all_tasks = await orch.task_board.get_tasks()
        assert len(all_tasks) == 2

    async def test_plan_raises_on_double_malformed_json(self, event_bus: EventBus) -> None:
        """Leader returns garbage twice -> raises ValueError."""
        orch = make_orchestrator(
            event_bus, leader_responses=["garbage1", "garbage2"]
        )
        with pytest.raises(ValueError, match="invalid JSON"):
            await orch._plan("Build something")


class TestSpawn:
    async def test_spawn_creates_agents_per_worker(self, event_bus: EventBus) -> None:
        """Spawn creates one SwarmAgent per unique worker in plan."""
        orch = make_orchestrator(event_bus)
        await orch._spawn(VALID_PLAN)

        assert len(orch.agents) == 2
        assert "analyst" in orch.agents
        assert "writer" in orch.agents
        assert orch.agents["analyst"].role == "Analyst"
        assert orch.agents["writer"].role == "Writer"

    async def test_spawn_registers_in_team_registry(self, event_bus: EventBus) -> None:
        """All agents registered in TeamRegistry."""
        orch = make_orchestrator(event_bus)
        await orch._spawn(VALID_PLAN)

        all_agents = await orch.registry.get_all()
        names = {a.name for a in all_agents}
        assert names == {"analyst", "writer"}

    async def test_spawn_deduplicates_workers(self, event_bus: EventBus) -> None:
        """Workers with the same name appearing in multiple tasks are only spawned once."""
        plan_with_dups = {
            "team_description": "Dup team",
            "tasks": [
                {
                    "subject": "T1",
                    "description": "D1",
                    "worker_role": "Analyst",
                    "worker_name": "analyst",
                    "blocked_by_indices": [],
                },
                {
                    "subject": "T2",
                    "description": "D2",
                    "worker_role": "Analyst",
                    "worker_name": "analyst",
                    "blocked_by_indices": [],
                },
            ],
        }
        orch = make_orchestrator(event_bus)
        await orch._spawn(plan_with_dups)
        assert len(orch.agents) == 1


class TestExecute:
    async def test_execute_round_runs_pending_tasks(self, event_bus: EventBus) -> None:
        """Tasks in PENDING get executed, move through lifecycle."""
        orch = make_orchestrator(event_bus)
        plan = await orch._plan("Build something")
        await orch._spawn(plan)
        await orch._execute()

        all_tasks = await orch.task_board.get_tasks()
        # Task 0 should be completed (was PENDING, got executed)
        t0 = next(t for t in all_tasks if t.id == "task-0")
        assert t0.status == TaskStatus.COMPLETED

        # Task 1 was BLOCKED by task-0. After task-0 completes, it becomes PENDING
        # and gets executed in the next round.
        t1 = next(t for t in all_tasks if t.id == "task-1")
        assert t1.status == TaskStatus.COMPLETED

    async def test_execute_respects_round_limit(self, event_bus: EventBus) -> None:
        """max_rounds=1 stops after 1 round even with remaining tasks."""
        orch = make_orchestrator(event_bus, config={"max_rounds": 1, "timeout": 300})
        plan = await orch._plan("Build something")
        await orch._spawn(plan)
        await orch._execute()

        all_tasks = await orch.task_board.get_tasks()
        t0 = next(t for t in all_tasks if t.id == "task-0")
        assert t0.status == TaskStatus.COMPLETED

        # Task 1 was blocked, became pending after task-0 completed,
        # but we only had 1 round so it stays pending
        t1 = next(t for t in all_tasks if t.id == "task-1")
        assert t1.status == TaskStatus.PENDING

    async def test_execute_handles_agent_failure(self, event_bus: EventBus) -> None:
        """One agent fails, others complete, failed task marked 'failed'."""
        worker_sessions = {
            "analyst": MockWorkerSession(fail=True),
            "writer": MockWorkerSession(fail=False),
        }

        # Use a plan where both tasks are independent (no dependencies)
        independent_plan = {
            "team_description": "Test team",
            "tasks": [
                {
                    "subject": "Task 1",
                    "description": "Do thing 1",
                    "worker_role": "Analyst",
                    "worker_name": "analyst",
                    "blocked_by_indices": [],
                },
                {
                    "subject": "Task 2",
                    "description": "Do thing 2",
                    "worker_role": "Writer",
                    "worker_name": "writer",
                    "blocked_by_indices": [],
                },
            ],
        }
        independent_plan_json = json.dumps(independent_plan)

        orch = make_orchestrator(
            event_bus,
            leader_responses=[independent_plan_json],
            worker_sessions=worker_sessions,
        )
        plan = await orch._plan("Build something")
        await orch._spawn(plan)
        await orch._execute()

        all_tasks = await orch.task_board.get_tasks()
        t0 = next(t for t in all_tasks if t.id == "task-0")
        assert t0.status == TaskStatus.FAILED

        t1 = next(t for t in all_tasks if t.id == "task-1")
        assert t1.status == TaskStatus.COMPLETED


class TestSynthesize:
    async def test_synthesize_returns_report(self, event_bus: EventBus) -> None:
        """Leader session receives synthesis prompt, returns report text."""
        orch = make_orchestrator(event_bus, synthesis_response="The final synthesis report")

        # Add a completed task so synthesis has something to work with
        await orch.task_board.add_task(
            id="task-0",
            subject="Research",
            description="Do research",
            worker_role="Analyst",
            worker_name="analyst",
        )
        await orch.task_board.update_status("task-0", "completed", "Research findings")

        report = await orch._synthesize("Build something great")
        assert report == "The final synthesis report"


class TestFullLifecycle:
    async def test_full_run_lifecycle(self, event_bus: EventBus) -> None:
        """End-to-end: plan -> spawn -> execute -> synthesize with simple 2-task plan."""
        events_received: list[tuple[str, dict]] = []

        def track_events(event_type: str, data: dict) -> None:
            events_received.append((event_type, data))

        event_bus.subscribe(track_events)

        orch = make_orchestrator(
            event_bus,
            leader_responses=[VALID_PLAN_JSON],
            synthesis_response="Everything is done. Great work!",
        )

        report = await orch.run("Build something amazing")

        # Verify the report
        assert report == "Everything is done. Great work!"

        # Verify tasks were created and completed
        all_tasks = await orch.task_board.get_tasks()
        assert len(all_tasks) == 2
        for t in all_tasks:
            assert t.status == TaskStatus.COMPLETED

        # Verify agents were created
        assert len(orch.agents) == 2

        # Verify key events were emitted
        event_types = [e[0] for e in events_received]
        assert "swarm.plan_complete" in event_types
        assert "swarm.spawn_complete" in event_types
        assert "swarm.round_start" in event_types
        assert "swarm.synthesis_complete" in event_types
