"""Basic session lifecycle tests against a live copilot-cli process.

Every test creates its own session so that failures are isolated.
These tests make real LLM API calls -- keep prompts minimal.
"""

import asyncio

import pytest
import pytest_asyncio

from copilot import CopilotClient, CopilotSession, SubprocessConfig
from copilot.session import PermissionHandler

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_session(client: CopilotClient) -> CopilotSession:
    """Create a session with approve-all permissions."""
    return await client.create_session(
        on_permission_request=PermissionHandler.approve_all,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_create_session_returns_session_id(copilot_client: CopilotClient):
    """Creating a session should yield a non-empty session ID."""
    session = await _create_session(copilot_client)
    assert isinstance(session.session_id, str)
    assert len(session.session_id) > 0
    await session.disconnect()


async def test_send_and_wait_returns_response(copilot_client: CopilotClient):
    """send_and_wait should return a response containing expected text."""
    session = await _create_session(copilot_client)
    try:
        response = await session.send_and_wait(
            "Reply with exactly: hello world",
            timeout=120,
        )
        assert response is not None, "Expected a non-None response from the assistant"
        # The response.data.content should contain the word "hello"
        content = getattr(response.data, "content", "") or ""
        assert "hello" in content.lower(), (
            f"Expected 'hello' in response content, got: {content!r}"
        )
    finally:
        await session.disconnect()


async def test_session_events_fire(copilot_client: CopilotClient):
    """Session events should fire for turn_start and turn_end (or equivalent)."""
    session = await _create_session(copilot_client)
    collected_types: list[str] = []

    def _on_event(event):
        collected_types.append(event.type.value if hasattr(event.type, "value") else str(event.type))

    session.on(_on_event)
    try:
        await session.send_and_wait("Say hi", timeout=120)
        # At minimum we expect some events to have been emitted.
        assert len(collected_types) > 0, "No events received"
        # Check for turn_start and turn_end (or assistant.turn_start / assistant.turn_end)
        has_turn_start = any("turn_start" in t for t in collected_types)
        has_turn_end = any("turn_end" in t for t in collected_types)
        assert has_turn_start, f"No turn_start event found in: {collected_types}"
        assert has_turn_end, f"No turn_end event found in: {collected_types}"
    finally:
        await session.disconnect()


async def test_session_disconnect_is_clean(copilot_client: CopilotClient):
    """Disconnecting a session should not raise any exceptions."""
    session = await _create_session(copilot_client)
    # Disconnecting immediately (no messages sent) should be fine.
    await session.disconnect()
