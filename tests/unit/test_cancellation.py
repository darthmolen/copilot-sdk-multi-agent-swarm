"""TDD tests for cancellation support and error handling (Phase 5)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.rest import swarm_store
from backend.events import EventBus
from backend.main import app
from backend.swarm.event_bridge import SessionEvent, SessionEventData, SessionEventType
from backend.swarm.orchestrator import SwarmOrchestrator
from backend.swarm.tools import Tool, ToolInvocation

# Re-use mock infrastructure from test_orchestrator
from tests.unit.test_orchestrator import (
    VALID_PLAN,
    MockCopilotClient,
    MockToolCallingSession,
    MockWorkerSession,
    make_orchestrator,
)


# ---------------------------------------------------------------------------
# Plan with 3 rounds of tasks (sequential chain via blocked_by)
# ---------------------------------------------------------------------------

THREE_ROUND_PLAN = {
    "team_description": "Three-round team",
    "tasks": [
        {"subject": "Task A", "description": "Do A", "worker_role": "Worker", "worker_name": "worker_a", "blocked_by_indices": []},
        {"subject": "Task B", "description": "Do B", "worker_role": "Worker", "worker_name": "worker_b", "blocked_by_indices": [0]},
        {"subject": "Task C", "description": "Do C", "worker_role": "Worker", "worker_name": "worker_c", "blocked_by_indices": [1]},
    ],
}


# ---------------------------------------------------------------------------
# Slow worker session that introduces a delay (for mid-execution cancel)
# ---------------------------------------------------------------------------


class SlowMockWorkerSession(MockWorkerSession):
    """Worker session that waits before firing ASSISTANT_TURN_END."""

    def __init__(self, delay: float = 0.05, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._delay = delay

    async def send(self, prompt: str, **kwargs: Any) -> str:
        await asyncio.sleep(self._delay)
        for h in list(self._handlers):
            h(SessionEvent(
                type=SessionEventType.SESSION_IDLE,
                data=SessionEventData(turn_id="turn-1"),
            ))
        return "msg-1"


class SlowMockCopilotClient(MockCopilotClient):
    """Client that returns slow worker sessions."""

    def __init__(self, worker_delay: float = 0.05, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._worker_delay = worker_delay

    async def create_session(self, **kwargs: Any) -> Any:
        tools = kwargs.get("tools", []) or []
        tool_names = {t.name for t in tools}
        if "task_update" in tool_names:
            session = SlowMockWorkerSession(delay=self._worker_delay)
            session._tools = kwargs.get("tools", []) or []
            return session
        return await super().create_session(**kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


# ---------------------------------------------------------------------------
# Tests: cancellation flag and event
# ---------------------------------------------------------------------------


class TestCancelFlag:
    async def test_cancel_sets_cancelled_flag(self, event_bus: EventBus) -> None:
        orch = make_orchestrator(event_bus)
        assert orch.is_cancelled is False
        await orch.cancel()
        assert orch.is_cancelled is True

    async def test_cancel_emits_event(self, event_bus: EventBus) -> None:
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        orch = make_orchestrator(event_bus)
        await orch.cancel()

        assert any(t == "swarm.cancelled" for t, _ in events)


# ---------------------------------------------------------------------------
# Tests: execute stops on cancel
# ---------------------------------------------------------------------------


class TestExecuteStopsOnCancel:
    async def test_execute_stops_on_cancel(self, event_bus: EventBus) -> None:
        """If cancelled is set before _execute, no tasks should run."""
        orch = make_orchestrator(event_bus)
        plan = await orch._plan("Build something")
        await orch._spawn(plan)

        await orch.cancel()
        await orch._execute()

        from backend.swarm.models import TaskStatus

        all_tasks = await orch.task_board.get_tasks()
        for t in all_tasks:
            assert t.status in (TaskStatus.PENDING, TaskStatus.BLOCKED), (
                f"Task {t.id} should not have run but has status {t.status}"
            )

    async def test_cancel_mid_execution(self, event_bus: EventBus) -> None:
        """Cancel during execution; verify it stops at next round boundary."""
        client = SlowMockCopilotClient(
            worker_delay=0.05,
            leader_plan=THREE_ROUND_PLAN,
            synthesis_report="Final report",
        )
        orch = SwarmOrchestrator(
            client=client,
            event_bus=event_bus,
            config={"max_rounds": 5, "timeout": 300},
        )
        plan = await orch._plan("Build something")
        await orch._spawn(plan)

        async def cancel_soon() -> None:
            await asyncio.sleep(0.08)
            await orch.cancel()

        await asyncio.gather(orch._execute(), cancel_soon())

        from backend.swarm.models import TaskStatus

        all_tasks = await orch.task_board.get_tasks()
        completed = [t for t in all_tasks if t.status == TaskStatus.COMPLETED]
        assert len(completed) < len(all_tasks), (
            "Not all tasks should have completed after mid-execution cancel"
        )


# ---------------------------------------------------------------------------
# Tests: run() error handling
# ---------------------------------------------------------------------------


class TestRunErrorHandling:
    async def test_run_emits_error_on_plan_failure(self, event_bus: EventBus) -> None:
        """run() emits swarm.error when leader fails to submit a plan."""
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        # Create a client where the leader session never calls the tool
        client = MockCopilotClient(leader_plan=VALID_PLAN)
        original_create = client.create_session

        async def _no_tool_session(**kwargs: Any) -> Any:
            tools = kwargs.get("tools", []) or []
            tool_names = {t.name for t in tools}
            if "create_plan" in tool_names:
                session = MockToolCallingSession(tool_call_args=None, tool_name="")
                session._tools = tools
                return session
            return await original_create(**kwargs)

        client.create_session = _no_tool_session  # type: ignore[assignment]
        orch = SwarmOrchestrator(client=client, event_bus=event_bus, config={"max_rounds": 3, "timeout": 0.1})

        with pytest.raises(ValueError, match="Leader did not submit a plan"):
            await orch.run("Build something")

        error_events = [(t, d) for t, d in events if t == "swarm.error"]
        assert len(error_events) == 1
        assert "plan" in error_events[0][1]["message"].lower()


# ---------------------------------------------------------------------------
# Tests: REST cancel endpoint
# ---------------------------------------------------------------------------


class TestCancelEndpoint:
    def test_cancel_endpoint_returns_cancelled(self) -> None:
        swarm_store.clear()
        client = TestClient(app)

        resp = client.post("/api/swarm/start", json={"goal": "Test cancel"})
        swarm_id = resp.json()["swarm_id"]

        resp = client.post(f"/api/swarm/{swarm_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_endpoint_unknown_swarm_returns_404(self) -> None:
        swarm_store.clear()
        client = TestClient(app)

        resp = client.post("/api/swarm/nonexistent/cancel")
        assert resp.status_code == 404
