"""TDD tests for swarm tools factory — uses real TaskBoard and InboxSystem."""

from __future__ import annotations

import json

import pytest

from backend.swarm.inbox_system import InboxSystem
from backend.swarm.models import Task, TaskStatus
from backend.swarm.task_board import TaskBoard
from backend.swarm.tools import Tool, ToolInvocation, create_swarm_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_TOOL_NAMES = {"task_update", "inbox_send", "inbox_receive", "task_list"}


def _find_tool(tools: list[Tool], name: str) -> Tool:
    return next(t for t in tools if t.name == name)


async def _seed_task(
    board: TaskBoard,
    task_id: str = "t1",
    subject: str = "do something",
    description: str = "details",
    worker_role: str = "coder",
    worker_name: str = "alice",
) -> Task:
    return await board.add_task(
        id=task_id,
        subject=subject,
        description=description,
        worker_role=worker_role,
        worker_name=worker_name,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_swarm_tools_returns_4_tools():
    """Factory returns exactly 4 tools with correct names and skip_permission."""
    board = TaskBoard()
    inbox = InboxSystem()
    tools = create_swarm_tools("worker_1", board, inbox)

    assert len(tools) == 4
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOL_NAMES

    for tool in tools:
        assert tool.skip_permission is True


@pytest.mark.asyncio
async def test_task_update_mutates_real_taskboard():
    """task_update tool actually changes the task status on the real board."""
    board = TaskBoard()
    inbox = InboxSystem()
    await _seed_task(board, "t1")

    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_update")

    invocation = ToolInvocation(
        arguments={"task_id": "t1", "status": "completed", "result": "done"}
    )
    result = await tool.handler(invocation)

    assert result.result_type == "success"
    data = json.loads(result.text_result_for_llm)
    assert data["ok"] is True
    assert data["task_id"] == "t1"

    # Verify the real board was mutated
    tasks = await board.get_tasks()
    assert tasks[0].status is TaskStatus.COMPLETED
    assert tasks[0].result == "done"


@pytest.mark.asyncio
async def test_inbox_send_delivers_to_real_inbox():
    """inbox_send tool delivers a message through the real InboxSystem."""
    board = TaskBoard()
    inbox = InboxSystem()
    inbox.register_agent("worker_1")
    inbox.register_agent("worker_2")

    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "inbox_send")

    invocation = ToolInvocation(
        arguments={"to": "worker_2", "message": "hello there"}
    )
    result = await tool.handler(invocation)

    assert result.result_type == "success"
    data = json.loads(result.text_result_for_llm)
    assert data["ok"] is True
    assert data["sent_to"] == "worker_2"

    # Verify message actually landed in the real inbox
    messages = await inbox.receive("worker_2")
    assert len(messages) == 1
    assert messages[0].content == "hello there"
    assert messages[0].sender == "worker_1"


@pytest.mark.asyncio
async def test_inbox_receive_returns_messages():
    """inbox_receive tool returns all queued messages as JSON."""
    board = TaskBoard()
    inbox = InboxSystem()
    inbox.register_agent("worker_1")

    # Pre-load two messages
    await inbox.send("boss", "worker_1", "do task A")
    await inbox.send("peer", "worker_1", "need help?")

    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "inbox_receive")

    invocation = ToolInvocation()
    result = await tool.handler(invocation)

    assert result.result_type == "success"
    data = json.loads(result.text_result_for_llm)
    assert len(data["messages"]) == 2
    assert data["messages"][0]["sender"] == "boss"
    assert data["messages"][0]["content"] == "do task A"
    assert data["messages"][1]["sender"] == "peer"
    assert "timestamp" in data["messages"][0]


@pytest.mark.asyncio
async def test_task_list_returns_correct_json():
    """task_list tool returns all tasks serialized as JSON."""
    board = TaskBoard()
    inbox = InboxSystem()
    await _seed_task(board, "t1", worker_name="alice")
    await _seed_task(board, "t2", worker_name="bob")
    await board.update_status("t1", "completed", "result-1")

    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_list")

    invocation = ToolInvocation(arguments={})
    result = await tool.handler(invocation)

    assert result.result_type == "success"
    data = json.loads(result.text_result_for_llm)
    assert len(data["tasks"]) == 2

    ids = {t["id"] for t in data["tasks"]}
    assert ids == {"t1", "t2"}

    completed = next(t for t in data["tasks"] if t["id"] == "t1")
    assert completed["status"] == "completed"
    assert completed["result"] == "result-1"


@pytest.mark.asyncio
async def test_task_list_filters_by_owner():
    """task_list tool filters tasks by owner when parameter is provided."""
    board = TaskBoard()
    inbox = InboxSystem()
    await _seed_task(board, "t1", worker_name="alice")
    await _seed_task(board, "t2", worker_name="bob")
    await _seed_task(board, "t3", worker_name="alice")

    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_list")

    invocation = ToolInvocation(arguments={"owner": "alice"})
    result = await tool.handler(invocation)

    data = json.loads(result.text_result_for_llm)
    assert len(data["tasks"]) == 2
    assert all(t["worker_name"] == "alice" for t in data["tasks"])


@pytest.mark.asyncio
async def test_event_callback_called_on_task_update():
    """event_callback is invoked with event data when task_update runs."""
    board = TaskBoard()
    inbox = InboxSystem()
    await _seed_task(board, "t1")

    events: list[dict] = []

    tools = create_swarm_tools("worker_1", board, inbox, event_callback=events.append)
    tool = _find_tool(tools, "task_update")

    invocation = ToolInvocation(
        arguments={"task_id": "t1", "status": "in_progress"}
    )
    await tool.handler(invocation)

    assert len(events) == 1
    assert events[0]["event"] == "task_update"
    assert events[0]["agent"] == "worker_1"
    assert events[0]["task_id"] == "t1"
    assert events[0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_sender_stamped_from_closure():
    """inbox_send always stamps the sender from the closure, not from arguments."""
    board = TaskBoard()
    inbox = InboxSystem()
    inbox.register_agent("worker_1")
    inbox.register_agent("victim")

    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "inbox_send")

    # The LLM cannot override the sender — it is closure-bound to "worker_1"
    invocation = ToolInvocation(
        arguments={"to": "victim", "message": "spoofed"}
    )
    await tool.handler(invocation)

    messages = await inbox.receive("victim")
    assert len(messages) == 1
    assert messages[0].sender == "worker_1"  # always from closure, never spoofable
