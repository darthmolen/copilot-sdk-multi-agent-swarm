"""Tests for SDK-to-WebSocket event bridge."""

from backend.swarm.event_bridge import (
    SessionEvent,
    SessionEventData,
    SessionEventType,
    bridge_sdk_event,
)

AGENT = "test-agent"


def test_turn_start_maps_to_thinking():
    event = SessionEvent(type=SessionEventType.ASSISTANT_TURN_START)
    result = bridge_sdk_event(AGENT, event)
    assert result == {"type": "agent.status_changed", "data": {"name": AGENT, "status": "thinking"}}


def test_turn_end_maps_to_ready():
    event = SessionEvent(type=SessionEventType.ASSISTANT_TURN_END)
    result = bridge_sdk_event(AGENT, event)
    assert result == {"type": "agent.status_changed", "data": {"name": AGENT, "status": "ready"}}


def test_reasoning_delta_maps_correctly():
    event = SessionEvent(
        type=SessionEventType.ASSISTANT_REASONING_DELTA,
        data=SessionEventData(reasoning_id="r-1", delta_content="thinking about..."),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result == {
        "type": "agent.reasoning_delta",
        "data": {"agent_name": AGENT, "reasoning_id": "r-1", "delta": "thinking about..."},
    }


def test_message_delta_maps_correctly():
    event = SessionEvent(
        type=SessionEventType.ASSISTANT_MESSAGE_DELTA,
        data=SessionEventData(delta_content="Hello", message_id="msg-1"),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result == {
        "type": "agent.message_delta",
        "data": {"agent_name": AGENT, "delta": "Hello", "message_id": "msg-1"},
    }


def test_message_without_tool_requests_emits_content():
    event = SessionEvent(
        type=SessionEventType.ASSISTANT_MESSAGE,
        data=SessionEventData(content="Final answer", tool_requests=None),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result == {"type": "agent.message", "data": {"agent_name": AGENT, "content": "Final answer"}}


def test_message_with_tool_requests_emits_finalize():
    event = SessionEvent(
        type=SessionEventType.ASSISTANT_MESSAGE,
        data=SessionEventData(
            content="I will call a tool",
            message_id="msg-2",
            tool_requests=[{"tool": "search", "args": {}}],
        ),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result is not None
    assert result == {
        "type": "agent.message_finalize",
        "data": {"agent_name": AGENT, "message_id": "msg-2"},
    }
    # Content must be suppressed
    assert "content" not in result["data"]


def test_message_with_tool_requests_and_no_content():
    event = SessionEvent(
        type=SessionEventType.ASSISTANT_MESSAGE,
        data=SessionEventData(
            content=None,
            message_id="msg-3",
            tool_requests=[{"tool": "run_code"}],
        ),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result == {
        "type": "agent.message_finalize",
        "data": {"agent_name": AGENT, "message_id": "msg-3"},
    }


def test_tool_execution_start():
    event = SessionEvent(
        type=SessionEventType.TOOL_EXECUTION_START,
        data=SessionEventData(tool_name="search", tool_call_id="tc-1"),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result == {
        "type": "agent.tool_call",
        "data": {"agent_name": AGENT, "tool_name": "search", "tool_call_id": "tc-1"},
    }


def test_tool_execution_complete():
    event = SessionEvent(
        type=SessionEventType.TOOL_EXECUTION_COMPLETE,
        data=SessionEventData(tool_call_id="tc-1", success=True),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result == {
        "type": "agent.tool_result",
        "data": {"agent_name": AGENT, "tool_call_id": "tc-1", "success": True},
    }


def test_tool_partial_result():
    event = SessionEvent(
        type=SessionEventType.TOOL_EXECUTION_PARTIAL_RESULT,
        data=SessionEventData(tool_call_id="tc-1", partial_output="partial data..."),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result == {
        "type": "agent.tool_output",
        "data": {"agent_name": AGENT, "tool_call_id": "tc-1", "output": "partial data..."},
    }


def test_subagent_started():
    event = SessionEvent(type=SessionEventType.SUBAGENT_STARTED)
    result = bridge_sdk_event(AGENT, event)
    assert result == {"type": "agent.status_changed", "data": {"name": AGENT, "status": "working"}}


def test_subagent_completed():
    event = SessionEvent(type=SessionEventType.SUBAGENT_COMPLETED)
    result = bridge_sdk_event(AGENT, event)
    assert result == {"type": "agent.status_changed", "data": {"name": AGENT, "status": "idle"}}


def test_subagent_failed():
    event = SessionEvent(
        type=SessionEventType.SUBAGENT_FAILED,
        data=SessionEventData(error="timeout exceeded"),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result == {"type": "agent.error", "data": {"name": AGENT, "error": "timeout exceeded"}}


def test_session_error():
    event = SessionEvent(
        type=SessionEventType.SESSION_ERROR,
        data=SessionEventData(error="rate limit hit"),
    )
    result = bridge_sdk_event(AGENT, event)
    assert result == {"type": "agent.error", "data": {"name": AGENT, "error": "rate limit hit"}}
