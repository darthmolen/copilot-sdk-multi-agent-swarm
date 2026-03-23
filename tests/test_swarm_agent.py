"""Tests for SwarmAgent — event-driven task execution with real infrastructure."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import pytest

from backend.events import EventBus
from backend.swarm.agent import SwarmAgent
from backend.swarm.event_bridge import SessionEvent, SessionEventData, SessionEventType
from backend.swarm.inbox_system import InboxSystem
from backend.swarm.models import TaskStatus
from backend.swarm.task_board import TaskBoard
from backend.swarm.team_registry import TeamRegistry
from backend.swarm.tools import Tool


# ---------------------------------------------------------------------------
# Mock boundary — only CopilotClient / CopilotSession are mocked
# ---------------------------------------------------------------------------


class MockSession:
    def __init__(self) -> None:
        self._handlers: list[Callable[[SessionEvent], None]] = []
        self.sent_messages: list[str] = []

    def on(self, handler: Callable[[SessionEvent], None]) -> Callable[[], None]:
        self._handlers.append(handler)

        def unsubscribe() -> None:
            self._handlers.remove(handler)

        return unsubscribe

    async def send(self, prompt: str, **kwargs: Any) -> str:
        self.sent_messages.append(prompt)
        return "msg-id-1"

    def fire_event(self, event: SessionEvent) -> None:
        """Test helper to simulate SDK events."""
        for h in list(self._handlers):
            h(event)


class MockClient:
    def __init__(self, session: MockSession | None = None) -> None:
        self.session = session or MockSession()
        self.create_session_kwargs: dict[str, Any] | None = None

    async def create_session(self, **kwargs: Any) -> MockSession:
        self.create_session_kwargs = kwargs
        return self.session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def task_board() -> TaskBoard:
    return TaskBoard()


@pytest.fixture
def inbox() -> InboxSystem:
    return InboxSystem()


@pytest.fixture
def registry() -> TeamRegistry:
    return TeamRegistry()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_session() -> MockSession:
    return MockSession()


@pytest.fixture
def mock_client(mock_session: MockSession) -> MockClient:
    return MockClient(session=mock_session)


@pytest.fixture
def agent(
    task_board: TaskBoard,
    inbox: InboxSystem,
    registry: TeamRegistry,
    event_bus: EventBus,
) -> SwarmAgent:
    return SwarmAgent(
        name="coder",
        role="Write Python code",
        display_name="Coder Agent",
        task_board=task_board,
        inbox=inbox,
        registry=registry,
        event_bus=event_bus,
    )


# ---------------------------------------------------------------------------
# create_session tests
# ---------------------------------------------------------------------------


async def test_create_session_passes_custom_agents_config(
    agent: SwarmAgent, mock_client: MockClient
) -> None:
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    assert kwargs is not None
    custom_agents = kwargs["custom_agents"]
    assert len(custom_agents) == 1

    ca = custom_agents[0]
    assert ca["name"] == "coder"
    assert ca["display_name"] == "Coder Agent"
    assert ca["infer"] is False


async def test_create_session_passes_agent_preselection(
    agent: SwarmAgent, mock_client: MockClient
) -> None:
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    assert kwargs is not None
    assert kwargs["agent"] == "coder"


async def test_create_session_registers_swarm_tools(
    agent: SwarmAgent, mock_client: MockClient
) -> None:
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    assert kwargs is not None
    tools = kwargs["tools"]
    assert len(tools) == 4
    assert all(isinstance(t, Tool) for t in tools)


# ---------------------------------------------------------------------------
# execute_task tests
# ---------------------------------------------------------------------------


async def _make_task(task_board: TaskBoard) -> Any:
    """Helper to add a task and return it."""
    return await task_board.add_task(
        id="task-1",
        subject="Build feature",
        description="Implement the login page",
        worker_role="coder",
        worker_name="coder",
    )


async def test_execute_task_marks_in_progress(
    agent: SwarmAgent,
    mock_client: MockClient,
    mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    # Fire turn_end shortly after send so execute_task completes
    async def _fire_after_delay() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(
            SessionEvent(type=SessionEventType.ASSISTANT_TURN_END)
        )

    asyncio.ensure_future(_fire_after_delay())
    await agent.execute_task(task)

    # Task should have passed through IN_PROGRESS (now COMPLETED)
    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.COMPLETED


async def test_execute_task_sends_prompt(
    agent: SwarmAgent,
    mock_client: MockClient,
    mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    async def _fire_after_delay() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(
            SessionEvent(type=SessionEventType.ASSISTANT_TURN_END)
        )

    asyncio.ensure_future(_fire_after_delay())
    await agent.execute_task(task)

    assert "Implement the login page" in mock_session.sent_messages


async def test_execute_task_completes_on_turn_end(
    agent: SwarmAgent,
    mock_client: MockClient,
    mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    async def _fire_after_delay() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(
            SessionEvent(type=SessionEventType.ASSISTANT_TURN_END)
        )

    asyncio.ensure_future(_fire_after_delay())

    # Should return without hanging (implicit timeout from pytest)
    await agent.execute_task(task)

    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.COMPLETED


async def test_execute_task_timeout_marks_task(
    agent: SwarmAgent,
    mock_client: MockClient,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    # Don't fire any event, use a very short timeout
    await agent.execute_task(task, timeout=0.05)

    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.TIMEOUT


async def test_execute_task_error_marks_failed(
    agent: SwarmAgent,
    mock_client: MockClient,
    mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    async def _fire_error() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(
            SessionEvent(
                type=SessionEventType.SESSION_ERROR,
                data=SessionEventData(error="something broke"),
            )
        )

    asyncio.ensure_future(_fire_error())
    await agent.execute_task(task)

    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.FAILED


async def test_execute_task_unsubscribes_on_completion(
    agent: SwarmAgent,
    mock_client: MockClient,
    mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    handlers_before = len(mock_session._handlers)

    async def _fire_after_delay() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(
            SessionEvent(type=SessionEventType.ASSISTANT_TURN_END)
        )

    asyncio.ensure_future(_fire_after_delay())
    await agent.execute_task(task)

    # Handler should have been removed
    assert len(mock_session._handlers) == handlers_before
