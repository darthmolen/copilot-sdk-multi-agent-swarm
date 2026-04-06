"""Tests for SDK-to-WebSocket event bridge."""

from backend.swarm.event_bridge import (
    SessionEvent,
    SessionEventData,
    SessionEventType,
    _summarize_args,
    _truncate,
    bridge_raw_sdk_event,
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


# ---------------------------------------------------------------------------
# Tests for bridge_raw_sdk_event (unified tool event stream)
# ---------------------------------------------------------------------------

class _FakeData:
    """Minimal object that responds to getattr for SDK event data fields."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeEvent:
    """Minimal SDK-like event with .type and .data attributes."""

    def __init__(self, event_type: str, **data_kwargs: object) -> None:
        self.type = event_type
        self.data = _FakeData(**data_kwargs) if data_kwargs else None


class TestBridgeRawToolStart:
    def test_bridge_raw_tool_start_includes_input(self) -> None:
        """tool.execution_start with arguments -> agent.tool_call with summarized input."""
        event = _FakeEvent(
            "tool.execution_start",
            tool_name="Bash",
            tool_call_id="tc-42",
            arguments={"command": "ls -la", "timeout": 5000},
        )
        result = bridge_raw_sdk_event("leader", event)
        assert result is not None
        assert result["type"] == "agent.tool_call"
        data = result["data"]
        assert data["agent_name"] == "leader"
        assert data["tool_name"] == "Bash"
        assert data["tool_call_id"] == "tc-42"
        assert "input" in data
        assert "ls -la" in data["input"]


class TestBridgeRawToolResult:
    def test_bridge_raw_tool_result_includes_output(self) -> None:
        """tool.execution_complete with result -> agent.tool_result with output field."""

        class _FakeResult:
            content = "file1.txt\nfile2.txt"
            detailed_content = None

        event = _FakeEvent(
            "tool.execution_complete",
            tool_call_id="tc-42",
            success=True,
            result=_FakeResult(),
            error=None,
        )
        result = bridge_raw_sdk_event("leader", event)
        assert result is not None
        assert result["type"] == "agent.tool_result"
        data = result["data"]
        assert data["agent_name"] == "leader"
        assert data["tool_call_id"] == "tc-42"
        assert data["success"] is True
        assert "output" in data
        assert "file1.txt" in data["output"]
        assert data["error"] is None

    def test_bridge_raw_tool_result_includes_error(self) -> None:
        """tool.execution_complete with error -> agent.tool_result with error field."""
        event = _FakeEvent(
            "tool.execution_complete",
            tool_call_id="tc-99",
            success=False,
            result=None,
            error="Permission denied",
        )
        result = bridge_raw_sdk_event("leader", event)
        assert result is not None
        assert result["type"] == "agent.tool_result"
        data = result["data"]
        assert data["success"] is False
        assert data["error"] == "Permission denied"
        assert data["output"] is None


class TestBridgeRawMessageId:
    def test_bridge_raw_passes_message_id(self) -> None:
        """When message_id kwarg is provided, it appears in the output."""
        event = _FakeEvent(
            "tool.execution_start",
            tool_name="Read",
            tool_call_id="tc-1",
            arguments={"file_path": "/tmp/f.py"},
        )
        result = bridge_raw_sdk_event("leader", event, message_id="chat-123")
        assert result is not None
        assert result["data"]["message_id"] == "chat-123"

    def test_bridge_raw_message_id_null_when_absent(self) -> None:
        """When no message_id kwarg, field is None."""
        event = _FakeEvent(
            "tool.execution_start",
            tool_name="Read",
            tool_call_id="tc-1",
            arguments={"file_path": "/tmp/f.py"},
        )
        result = bridge_raw_sdk_event("leader", event)
        assert result is not None
        assert result["data"]["message_id"] is None


class TestBridgeRawSwarmId:
    def test_bridge_raw_passes_swarm_id(self) -> None:
        """When swarm_id kwarg is provided, it appears in the output."""
        event = _FakeEvent(
            "tool.execution_start",
            tool_name="Bash",
            tool_call_id="tc-1",
            arguments={"command": "echo hi"},
        )
        result = bridge_raw_sdk_event("worker-1", event, swarm_id="swarm-abc")
        assert result is not None
        assert result["data"]["swarm_id"] == "swarm-abc"

    def test_bridge_raw_swarm_id_null_when_absent(self) -> None:
        """When no swarm_id, field is None."""
        event = _FakeEvent(
            "tool.execution_start",
            tool_name="Bash",
            tool_call_id="tc-1",
            arguments={"command": "echo hi"},
        )
        result = bridge_raw_sdk_event("worker-1", event)
        assert result is not None
        assert result["data"]["swarm_id"] is None


class TestBridgeRawPartialResult:
    def test_bridge_raw_partial_result(self) -> None:
        """tool.execution_partial_result -> agent.tool_output."""
        event = _FakeEvent(
            "tool.execution_partial_result",
            tool_call_id="tc-7",
            partial_output="streaming line 1",
        )
        result = bridge_raw_sdk_event("leader", event)
        assert result is not None
        assert result["type"] == "agent.tool_output"
        assert result["data"]["tool_call_id"] == "tc-7"
        assert result["data"]["output"] == "streaming line 1"


class TestBridgeRawUnknownEvent:
    def test_bridge_raw_returns_none_for_unknown(self) -> None:
        """Unknown event types return None."""
        event = _FakeEvent("some.unknown.event")
        result = bridge_raw_sdk_event("leader", event)
        assert result is None


class TestSummarizeArgs:
    def test_summarize_args_formats_bash(self) -> None:
        """Bash tool shows command."""
        result = _summarize_args("Bash", {"command": "git status", "timeout": 5000})
        assert "git status" in result

    def test_summarize_args_formats_read(self) -> None:
        """Read tool shows file_path."""
        result = _summarize_args("Read", {"file_path": "/home/user/project/main.py", "limit": 100})
        assert "/home/user/project/main.py" in result

    def test_summarize_args_formats_edit(self) -> None:
        """Edit tool shows file_path."""
        result = _summarize_args("Edit", {"file_path": "/tmp/f.py", "old_string": "foo", "new_string": "bar"})
        assert "/tmp/f.py" in result

    def test_summarize_args_formats_write(self) -> None:
        """Write tool shows file_path."""
        result = _summarize_args("Write", {"file_path": "/tmp/out.txt", "content": "hello"})
        assert "/tmp/out.txt" in result

    def test_summarize_args_formats_grep(self) -> None:
        """Grep tool shows pattern."""
        result = _summarize_args("Grep", {"pattern": "def main", "path": "/src"})
        assert "def main" in result

    def test_summarize_args_formats_glob(self) -> None:
        """Glob tool shows pattern."""
        result = _summarize_args("Glob", {"pattern": "**/*.py"})
        assert "**/*.py" in result

    def test_summarize_args_generic_key_value(self) -> None:
        """Generic tool shows key=value pairs."""
        result = _summarize_args("custom_tool", {"key1": "val1", "key2": "val2"})
        assert "key1=" in result
        assert "key2=" in result

    def test_summarize_args_none(self) -> None:
        """None arguments return empty string."""
        result = _summarize_args("Bash", None)
        assert result == ""

    def test_summarize_args_empty(self) -> None:
        """Empty dict returns empty string."""
        result = _summarize_args("Bash", {})
        assert result == ""


class TestTruncate:
    def test_truncate_none(self) -> None:
        assert _truncate(None) is None

    def test_truncate_short_string(self) -> None:
        assert _truncate("hello") == "hello"

    def test_truncate_long_string(self) -> None:
        long_str = "x" * 2000
        result = _truncate(long_str, max_len=500)
        assert len(result) <= 503  # 500 + "..."
        assert result.endswith("...")

    def test_truncate_default_limit(self) -> None:
        long_str = "y" * 2000
        result = _truncate(long_str)
        assert len(result) <= 1003  # default 1000 + "..."
