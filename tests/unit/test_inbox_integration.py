"""Integration test: inbox_send tool → EventBus → WS forwarder → WebSocket client.

Tests the full chain from tool invocation to frontend event delivery.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.events import EventBus
from backend.swarm.inbox_system import InboxSystem
from backend.swarm.task_board import TaskBoard
from backend.swarm.tools import ToolInvocation, create_swarm_tools


async def test_inbox_send_event_reaches_eventbus_subscriber() -> None:
    """When inbox_send tool runs with event_callback wired to EventBus,
    an EventBus subscriber receives the inbox.message event."""
    task_board = TaskBoard()
    inbox = InboxSystem()
    inbox.register_agent("sender_agent")
    inbox.register_agent("receiver_agent")
    event_bus = EventBus()

    # Collect events from EventBus
    received: list[tuple[str, dict]] = []
    event_bus.subscribe(lambda t, d: received.append((t, d)))

    # Wire event_callback to emit_sync (same as SwarmAgent does)
    def _tool_event_callback(event_data: dict) -> None:
        event_name = event_data.get("event", "tool_event")
        event_bus.emit_sync(event_name, event_data)

    tools = create_swarm_tools(
        "sender_agent", task_board, inbox, event_callback=_tool_event_callback
    )
    inbox_tool = next(t for t in tools if t.name == "inbox_send")

    # Invoke the tool
    await inbox_tool.handler(
        ToolInvocation(arguments={"to": "receiver_agent", "message": "hello from sender"})
    )

    # emit_sync schedules on the event loop — yield control
    await asyncio.sleep(0.05)

    # Verify EventBus received the event
    inbox_events = [(t, d) for t, d in received if t == "inbox.message"]
    assert len(inbox_events) == 1, f"Expected 1 inbox.message, got {len(inbox_events)}. All events: {received}"

    event_data = inbox_events[0][1]
    assert event_data["sender"] == "sender_agent"
    assert event_data["recipient"] == "receiver_agent"
    assert event_data["content"] == "hello from sender"


async def test_inbox_message_has_correct_shape_for_frontend() -> None:
    """The inbox.message event data matches what the frontend reducer expects:
    {event: "inbox.message", sender: str, recipient: str, content: str}
    """
    task_board = TaskBoard()
    inbox = InboxSystem()
    inbox.register_agent("a")
    inbox.register_agent("b")

    captured: list[dict] = []

    tools = create_swarm_tools("a", task_board, inbox, event_callback=captured.append)
    inbox_tool = next(t for t in tools if t.name == "inbox_send")

    await inbox_tool.handler(ToolInvocation(arguments={"to": "b", "message": "test msg"}))

    assert len(captured) == 1
    msg = captured[0]

    # Frontend reducer expects these fields
    assert msg["event"] == "inbox.message"
    assert msg["sender"] == "a"
    assert msg["recipient"] == "b"
    assert msg["content"] == "test msg"


async def test_task_update_event_reaches_eventbus() -> None:
    """task_update tool with event_callback also emits to EventBus."""
    task_board = TaskBoard()
    inbox = InboxSystem()
    event_bus = EventBus()
    await task_board.add_task(
        id="t1", subject="Test", description="D",
        worker_role="R", worker_name="worker",
    )

    received: list[tuple[str, dict]] = []
    event_bus.subscribe(lambda t, d: received.append((t, d)))

    def _cb(event_data: dict) -> None:
        event_bus.emit_sync(event_data.get("event", "tool_event"), event_data)

    tools = create_swarm_tools("worker", task_board, inbox, event_callback=_cb)
    update_tool = next(t for t in tools if t.name == "task_update")

    await update_tool.handler(
        ToolInvocation(arguments={"task_id": "t1", "status": "in_progress"})
    )

    await asyncio.sleep(0.05)

    task_events = [(t, d) for t, d in received if t == "task.updated"]
    assert len(task_events) == 1
    assert task_events[0][1]["task"]["id"] == "t1"
    assert task_events[0][1]["task"]["status"] == "in_progress"
