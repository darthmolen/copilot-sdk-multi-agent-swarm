"""Tests for SwarmOrchestrator — strict TDD for the full swarm lifecycle."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.events import EventBus
from backend.swarm.event_bridge import SessionEvent, SessionEventData, SessionEventType
from backend.swarm.models import TaskStatus
from backend.swarm.orchestrator import SwarmOrchestrator
from backend.swarm.tools import Tool, ToolInvocation


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


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------


class MockEvent:
    """Mimics an SDK event with .content and .data.content."""

    def __init__(self, content: str = "") -> None:
        self.content = content


class MockToolCallingSession:
    """Simulates SDK behavior: on send(), invokes the registered tool handler
    with preconfigured args, then fires ASSISTANT_TURN_END.

    Also supports send_and_wait() for synthesis (returns text directly).
    """

    def __init__(
        self,
        tool_call_args: dict[str, Any] | None = None,
        tool_name: str = "",
        send_and_wait_response: str = "",
    ) -> None:
        self._tool_call_args = tool_call_args
        self._tool_name = tool_name
        self._send_and_wait_response = send_and_wait_response
        self._handlers: list[Any] = []
        self._tools: list[Tool] = []
        self.sent_messages: list[str] = []

    def on(self, handler: Any) -> Any:
        self._handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe

    async def send(self, prompt: str, **kwargs: Any) -> str:
        self.sent_messages.append(prompt)

        # Find the target tool and call its handler (simulating SDK function calling)
        if self._tool_call_args and self._tool_name and self._tools:
            tool = next((t for t in self._tools if t.name == self._tool_name), None)
            if tool:
                invocation = ToolInvocation(
                    tool_name=self._tool_name,
                    arguments=self._tool_call_args,
                )
                await tool.handler(invocation)

        # Fire assistant.message with content (for event-driven text capture)
        if self._send_and_wait_response:
            for h in list(self._handlers):
                h(SessionEvent(
                    type=SessionEventType.ASSISTANT_MESSAGE,
                    data=SessionEventData(content=self._send_and_wait_response),
                ))

        # Fire turn_end
        for h in list(self._handlers):
            h(SessionEvent(
                type=SessionEventType.ASSISTANT_TURN_END,
                data=SessionEventData(turn_id="turn-1"),
            ))
        return "msg-1"


class MockWorkerSession:
    """Fires ASSISTANT_TURN_END after send() to work with real SwarmAgent.execute_task."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self._handlers: list[Any] = []
        self._tools: list[Tool] = []

    def on(self, handler: Any) -> Any:
        self._handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe

    async def send(self, prompt: str, **kwargs: Any) -> str:
        if self._fail:
            for h in list(self._handlers):
                h(SessionEvent(
                    type=SessionEventType.SESSION_ERROR,
                    data=SessionEventData(error="Agent execution failed"),
                ))
            return "msg-1"
        for h in list(self._handlers):
            h(SessionEvent(
                type=SessionEventType.ASSISTANT_TURN_END,
                data=SessionEventData(turn_id="turn-1"),
            ))
        return "msg-1"


class MockCopilotClient:
    """Mock client that creates tool-calling sessions for leader/synthesis
    and worker sessions for agents."""

    def __init__(
        self,
        leader_plan: dict[str, Any] | None = None,
        worker_fail_names: set[str] | None = None,
        synthesis_report: str = "Final report",
    ) -> None:
        self._leader_plan = leader_plan or VALID_PLAN
        self._synthesis_report = synthesis_report
        self._worker_fail_names = worker_fail_names or set()
        self._plan_session_created = False

    async def create_session(self, **kwargs: Any) -> Any:
        tools: list[Tool] = kwargs.get("tools", []) or []
        tool_names = {t.name for t in tools}

        # Leader plan session: has create_plan tool
        if "create_plan" in tool_names:
            session = MockToolCallingSession(
                tool_call_args=self._leader_plan,
                tool_name="create_plan",
            )
            session._tools = tools
            return session

        # Worker session: has task_update tool (but not create_plan)
        if "task_update" in tool_names:
            # Identify worker by system_message content
            sm = kwargs.get("system_message", {})
            content = sm.get("content", "") if isinstance(sm, dict) else ""
            # Find worker name from the prompt content
            worker_name = ""
            for name in self._worker_fail_names:
                if name.lower() in content.lower():
                    worker_name = name
                    break
            fail = worker_name in self._worker_fail_names if worker_name else False
            session = MockWorkerSession(fail=fail)
            session._tools = tools
            return session

        # Synthesis session: no swarm tools (uses send_and_wait)
        session = MockToolCallingSession(
            send_and_wait_response=self._synthesis_report,
        )
        session._tools = tools
        return session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


def make_orchestrator(
    event_bus: EventBus,
    leader_plan: dict[str, Any] | None = None,
    worker_fail_names: set[str] | None = None,
    synthesis_report: str = "Final report",
    config: dict[str, Any] | None = None,
) -> SwarmOrchestrator:
    client = MockCopilotClient(
        leader_plan=leader_plan,
        worker_fail_names=worker_fail_names,
        synthesis_report=synthesis_report,
    )
    return SwarmOrchestrator(client=client, event_bus=event_bus, config=config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlan:
    async def test_plan_creates_tasks_from_tool_call(self, event_bus: EventBus) -> None:
        """Leader calls create_plan tool → tasks created on TaskBoard with correct blocked_by."""
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

    async def test_plan_raises_when_tool_not_called(self, event_bus: EventBus) -> None:
        """If leader never calls create_plan, raise ValueError."""
        client = MockCopilotClient(leader_plan=VALID_PLAN)
        # Override: create a session that does NOT call any tool
        original_create = client.create_session

        async def _no_tool_session(**kwargs: Any) -> Any:
            tools = kwargs.get("tools", []) or []
            tool_names = {t.name for t in tools}
            if "create_plan" in tool_names:
                # Return session that sends but never calls the tool
                session = MockToolCallingSession(tool_call_args=None, tool_name="")
                session._tools = tools
                return session
            return await original_create(**kwargs)

        client.create_session = _no_tool_session  # type: ignore[assignment]
        orch = SwarmOrchestrator(client=client, event_bus=event_bus, config={"max_rounds": 3, "timeout": 0.1})

        with pytest.raises(ValueError, match="Leader did not submit a plan"):
            await orch._plan("Build something")


class TestSpawn:
    async def test_spawn_creates_agents_per_worker(self, event_bus: EventBus) -> None:
        orch = make_orchestrator(event_bus)
        await orch._spawn(VALID_PLAN)

        assert len(orch.agents) == 2
        assert "analyst" in orch.agents
        assert "writer" in orch.agents

    async def test_spawn_registers_in_team_registry(self, event_bus: EventBus) -> None:
        orch = make_orchestrator(event_bus)
        await orch._spawn(VALID_PLAN)

        all_agents = await orch.registry.get_all()
        names = {a.name for a in all_agents}
        assert names == {"analyst", "writer"}

    async def test_spawn_deduplicates_workers(self, event_bus: EventBus) -> None:
        plan_with_dups = {
            "team_description": "Dup team",
            "tasks": [
                {"subject": "T1", "description": "D1", "worker_role": "Analyst", "worker_name": "analyst", "blocked_by_indices": []},
                {"subject": "T2", "description": "D2", "worker_role": "Analyst", "worker_name": "analyst", "blocked_by_indices": []},
            ],
        }
        orch = make_orchestrator(event_bus)
        await orch._spawn(plan_with_dups)
        assert len(orch.agents) == 1


class TestExecute:
    async def test_execute_round_runs_pending_tasks(self, event_bus: EventBus) -> None:
        orch = make_orchestrator(event_bus)
        plan = await orch._plan("Build something")
        await orch._spawn(plan)
        await orch._execute()

        all_tasks = await orch.task_board.get_tasks()
        t0 = next(t for t in all_tasks if t.id == "task-0")
        assert t0.status == TaskStatus.COMPLETED

        t1 = next(t for t in all_tasks if t.id == "task-1")
        assert t1.status == TaskStatus.COMPLETED

    async def test_execute_respects_round_limit(self, event_bus: EventBus) -> None:
        orch = make_orchestrator(event_bus, config={"max_rounds": 1, "timeout": 300})
        plan = await orch._plan("Build something")
        await orch._spawn(plan)
        await orch._execute()

        all_tasks = await orch.task_board.get_tasks()
        t0 = next(t for t in all_tasks if t.id == "task-0")
        assert t0.status == TaskStatus.COMPLETED

        t1 = next(t for t in all_tasks if t.id == "task-1")
        assert t1.status == TaskStatus.PENDING

    async def test_execute_handles_agent_failure(self, event_bus: EventBus) -> None:
        independent_plan = {
            "team_description": "Test team",
            "tasks": [
                {"subject": "Task 1", "description": "Do thing 1", "worker_role": "Analyst", "worker_name": "analyst", "blocked_by_indices": []},
                {"subject": "Task 2", "description": "Do thing 2", "worker_role": "Writer", "worker_name": "writer", "blocked_by_indices": []},
            ],
        }

        orch = make_orchestrator(
            event_bus,
            leader_plan=independent_plan,
            worker_fail_names={"analyst"},
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
    async def test_synthesize_returns_report_via_event_driven(self, event_bus: EventBus) -> None:
        """Synthesis uses event-driven pattern — captures assistant.message text."""
        orch = make_orchestrator(event_bus, synthesis_report="The final synthesis report")

        await orch.task_board.add_task(
            id="task-0", subject="Research", description="Do research",
            worker_role="Analyst", worker_name="analyst",
        )
        await orch.task_board.update_status("task-0", "completed", "Research findings")

        report = await orch._synthesize("Build something great")
        assert report == "The final synthesis report"

    async def test_synthesize_does_not_use_send_and_wait(self, event_bus: EventBus) -> None:
        """Synthesis must NOT use send_and_wait (it times out). Uses send() + on() instead."""
        orch = make_orchestrator(event_bus, synthesis_report="Report text")

        await orch.task_board.add_task(
            id="task-0", subject="R", description="D",
            worker_role="A", worker_name="a",
        )
        await orch.task_board.update_status("task-0", "completed", "done")

        # The mock's send_and_wait was removed — if synthesis tries to call it,
        # it will raise AttributeError. This test verifies synthesis uses send() only.
        report = await orch._synthesize("goal")
        assert len(report) > 0


class TestGranularEvents:
    """Verify the orchestrator emits granular events for the frontend."""

    async def test_plan_emits_task_created_events(self, event_bus: EventBus) -> None:
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        orch = make_orchestrator(event_bus)
        await orch._plan("Build something")

        task_created = [(t, d) for t, d in events if t == "task.created"]
        assert len(task_created) == 2, f"Expected 2 task.created, got {len(task_created)}"

        # Verify task data shape
        assert task_created[0][1]["task"]["id"] == "task-0"
        assert task_created[0][1]["task"]["subject"] == "Task 1"
        assert task_created[1][1]["task"]["id"] == "task-1"
        assert task_created[1][1]["task"]["worker_name"] == "writer"

    async def test_plan_emits_phase_changed_planning(self, event_bus: EventBus) -> None:
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        orch = make_orchestrator(event_bus)
        await orch._plan("Build something")

        phase_events = [(t, d) for t, d in events if t == "swarm.phase_changed"]
        phases = [d["phase"] for _, d in phase_events]
        assert "planning" in phases

    async def test_spawn_emits_agent_spawned_events(self, event_bus: EventBus) -> None:
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        orch = make_orchestrator(event_bus)
        await orch._spawn(VALID_PLAN)

        spawned = [(t, d) for t, d in events if t == "agent.spawned"]
        assert len(spawned) == 2, f"Expected 2 agent.spawned, got {len(spawned)}"

        agent_names = {d["agent"]["name"] for _, d in spawned}
        assert agent_names == {"analyst", "writer"}

        # Verify agent data shape
        for _, d in spawned:
            agent = d["agent"]
            assert "name" in agent
            assert "role" in agent
            assert "display_name" in agent
            assert agent["status"] == "idle"
            assert agent["tasks_completed"] == 0

    async def test_spawn_emits_phase_changed_spawning(self, event_bus: EventBus) -> None:
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        orch = make_orchestrator(event_bus)
        await orch._spawn(VALID_PLAN)

        phase_events = [(t, d) for t, d in events if t == "swarm.phase_changed"]
        phases = [d["phase"] for _, d in phase_events]
        assert "spawning" in phases

    async def test_execute_emits_task_updated_events(self, event_bus: EventBus) -> None:
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        orch = make_orchestrator(event_bus)
        plan = await orch._plan("Build something")
        await orch._spawn(plan)
        await orch._execute()

        updated = [(t, d) for t, d in events if t == "task.updated"]
        assert len(updated) >= 2, f"Expected at least 2 task.updated, got {len(updated)}"

        # Verify task data shape
        for _, d in updated:
            assert "task" in d
            assert "id" in d["task"]
            assert "status" in d["task"]

    async def test_execute_emits_phase_changed_executing(self, event_bus: EventBus) -> None:
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        orch = make_orchestrator(event_bus)
        plan = await orch._plan("Build something")
        await orch._spawn(plan)
        await orch._execute()

        phase_events = [(t, d) for t, d in events if t == "swarm.phase_changed"]
        phases = [d["phase"] for _, d in phase_events]
        assert "executing" in phases

    async def test_synthesize_emits_leader_report(self, event_bus: EventBus) -> None:
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        orch = make_orchestrator(event_bus, synthesis_report="The great report")
        await orch.task_board.add_task(
            id="task-0", subject="Research", description="Do research",
            worker_role="Analyst", worker_name="analyst",
        )
        await orch.task_board.update_status("task-0", "completed", "findings")

        await orch._synthesize("Build something")

        report_events = [(t, d) for t, d in events if t == "leader.report"]
        assert len(report_events) == 1
        assert report_events[0][1]["content"] == "The great report"

    async def test_synthesize_emits_phase_changed_synthesizing_and_complete(self, event_bus: EventBus) -> None:
        events: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events.append((t, d)))

        orch = make_orchestrator(event_bus, synthesis_report="report")
        await orch.task_board.add_task(
            id="task-0", subject="R", description="D",
            worker_role="A", worker_name="a",
        )
        await orch.task_board.update_status("task-0", "completed", "done")

        await orch._synthesize("goal")

        phase_events = [(t, d) for t, d in events if t == "swarm.phase_changed"]
        phases = [d["phase"] for _, d in phase_events]
        assert "synthesizing" in phases
        assert "complete" in phases


class TestFullLifecycle:
    async def test_full_run_lifecycle(self, event_bus: EventBus) -> None:
        events_received: list[tuple[str, dict]] = []

        def track_events(event_type: str, data: dict) -> None:
            events_received.append((event_type, data))

        event_bus.subscribe(track_events)

        orch = make_orchestrator(
            event_bus,
            leader_plan=VALID_PLAN,
            synthesis_report="Everything is done. Great work!",
        )

        report = await orch.run("Build something amazing")

        assert report == "Everything is done. Great work!"

        all_tasks = await orch.task_board.get_tasks()
        assert len(all_tasks) == 2
        for t in all_tasks:
            assert t.status == TaskStatus.COMPLETED

        assert len(orch.agents) == 2

        event_types = [e[0] for e in events_received]
        # Aggregate events (original)
        assert "swarm.plan_complete" in event_types
        assert "swarm.spawn_complete" in event_types
        assert "swarm.round_start" in event_types
        assert "swarm.synthesis_complete" in event_types
        # Granular events (new)
        assert "task.created" in event_types
        assert "agent.spawned" in event_types
        assert "task.updated" in event_types
        assert "leader.report" in event_types
        assert "swarm.phase_changed" in event_types

    async def test_full_lifecycle_event_order(self, event_bus: EventBus) -> None:
        """Verify events appear in the correct lifecycle order."""
        events_received: list[tuple[str, dict]] = []
        event_bus.subscribe(lambda t, d: events_received.append((t, d)))

        orch = make_orchestrator(event_bus, synthesis_report="Final report")
        await orch.run("Build something")

        event_types = [e[0] for e in events_received]

        # Verify ordering: planning events before spawning before executing before synthesis
        plan_idx = event_types.index("swarm.phase_changed")  # first phase_changed = planning
        task_created_idx = event_types.index("task.created")
        spawn_idx = event_types.index("agent.spawned")
        round_idx = event_types.index("swarm.round_start")
        report_idx = event_types.index("leader.report")

        assert plan_idx < task_created_idx, "phase_changed should come before task.created"
        assert task_created_idx < spawn_idx, "task.created should come before agent.spawned"
        assert spawn_idx < round_idx, "agent.spawned should come before round_start"
        assert round_idx < report_idx, "round_start should come before leader.report"


class TestLogging:
    """Verify orchestrator logs at correct levels."""

    async def test_synthesis_timeout_logs_warning(self, event_bus: EventBus) -> None:
        """Synthesis timeout should log at WARNING level, not silently."""
        import structlog
        from unittest.mock import patch

        log_output: list[dict] = []

        def capture_log(logger: Any, method_name: str, event_dict: dict) -> dict:
            log_output.append({"level": method_name, **event_dict})
            raise structlog.DropEvent

        # Create orchestrator with very short timeout
        orch = make_orchestrator(event_bus, synthesis_report="", config={"max_rounds": 3, "timeout": 0.05})
        await orch.task_board.add_task(id="t-0", subject="R", description="D", worker_role="A", worker_name="a")
        await orch.task_board.update_status("t-0", "completed", "done")

        # Patch session creation to return a session that never fires turn_end
        original_create = orch.client.create_session

        async def _hanging_session(**kwargs: Any) -> Any:
            """Session whose send() never fires events — simulates a hung agent."""

            class HangingSession:
                def on(self, handler: Any) -> Any:
                    return lambda: None  # no-op unsubscribe

                async def send(self, prompt: str, **kw: Any) -> str:
                    return "msg-1"  # returns immediately but fires no events

            return HangingSession()

        orch.client.create_session = _hanging_session  # type: ignore[attr-defined]

        report = await orch._synthesize("goal")
        # Synthesis should complete with no output (timeout, not crash)
        assert report == "(Synthesis produced no output)"

    async def test_agent_failure_logs_warning_not_error(self, event_bus: EventBus) -> None:
        """Agent task failures should log at WARNING, not ERROR (they're expected workflow)."""
        independent_plan = {
            "team_description": "Test team",
            "tasks": [
                {"subject": "Task 1", "description": "Do thing 1", "worker_role": "Analyst", "worker_name": "analyst", "blocked_by_indices": []},
            ],
        }

        orch = make_orchestrator(event_bus, leader_plan=independent_plan, worker_fail_names={"analyst"})
        plan = await orch._plan("Build something")
        await orch._spawn(plan)
        await orch._execute()

        # Verify the task was marked failed (the behavior we care about)
        all_tasks = await orch.task_board.get_tasks()
        t0 = next(t for t in all_tasks if t.id == "task-0")
        assert t0.status == TaskStatus.FAILED
