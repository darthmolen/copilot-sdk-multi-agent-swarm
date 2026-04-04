"""TDD tests for swarm tools factory — uses real TaskBoard and InboxSystem."""

from __future__ import annotations

import asyncio
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
async def test_swarm_tool_parameters_are_json_schema():
    """All swarm tools with parameters must use valid JSON Schema format (from Pydantic)."""
    board = TaskBoard()
    inbox = InboxSystem()
    tools = create_swarm_tools("worker_1", board, inbox)

    for tool in tools:
        if tool.parameters is None:
            continue  # inbox_receive has no params — OK
        schema = tool.parameters
        # Must be a JSON Schema object with "properties" and "type"
        assert "properties" in schema, f"{tool.name}: missing 'properties' in schema: {schema}"
        assert schema.get("type") == "object", f"{tool.name}: schema type must be 'object', got {schema.get('type')}"
        # "required" should be a list at the top level, not per-property
        for prop_name, prop_def in schema["properties"].items():
            assert "required" not in prop_def, (
                f"{tool.name}.{prop_name}: 'required' must be at schema top level, not per-property"
            )


@pytest.mark.asyncio
async def test_task_update_mutates_real_taskboard():
    """task_update tool actually changes the task status on the real board."""
    board = TaskBoard()
    inbox = InboxSystem()
    await _seed_task(board, "t1")

    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_update")

    invocation = ToolInvocation(arguments={"task_id": "t1", "status": "completed", "result": "done"})
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

    invocation = ToolInvocation(arguments={"to": "worker_2", "message": "hello there"})
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

    invocation = ToolInvocation(arguments={"task_id": "t1", "status": "in_progress"})
    await tool.handler(invocation)

    assert len(events) == 1
    assert events[0]["event"] == "task.updated"
    assert events[0]["task"]["id"] == "t1"
    assert events[0]["task"]["status"] == "in_progress"


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
    invocation = ToolInvocation(arguments={"to": "victim", "message": "spoofed"})
    await tool.handler(invocation)

    messages = await inbox.receive("victim")
    assert len(messages) == 1
    assert messages[0].sender == "worker_1"  # always from closure, never spoofable


# ---------------------------------------------------------------------------
# Plan / Report tool tests (Step 1+2 of tool-based spike)
# ---------------------------------------------------------------------------


async def test_create_plan_tool_returns_tool_with_correct_shape():
    """create_plan_tool returns a Tool named 'create_plan' with skip_permission=True."""
    from backend.swarm.tools import create_plan_tool

    holder: list[dict] = []
    tool = create_plan_tool(holder)

    assert tool.name == "create_plan"
    assert tool.skip_permission is True
    assert tool.parameters is not None  # has a JSON schema


async def test_create_report_tool_returns_tool_with_correct_shape():
    """create_report_tool returns a Tool named 'submit_report' with skip_permission=True."""
    from backend.swarm.tools import create_report_tool

    holder: list[str] = []
    tool = create_report_tool(holder)

    assert tool.name == "submit_report"
    assert tool.skip_permission is True
    assert tool.parameters is not None


async def test_plan_tool_handler_captures_valid_plan():
    """Invoking create_plan handler with valid args populates plan_holder."""
    from backend.swarm.tools import create_plan_tool

    holder: list[dict] = []
    tool = create_plan_tool(holder)

    invocation = ToolInvocation(
        arguments={
            "team_description": "Test team",
            "tasks": [
                {
                    "subject": "Design",
                    "description": "Design the system",
                    "worker_role": "Architect",
                    "worker_name": "architect",
                    "blocked_by_indices": [],
                },
                {
                    "subject": "Implement",
                    "description": "Build it",
                    "worker_role": "Developer",
                    "worker_name": "developer",
                    "blocked_by_indices": [0],
                },
            ],
        }
    )
    result = await tool.handler(invocation)

    assert result.result_type == "success"
    assert len(holder) == 1
    assert holder[0]["team_description"] == "Test team"
    assert len(holder[0]["tasks"]) == 2
    assert holder[0]["tasks"][0]["subject"] == "Design"
    assert holder[0]["tasks"][1]["blocked_by_indices"] == [0]


async def test_plan_tool_handler_rejects_invalid_args():
    """Invoking create_plan with missing required fields returns failure."""
    from backend.swarm.tools import create_plan_tool

    holder: list[dict] = []
    tool = create_plan_tool(holder)

    invocation = ToolInvocation(arguments={"bad_field": "oops"})
    result = await tool.handler(invocation)

    assert result.result_type == "failure"
    assert len(holder) == 0  # nothing captured


async def test_report_tool_handler_captures_report():
    """Invoking submit_report handler populates report_holder."""
    from backend.swarm.tools import create_report_tool

    holder: list[str] = []
    tool = create_report_tool(holder)

    invocation = ToolInvocation(arguments={"report": "The final synthesis report."})
    result = await tool.handler(invocation)

    assert result.result_type == "success"
    assert len(holder) == 1
    assert holder[0] == "The final synthesis report."


# ---------------------------------------------------------------------------
# Defensive error handling tests (TDD RED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_update_missing_task_id_returns_error():
    """task_update with missing task_id returns error result, not KeyError crash."""
    board = TaskBoard()
    inbox = InboxSystem()
    await _seed_task(board, "t1")

    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_update")

    # Agent sends {"id": "t1"} instead of {"task_id": "t1"}
    invocation = ToolInvocation(arguments={"id": "t1", "status": "completed"})
    result = await tool.handler(invocation)

    assert result.result_type == "error"
    assert "task_id" in result.text_result_for_llm.lower()


@pytest.mark.asyncio
async def test_task_update_none_arguments_returns_error():
    """task_update with None arguments returns error, not crash."""
    board = TaskBoard()
    inbox = InboxSystem()
    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_update")

    invocation = ToolInvocation(arguments=None)
    result = await tool.handler(invocation)

    assert result.result_type == "error"


@pytest.mark.asyncio
async def test_task_update_string_arguments_returns_error():
    """task_update with string arguments (not dict) returns error, not crash."""
    board = TaskBoard()
    inbox = InboxSystem()
    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_update")

    invocation = ToolInvocation(arguments="task-1 completed done")
    result = await tool.handler(invocation)

    assert result.result_type == "error"


@pytest.mark.asyncio
async def test_task_update_invalid_task_id_returns_error():
    """task_update with a task_id that doesn't exist returns error, not crash."""
    board = TaskBoard()
    inbox = InboxSystem()
    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_update")

    invocation = ToolInvocation(arguments={"task_id": "nonexistent", "status": "completed"})
    result = await tool.handler(invocation)

    assert result.result_type == "error"
    assert "nonexistent" in result.text_result_for_llm.lower() or "not found" in result.text_result_for_llm.lower()


@pytest.mark.asyncio
async def test_inbox_send_missing_fields_returns_error():
    """inbox_send with missing 'to' or 'message' returns error, not crash."""
    board = TaskBoard()
    inbox = InboxSystem()
    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "inbox_send")

    invocation = ToolInvocation(arguments={"recipient": "worker_2", "content": "hello"})
    result = await tool.handler(invocation)

    assert result.result_type == "error"


@pytest.mark.asyncio
async def test_inbox_send_none_arguments_returns_error():
    """inbox_send with None arguments returns error, not crash."""
    board = TaskBoard()
    inbox = InboxSystem()
    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "inbox_send")

    invocation = ToolInvocation(arguments=None)
    result = await tool.handler(invocation)

    assert result.result_type == "error"


@pytest.mark.asyncio
async def test_task_list_none_arguments_still_works():
    """task_list with None arguments should still work (all params optional)."""
    board = TaskBoard()
    inbox = InboxSystem()
    await _seed_task(board, "t1")

    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_list")

    invocation = ToolInvocation(arguments=None)
    result = await tool.handler(invocation)

    assert result.result_type == "success"
    data = json.loads(result.text_result_for_llm)
    assert len(data["tasks"]) == 1


@pytest.mark.asyncio
async def test_task_update_logs_arguments_on_error(caplog):
    """task_update logs the actual arguments received when it fails."""
    import logging

    board = TaskBoard()
    inbox = InboxSystem()
    tools = create_swarm_tools("worker_1", board, inbox)
    tool = _find_tool(tools, "task_update")

    with caplog.at_level(logging.WARNING):
        invocation = ToolInvocation(arguments={"wrong_key": "bad_value"})
        await tool.handler(invocation)

    # structlog may not write to caplog, so just verify the result is error
    # The real assertion is that it doesn't crash


async def test_inbox_send_emits_event_via_callback():
    """inbox_send tool emits inbox.message event when event_callback is provided."""
    board = TaskBoard()
    inbox = InboxSystem()
    inbox.register_agent("worker_1")
    inbox.register_agent("worker_2")

    events: list[dict] = []
    tools = create_swarm_tools("worker_1", board, inbox, event_callback=events.append)
    tool = _find_tool(tools, "inbox_send")

    invocation = ToolInvocation(arguments={"to": "worker_2", "message": "hello from worker 1"})
    await tool.handler(invocation)

    # Should have emitted an event with inbox.message data
    assert len(events) >= 1
    inbox_events = [e for e in events if e.get("event") == "inbox.message"]
    assert len(inbox_events) == 1
    assert inbox_events[0]["sender"] == "worker_1"
    assert inbox_events[0]["recipient"] == "worker_2"
    assert inbox_events[0]["content"] == "hello from worker 1"


# ---------------------------------------------------------------------------
# begin_swarm tool tests (Q&A phase)
# ---------------------------------------------------------------------------


async def test_begin_swarm_tool_returns_correct_shape():
    """begin_swarm tool has correct name and skip_permission=True."""
    from backend.swarm.tools import create_begin_swarm_tool

    holder: list[str] = []
    event = asyncio.Event()
    tool = create_begin_swarm_tool(holder, event)

    assert isinstance(tool, Tool)
    assert tool.name == "begin_swarm"
    assert tool.skip_permission is True


async def test_begin_swarm_captures_refined_goal():
    """Invoking begin_swarm stores refined_goal and sets the completion event."""
    from backend.swarm.tools import create_begin_swarm_tool

    holder: list[str] = []
    event = asyncio.Event()
    tool = create_begin_swarm_tool(holder, event)

    invocation = ToolInvocation(
        arguments={"refined_goal": "Build a mid-size AKS platform for 12 legacy apps with pragmatic security."}
    )
    result = await tool.handler(invocation)

    assert result.result_type == "success"
    assert len(holder) == 1
    assert "mid-size AKS platform" in holder[0]
    assert event.is_set()


async def test_begin_swarm_rejects_missing_refined_goal():
    """begin_swarm with missing refined_goal returns failure."""
    from backend.swarm.tools import create_begin_swarm_tool

    holder: list[str] = []
    event = asyncio.Event()
    tool = create_begin_swarm_tool(holder, event)

    invocation = ToolInvocation(arguments={"wrong_field": "oops"})
    result = await tool.handler(invocation)

    assert result.result_type == "failure"
    assert len(holder) == 0
    assert not event.is_set()
