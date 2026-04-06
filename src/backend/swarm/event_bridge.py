"""SDK-to-WebSocket event bridge.

Maps copilot-sdk SessionEvent types to our WebSocket event taxonomy.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SessionEventType(str, Enum):
    ASSISTANT_TURN_START = "assistant.turn_start"
    ASSISTANT_TURN_END = "assistant.turn_end"
    ASSISTANT_REASONING_DELTA = "assistant.reasoning_delta"
    ASSISTANT_REASONING = "assistant.reasoning"
    ASSISTANT_MESSAGE_DELTA = "assistant.message_delta"
    ASSISTANT_MESSAGE = "assistant.message"
    ASSISTANT_USAGE = "assistant.usage"
    TOOL_EXECUTION_START = "tool.execution_start"
    TOOL_EXECUTION_PARTIAL_RESULT = "tool.execution_partial_result"
    TOOL_EXECUTION_COMPLETE = "tool.execution_complete"
    SUBAGENT_STARTED = "subagent.started"
    SUBAGENT_COMPLETED = "subagent.completed"
    SUBAGENT_FAILED = "subagent.failed"
    SESSION_ERROR = "session.error"
    SESSION_IDLE = "session.idle"


@dataclass
class SessionEventData:
    """Flexible data container for SDK events."""

    # Common fields
    turn_id: str | None = None
    content: str | None = None
    message_id: str | None = None
    delta_content: str | None = None
    reasoning_id: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    partial_output: str | None = None
    success: bool | None = None
    error: str | None = None
    message: str | None = None
    tool_requests: list[Any] | None = None
    agent_name: str | None = None
    agent_display_name: str | None = None


@dataclass
class SessionEvent:
    type: SessionEventType
    data: SessionEventData = field(default_factory=SessionEventData)


def bridge_sdk_event(agent_name: str, event: SessionEvent) -> dict[str, Any] | None:
    """Map an SDK SessionEvent to a WebSocket event dict.

    Returns {"type": str, "data": dict} or None if event should be ignored.

    Critical: handles the tool_requests one-step-off pattern:
    - assistant.message WITH tool_requests -> suppress content, emit agent.message_finalize
    - assistant.message WITHOUT tool_requests -> emit agent.message with content
    """
    t = event.type
    d = event.data

    if t is SessionEventType.ASSISTANT_TURN_START:
        return {"type": "agent.status_changed", "data": {"name": agent_name, "status": "thinking"}}

    if t is SessionEventType.ASSISTANT_TURN_END:
        return {"type": "agent.status_changed", "data": {"name": agent_name, "status": "ready"}}

    if t is SessionEventType.ASSISTANT_REASONING_DELTA:
        return {
            "type": "agent.reasoning_delta",
            "data": {"agent_name": agent_name, "reasoning_id": d.reasoning_id, "delta": d.delta_content},
        }

    if t is SessionEventType.ASSISTANT_REASONING:
        return {
            "type": "agent.reasoning",
            "data": {"agent_name": agent_name, "reasoning_id": d.reasoning_id, "content": d.content},
        }

    if t is SessionEventType.ASSISTANT_MESSAGE_DELTA:
        return {
            "type": "agent.message_delta",
            "data": {"agent_name": agent_name, "delta": d.delta_content, "message_id": d.message_id},
        }

    if t is SessionEventType.ASSISTANT_MESSAGE:
        has_tool_requests = bool(d.tool_requests)
        has_content = bool(d.content and d.content.strip())
        if has_content and not has_tool_requests:
            return {"type": "agent.message", "data": {"agent_name": agent_name, "content": d.content}}
        if has_tool_requests:
            return {"type": "agent.message_finalize", "data": {"agent_name": agent_name, "message_id": d.message_id}}
        return None  # No content and no tool_requests — suppress

    if t is SessionEventType.TOOL_EXECUTION_START:
        return {
            "type": "agent.tool_call",
            "data": {"agent_name": agent_name, "tool_name": d.tool_name, "tool_call_id": d.tool_call_id},
        }

    if t is SessionEventType.TOOL_EXECUTION_PARTIAL_RESULT:
        return {
            "type": "agent.tool_output",
            "data": {"agent_name": agent_name, "tool_call_id": d.tool_call_id, "output": d.partial_output},
        }

    if t is SessionEventType.TOOL_EXECUTION_COMPLETE:
        return {
            "type": "agent.tool_result",
            "data": {"agent_name": agent_name, "tool_call_id": d.tool_call_id, "success": d.success},
        }

    if t is SessionEventType.SUBAGENT_STARTED:
        return {"type": "agent.status_changed", "data": {"name": agent_name, "status": "working"}}

    if t is SessionEventType.SUBAGENT_COMPLETED:
        return {"type": "agent.status_changed", "data": {"name": agent_name, "status": "idle"}}

    if t is SessionEventType.SUBAGENT_FAILED:
        return {"type": "agent.error", "data": {"name": agent_name, "error": d.error}}

    if t is SessionEventType.ASSISTANT_USAGE:
        return {
            "type": "agent.usage",
            "data": {"agent_name": agent_name, "usage": {k: v for k, v in vars(d).items() if v is not None}},
        }

    if t is SessionEventType.SESSION_ERROR:
        return {"type": "agent.error", "data": {"name": agent_name, "error": d.error}}

    return None


# ---------------------------------------------------------------------------
# Unified raw SDK event bridge (Step 1: Chat UX Parity)
# ---------------------------------------------------------------------------

# Tool names with dedicated argument summarization
_PATH_TOOLS = frozenset({"Read", "Edit", "Write"})
_PATTERN_TOOLS = frozenset({"Grep", "Glob"})


def _truncate(value: str | None, max_len: int = 1000) -> str | None:
    """Truncate a string to max_len, appending '...' if clipped. None passes through."""
    if value is None:
        return None
    if len(value) <= max_len:
        return value
    return value[:max_len] + "..."


def _summarize_args(tool_name: str, arguments: dict[str, Any] | None) -> str:
    """Produce a human-readable one-liner from tool arguments.

    Special-cases common tools (Bash, Read, Edit, Grep, etc.) and falls back
    to key=value for anything else.
    """
    if not arguments:
        return ""

    if tool_name == "Bash":
        cmd = arguments.get("command", "")
        return str(cmd)[:200] if cmd else ""

    if tool_name in _PATH_TOOLS:
        path = arguments.get("file_path", "")
        return str(path)

    if tool_name in _PATTERN_TOOLS:
        pattern = arguments.get("pattern", "")
        return str(pattern)

    # Generic: key=value pairs, truncated
    parts: list[str] = []
    for k, v in arguments.items():
        parts.append(f"{k}={str(v)[:80]}")
    return ", ".join(parts)[:200]


def bridge_raw_sdk_event(
    agent_name: str,
    event: object,
    *,
    message_id: str | None = None,
    swarm_id: str | None = None,
) -> dict[str, Any] | None:
    """Map a raw SDK event object to a unified WebSocket event dict.

    Unlike ``bridge_sdk_event`` (which works with our local SessionEvent
    dataclass), this function works with the real SDK event objects via
    ``getattr``, making it safe for both production and test fakes.

    Returns ``{"type": str, "data": dict}`` or ``None`` if the event type
    is not tool-related and should be ignored by this bridge.
    """
    raw_type = getattr(event, "type", "")
    et = getattr(raw_type, "value", str(raw_type)).lower()
    data = getattr(event, "data", None)

    if "tool.execution_start" in et or "tool_execution_start" in et:
        tool_name = getattr(data, "tool_name", "") or ""
        tool_call_id = getattr(data, "tool_call_id", "") or ""
        arguments = getattr(data, "arguments", None)
        return {
            "type": "agent.tool_call",
            "data": {
                "agent_name": agent_name,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "input": _summarize_args(tool_name, arguments),
                "swarm_id": swarm_id,
                "message_id": message_id,
            },
        }

    if "tool.execution_complete" in et or "tool_execution_complete" in et:
        tool_call_id = getattr(data, "tool_call_id", "") or ""
        success = getattr(data, "success", None)
        error = getattr(data, "error", None)

        # Extract output from result object
        result_obj = getattr(data, "result", None)
        output: str | None = None
        if result_obj is not None:
            # Prefer detailed_content, fall back to content
            detailed = getattr(result_obj, "detailed_content", None)
            content = getattr(result_obj, "content", None)
            raw_output = detailed if detailed else content
            if raw_output is not None:
                output = _truncate(str(raw_output))

        return {
            "type": "agent.tool_result",
            "data": {
                "agent_name": agent_name,
                "tool_call_id": tool_call_id,
                "success": success,
                "output": output,
                "error": str(error) if error else None,
                "swarm_id": swarm_id,
                "message_id": message_id,
            },
        }

    if "tool.execution_partial_result" in et or "tool_execution_partial_result" in et:
        tool_call_id = getattr(data, "tool_call_id", "") or ""
        partial = getattr(data, "partial_output", "") or ""
        return {
            "type": "agent.tool_output",
            "data": {
                "agent_name": agent_name,
                "tool_call_id": tool_call_id,
                "output": str(partial),
                "swarm_id": swarm_id,
                "message_id": message_id,
            },
        }

    return None
