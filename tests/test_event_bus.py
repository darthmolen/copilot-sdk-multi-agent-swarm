"""Tests for EventBus (Phase 2c)."""

from __future__ import annotations

import asyncio

import pytest

from backend.events import EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_collector() -> tuple[list[tuple[str, dict]], "Callback"]:
    """Return (collected_events, async_callback)."""
    collected: list[tuple[str, dict]] = []

    async def _cb(event_type: str, data: dict) -> None:
        collected.append((event_type, data))

    return collected, _cb


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_subscribe_and_emit_delivers_event() -> None:
    bus = EventBus()
    collected, cb = _make_collector()

    bus.subscribe(cb)
    await bus.emit("agent.message", {"text": "hello"})

    assert collected == [("agent.message", {"text": "hello"})]


async def test_emit_sync_schedules_delivery() -> None:
    bus = EventBus()
    collected, cb = _make_collector()

    bus.subscribe(cb)
    bus.emit_sync("sync.event", {"n": 1})

    # Yield control so the scheduled coroutine can run.
    await asyncio.sleep(0.05)

    assert collected == [("sync.event", {"n": 1})]


async def test_multiple_subscribers_receive_same_event() -> None:
    bus = EventBus()
    collected_a, cb_a = _make_collector()
    collected_b, cb_b = _make_collector()

    bus.subscribe(cb_a)
    bus.subscribe(cb_b)
    await bus.emit("shared", {"v": 42})

    assert collected_a == [("shared", {"v": 42})]
    assert collected_b == [("shared", {"v": 42})]


async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    collected, cb = _make_collector()

    unsub = bus.subscribe(cb)
    await bus.emit("before", {})
    assert len(collected) == 1

    unsub()
    await bus.emit("after", {})
    assert len(collected) == 1  # no new event delivered


async def test_emit_with_no_subscribers_does_not_error() -> None:
    bus = EventBus()
    await bus.emit("lonely", {"ignored": True})  # must not raise


async def test_subscriber_error_does_not_break_other_subscribers() -> None:
    bus = EventBus()
    collected, good_cb = _make_collector()

    async def bad_cb(event_type: str, data: dict) -> None:
        raise RuntimeError("boom")

    bus.subscribe(bad_cb)
    bus.subscribe(good_cb)

    await bus.emit("error.test", {"x": 1})

    assert collected == [("error.test", {"x": 1})]


async def test_multiple_events_in_sequence() -> None:
    bus = EventBus()
    collected, cb = _make_collector()

    bus.subscribe(cb)
    await bus.emit("e1", {"i": 1})
    await bus.emit("e2", {"i": 2})
    await bus.emit("e3", {"i": 3})

    assert collected == [
        ("e1", {"i": 1}),
        ("e2", {"i": 2}),
        ("e3", {"i": 3}),
    ]
