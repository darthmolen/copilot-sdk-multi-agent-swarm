"""Integration-lite tests for swarm tool handlers in a real async context.

These tests verify that tool handlers work correctly when invoked inside a
real asyncio event loop -- the same conditions they encounter in production.
No copilot-cli session is required; we invoke handlers directly with our own
ToolInvocation dataclass.
"""

import json

import pytest

from backend.swarm.inbox_system import InboxSystem
from backend.swarm.task_board import TaskBoard
from backend.swarm.tools import ToolInvocation, create_swarm_tools

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_tool(tools, name: str):
    """Return the tool with the given name from a list of Tool instances."""
    for tool in tools:
        if tool.name == name:
            return tool
    raise KeyError(f"Tool {name!r} not found in {[t.name for t in tools]}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_task_update_tool_via_handler():
    """Invoking the task_update handler should mutate the shared TaskBoard."""
    board = TaskBoard()
    inbox = InboxSystem()
    agent_name = "worker-alpha"

    # Seed a task so we can update it.
    await board.add_task(
        id="t-1",
        subject="test task",
        description="integration test task",
        worker_role="coder",
        worker_name=agent_name,
    )

    tools = create_swarm_tools(agent_name, board, inbox)
    task_update = _find_tool(tools, "task_update")

    invocation = ToolInvocation(
        session_id="sess-test",
        tool_call_id="call-1",
        tool_name="task_update",
        arguments={"task_id": "t-1", "status": "completed", "result": "done"},
    )
    result = await task_update.handler(invocation)

    assert result.result_type == "success"
    payload = json.loads(result.text_result_for_llm)
    assert payload["ok"] is True

    # Verify the board was actually mutated.
    tasks = await board.get_tasks()
    assert len(tasks) == 1
    assert tasks[0].status.value == "completed"
    assert tasks[0].result == "done"


async def test_inbox_send_tool_handler_end_to_end():
    """Invoking inbox_send should deliver a message via the real InboxSystem."""
    board = TaskBoard()
    inbox = InboxSystem()
    sender = "worker-alpha"
    recipient = "worker-beta"

    inbox.register_agent(sender)
    inbox.register_agent(recipient)

    tools = create_swarm_tools(sender, board, inbox)
    inbox_send = _find_tool(tools, "inbox_send")

    invocation = ToolInvocation(
        session_id="sess-test",
        tool_call_id="call-2",
        tool_name="inbox_send",
        arguments={"to": recipient, "message": "Need your help with task t-1"},
    )
    result = await inbox_send.handler(invocation)

    assert result.result_type == "success"
    payload = json.loads(result.text_result_for_llm)
    assert payload["sent_to"] == recipient

    # Verify message actually landed in the recipient's inbox.
    messages = await inbox.receive(recipient)
    assert len(messages) == 1
    assert messages[0].sender == sender
    assert "task t-1" in messages[0].content


async def test_task_list_with_mixed_statuses():
    """task_list should return all tasks with their correct statuses."""
    board = TaskBoard()
    inbox = InboxSystem()

    # Create tasks with varied statuses.
    await board.add_task(
        id="t-1",
        subject="alpha task",
        description="first",
        worker_role="coder",
        worker_name="worker-a",
    )
    await board.add_task(
        id="t-2",
        subject="beta task",
        description="second",
        worker_role="reviewer",
        worker_name="worker-b",
    )
    await board.add_task(
        id="t-3",
        subject="gamma task",
        description="third -- blocked on t-1",
        worker_role="coder",
        worker_name="worker-a",
        blocked_by=["t-1"],
    )

    # Complete t-1 so that t-3 unblocks.
    await board.update_status("t-1", "completed", result="done")

    tools = create_swarm_tools("leader", board, inbox)
    task_list = _find_tool(tools, "task_list")

    invocation = ToolInvocation(
        session_id="sess-test",
        tool_call_id="call-3",
        tool_name="task_list",
        arguments={},
    )
    result = await task_list.handler(invocation)

    assert result.result_type == "success"
    payload = json.loads(result.text_result_for_llm)
    tasks = payload["tasks"]
    assert len(tasks) == 3

    by_id = {t["id"]: t for t in tasks}
    assert by_id["t-1"]["status"] == "completed"
    assert by_id["t-2"]["status"] == "pending"
    # t-3 was blocked on t-1 which is now completed, so it should be pending.
    assert by_id["t-3"]["status"] == "pending"
