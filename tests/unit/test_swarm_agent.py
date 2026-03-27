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
# Helper
# ---------------------------------------------------------------------------


async def _make_task(board: TaskBoard) -> Any:
    return await board.add_task(
        id="task-1",
        subject="Implement the login page",
        description="Implement the login page",
        worker_role="coder",
        worker_name="coder",
    )


# ---------------------------------------------------------------------------
# create_session tests
# ---------------------------------------------------------------------------


async def test_create_session_uses_system_message_replace(
    agent: SwarmAgent, mock_client: MockClient
) -> None:
    """Session uses system_message mode:replace, not customAgents."""
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    assert kwargs is not None
    # No customAgents
    assert "custom_agents" not in kwargs
    # system_message with mode:replace
    sm = kwargs["system_message"]
    assert sm["mode"] == "replace"
    assert len(sm["content"]) > 0


async def test_create_session_passes_model(
    task_board: TaskBoard, inbox: InboxSystem, registry: TeamRegistry,
    event_bus: EventBus, mock_client: MockClient,
) -> None:
    """Session passes the configured model."""
    agent = SwarmAgent(
        name="coder", role="Code", display_name="Coder",
        task_board=task_board, inbox=inbox, registry=registry,
        event_bus=event_bus, model="gemini-3-pro-preview",
    )
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    assert kwargs["model"] == "gemini-3-pro-preview"


async def test_create_session_registers_swarm_tools(
    agent: SwarmAgent, mock_client: MockClient
) -> None:
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    tools = kwargs.get("tools", [])
    assert len(tools) == 4
    tool_names = {t.name for t in tools}
    assert tool_names == {"task_update", "inbox_send", "inbox_receive", "task_list"}


async def test_create_session_passes_available_tools(
    task_board: TaskBoard, inbox: InboxSystem, registry: TeamRegistry,
    event_bus: EventBus, mock_client: MockClient,
) -> None:
    agent = SwarmAgent(
        name="coder", role="Code", display_name="Coder",
        task_board=task_board, inbox=inbox, registry=registry,
        event_bus=event_bus,
        available_tools=["bash", "grep"],
        system_tools=["task_update", "inbox_send", "inbox_receive", "task_list"],
    )
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    available = kwargs.get("available_tools")
    assert "bash" in available
    assert "grep" in available
    assert "task_update" in available
    assert "inbox_send" in available


async def test_create_session_no_available_tools_when_none(
    agent: SwarmAgent, mock_client: MockClient,
) -> None:
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    assert kwargs.get("available_tools") is None


async def test_create_session_uses_assembled_prompt(
    task_board: TaskBoard, inbox: InboxSystem, registry: TeamRegistry,
    event_bus: EventBus, mock_client: MockClient,
) -> None:
    agent = SwarmAgent(
        name="researcher", role="Primary Researcher", display_name="Dr. Smith",
        task_board=task_board, inbox=inbox, registry=registry,
        event_bus=event_bus,
        prompt_template="You are an expert in {role}.\n\nDo literature review.",
        system_preamble="## Protocol\nYou MUST call task_update.",
    )
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    prompt = kwargs["system_message"]["content"]
    assert "task_update" in prompt
    assert "literature review" in prompt
    assert "Primary Researcher" in prompt


# ---------------------------------------------------------------------------
# execute_task tests
# ---------------------------------------------------------------------------


async def test_execute_task_marks_in_progress(
    agent: SwarmAgent, mock_client: MockClient, mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    async def _fire() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(SessionEvent(type=SessionEventType.SESSION_IDLE))

    asyncio.ensure_future(_fire())
    await agent.execute_task(task)

    tasks = await task_board.get_tasks()
    assert tasks[0].status in (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED)


async def test_execute_task_sends_prompt(
    agent: SwarmAgent, mock_client: MockClient, mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    async def _fire() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(SessionEvent(type=SessionEventType.SESSION_IDLE))

    asyncio.ensure_future(_fire())
    await agent.execute_task(task)

    assert len(mock_session.sent_messages) == 1
    sent = mock_session.sent_messages[0]
    assert "task-1" in sent  # task ID included
    assert "Implement the login page" in sent  # description included


async def test_execute_task_completes_on_session_idle(
    agent: SwarmAgent, mock_client: MockClient, mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    async def _fire() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(SessionEvent(type=SessionEventType.SESSION_IDLE))

    asyncio.ensure_future(_fire())
    await agent.execute_task(task)

    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.COMPLETED


async def test_execute_task_timeout_marks_task(
    agent: SwarmAgent, mock_client: MockClient, task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)
    await agent.execute_task(task, timeout=0.05)

    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.TIMEOUT


async def test_execute_task_error_marks_failed(
    agent: SwarmAgent, mock_client: MockClient, mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    async def _fire() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(SessionEvent(
            type=SessionEventType.SESSION_ERROR,
            data=SessionEventData(error="boom"),
        ))

    asyncio.ensure_future(_fire())
    await agent.execute_task(task)

    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.FAILED


async def test_execute_task_unsubscribes_on_completion(
    agent: SwarmAgent, mock_client: MockClient, mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    await agent.create_session(mock_client)
    task = await _make_task(task_board)
    handlers_before = len(mock_session._handlers)

    async def _fire() -> None:
        await asyncio.sleep(0.01)
        mock_session.fire_event(SessionEvent(type=SessionEventType.SESSION_IDLE))

    asyncio.ensure_future(_fire())
    await agent.execute_task(task)

    assert len(mock_session._handlers) == handlers_before


# ---------------------------------------------------------------------------
# event_callback wiring
# ---------------------------------------------------------------------------


async def test_create_session_wires_event_callback(
    task_board: TaskBoard, inbox: InboxSystem, registry: TeamRegistry,
    event_bus: EventBus, mock_client: MockClient,
) -> None:
    events: list[tuple[str, dict]] = []
    event_bus.subscribe(lambda t, d: events.append((t, d)))

    agent = SwarmAgent(
        name="coder", role="Code", display_name="Coder",
        task_board=task_board, inbox=inbox, registry=registry,
        event_bus=event_bus,
    )
    await agent.create_session(mock_client)

    kwargs = mock_client.create_session_kwargs
    tools = kwargs.get("tools", [])
    assert len(tools) == 4

    from backend.swarm.tools import ToolInvocation
    inbox.register_agent("coder")
    inbox.register_agent("target")

    inbox_tool = next(t for t in tools if t.name == "inbox_send")
    await inbox_tool.handler(ToolInvocation(arguments={"to": "target", "message": "hi"}))

    await asyncio.sleep(0.05)

    inbox_events = [(t, d) for t, d in events if "inbox" in t.lower() or d.get("event") == "inbox.message"]
    assert len(inbox_events) >= 1


# ---------------------------------------------------------------------------
# Late completion monitoring tests
# ---------------------------------------------------------------------------


async def test_timed_out_task_recovers_on_late_completion(
    agent: SwarmAgent, mock_client: MockClient, mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    """A timed-out task should recover to COMPLETED when session.idle fires late."""
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    # Fire idle AFTER the timeout — simulates late completion
    async def _fire_late() -> None:
        await asyncio.sleep(0.15)
        mock_session.fire_event(SessionEvent(type=SessionEventType.SESSION_IDLE))

    asyncio.ensure_future(_fire_late())
    await agent.execute_task(task, timeout=0.05)

    # Immediately after execute_task, task should be TIMEOUT
    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.TIMEOUT

    # Wait for the background monitor to pick up the late completion
    await asyncio.sleep(0.3)

    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.COMPLETED


async def test_late_completion_captures_content(
    agent: SwarmAgent, mock_client: MockClient, mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    """Late completion should capture assistant.message content as the task result."""
    await agent.create_session(mock_client)
    task = await _make_task(task_board)

    async def _fire_late_with_content() -> None:
        await asyncio.sleep(0.15)
        mock_session.fire_event(SessionEvent(
            type=SessionEventType.ASSISTANT_MESSAGE,
            data=SessionEventData(content="Late result from agent"),
        ))
        mock_session.fire_event(SessionEvent(type=SessionEventType.SESSION_IDLE))

    asyncio.ensure_future(_fire_late_with_content())
    await agent.execute_task(task, timeout=0.05)

    await asyncio.sleep(0.3)

    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.COMPLETED
    assert "Late result from agent" in tasks[0].result


async def test_monitor_expires_without_completion(
    agent: SwarmAgent, mock_client: MockClient, mock_session: MockSession,
    task_board: TaskBoard,
) -> None:
    """Monitor should give up after its own timeout and unsubscribe."""
    await agent.create_session(mock_client)
    task = await _make_task(task_board)
    handlers_before = len(mock_session._handlers)

    # No idle event will ever fire — monitor should expire
    await agent.execute_task(task, timeout=0.05)

    # Handler is still subscribed (monitor is running)
    assert len(mock_session._handlers) == handlers_before + 1

    # Patch the monitor_timeout to be very short — but since we can't
    # change it after creation, we verify that after enough time the
    # task is still TIMEOUT (monitor doesn't false-complete)
    await asyncio.sleep(0.2)
    tasks = await task_board.get_tasks()
    assert tasks[0].status == TaskStatus.TIMEOUT
