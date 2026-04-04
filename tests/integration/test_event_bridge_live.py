"""Integration tests for the SDK-to-WebSocket event bridge.

Test 1 requires a live copilot-cli session.
Test 2 exercises all event types synthetically but in a real async context.
"""

import pytest
from copilot import CopilotClient
from copilot.session import PermissionHandler

from backend.swarm.event_bridge import (
    SessionEvent,
    SessionEventData,
    SessionEventType,
    bridge_sdk_event,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sdk_event_to_bridge_event(sdk_event) -> SessionEvent | None:
    """Convert a real SDK SessionEvent to our bridge's SessionEvent format.

    The SDK's generated SessionEvent has:
        - .type  (SessionEventType enum with .value like "assistant.turn_start")
        - .data  (a generated Data dataclass with varying fields)

    Our bridge's SessionEvent has:
        - .type  (our SessionEventType enum)
        - .data  (our SessionEventData dataclass)

    We map by matching the string value of the SDK event type to our enum.
    """
    sdk_type_str = sdk_event.type.value if hasattr(sdk_event.type, "value") else str(sdk_event.type)

    # Try to match against our SessionEventType enum.
    try:
        our_type = SessionEventType(sdk_type_str)
    except ValueError:
        return None  # Event type not in our bridge's vocabulary.

    # Build our SessionEventData from the SDK's data object.
    sdk_data = sdk_event.data
    our_data = SessionEventData(
        turn_id=getattr(sdk_data, "turn_id", None),
        content=getattr(sdk_data, "content", None),
        message_id=getattr(sdk_data, "message_id", None),
        delta_content=getattr(sdk_data, "delta_content", None) or getattr(sdk_data, "delta", None),
        reasoning_id=getattr(sdk_data, "reasoning_id", None),
        tool_name=getattr(sdk_data, "tool_name", None),
        tool_call_id=getattr(sdk_data, "tool_call_id", None),
        partial_output=getattr(sdk_data, "partial_output", None),
        success=getattr(sdk_data, "success", None),
        error=getattr(sdk_data, "error", None),
        message=getattr(sdk_data, "message", None),
        tool_requests=getattr(sdk_data, "tool_requests", None),
        agent_name=getattr(sdk_data, "agent_name", None),
        agent_display_name=getattr(sdk_data, "agent_display_name", None),
    )

    return SessionEvent(type=our_type, data=our_data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_real_session_events_map_through_bridge(copilot_client: CopilotClient):
    """Collect real SDK events from a session, convert them, and run through the bridge."""
    session = await copilot_client.create_session(
        on_permission_request=PermissionHandler.approve_all,
    )

    raw_sdk_events: list = []

    def _collect(event):
        raw_sdk_events.append(event)

    session.on(_collect)

    try:
        await session.send_and_wait("Say hello", timeout=120)
    finally:
        await session.disconnect()

    assert len(raw_sdk_events) > 0, "No SDK events collected from real session"

    mapped_count = 0
    for sdk_event in raw_sdk_events:
        bridge_event = _sdk_event_to_bridge_event(sdk_event)
        if bridge_event is None:
            continue
        ws_event = bridge_sdk_event("test-agent", bridge_event)
        if ws_event is not None:
            mapped_count += 1
            assert "type" in ws_event
            assert "data" in ws_event

    assert mapped_count > 0, (
        f"No SDK events mapped through bridge. Raw event types: {[e.type.value for e in raw_sdk_events]}"
    )


async def test_bridge_handles_all_event_types_gracefully():
    """Feed every SessionEventType through bridge_sdk_event -- none should crash."""
    for event_type in SessionEventType:
        event = SessionEvent(
            type=event_type,
            data=SessionEventData(
                turn_id="turn-0",
                content="test content",
                message_id="msg-0",
                delta_content="delta",
                reasoning_id="reason-0",
                tool_name="some_tool",
                tool_call_id="tc-0",
                partial_output="partial",
                success=True,
                error=None,
                message="test",
                tool_requests=None,
                agent_name="agent-x",
                agent_display_name="Agent X",
            ),
        )
        # Should return a dict or None -- never raise.
        result = bridge_sdk_event("test-agent", event)
        assert result is None or isinstance(result, dict), (
            f"bridge_sdk_event returned unexpected type {type(result)} for event type {event_type.value}"
        )
