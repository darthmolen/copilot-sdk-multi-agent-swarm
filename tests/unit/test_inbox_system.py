"""TDD tests for InboxSystem -- Red/Green for each behaviour."""

from __future__ import annotations

import asyncio

from backend.swarm.inbox_system import InboxSystem

# ---------------------------------------------------------------------------
# 1. send + receive delivers message with correct sender/recipient/content
# ---------------------------------------------------------------------------


async def test_send_and_receive_delivers_correct_message():
    inbox = InboxSystem()

    msg = await inbox.send("alice", "bob", "hello bob")

    assert msg.sender == "alice"
    assert msg.recipient == "bob"
    assert msg.content == "hello bob"
    assert msg.timestamp is not None

    received = await inbox.receive("bob")
    assert len(received) == 1
    assert received[0].sender == "alice"
    assert received[0].recipient == "bob"
    assert received[0].content == "hello bob"


# ---------------------------------------------------------------------------
# 2. receive is destructive (second call returns empty list)
# ---------------------------------------------------------------------------


async def test_receive_is_destructive():
    inbox = InboxSystem()

    await inbox.send("alice", "bob", "msg1")

    first = await inbox.receive("bob")
    assert len(first) == 1

    second = await inbox.receive("bob")
    assert second == []


# ---------------------------------------------------------------------------
# 3. peek is non-destructive (message still there after peek)
# ---------------------------------------------------------------------------


async def test_peek_is_non_destructive():
    inbox = InboxSystem()

    await inbox.send("alice", "bob", "persistent")

    peeked = await inbox.peek("bob")
    assert len(peeked) == 1
    assert peeked[0].content == "persistent"

    peeked_again = await inbox.peek("bob")
    assert len(peeked_again) == 1
    assert peeked_again[0].content == "persistent"

    # receive should still find it
    received = await inbox.receive("bob")
    assert len(received) == 1
    assert received[0].content == "persistent"


# ---------------------------------------------------------------------------
# 4. broadcast delivers to all registered agents except sender
# ---------------------------------------------------------------------------


async def test_broadcast_delivers_to_all_except_sender():
    inbox = InboxSystem()
    inbox.register_agent("alice")
    inbox.register_agent("bob")
    inbox.register_agent("carol")

    msgs = await inbox.broadcast("alice", "team update")

    # alice should NOT receive her own broadcast
    alice_inbox = await inbox.receive("alice")
    assert alice_inbox == []

    # bob and carol should each get the message
    bob_inbox = await inbox.receive("bob")
    assert len(bob_inbox) == 1
    assert bob_inbox[0].sender == "alice"
    assert bob_inbox[0].content == "team update"
    assert bob_inbox[0].recipient == "bob"

    carol_inbox = await inbox.receive("carol")
    assert len(carol_inbox) == 1
    assert carol_inbox[0].sender == "alice"
    assert carol_inbox[0].content == "team update"
    assert carol_inbox[0].recipient == "carol"

    # returned messages should match
    assert len(msgs) == 2
    recipients = {m.recipient for m in msgs}
    assert recipients == {"bob", "carol"}


async def test_broadcast_respects_exclude_list():
    inbox = InboxSystem()
    inbox.register_agent("alice")
    inbox.register_agent("bob")
    inbox.register_agent("carol")

    msgs = await inbox.broadcast("alice", "secret", exclude=["carol"])

    bob_inbox = await inbox.receive("bob")
    assert len(bob_inbox) == 1

    carol_inbox = await inbox.receive("carol")
    assert carol_inbox == []

    assert len(msgs) == 1
    assert msgs[0].recipient == "bob"


# ---------------------------------------------------------------------------
# 5. Multiple messages queue in order (FIFO)
# ---------------------------------------------------------------------------


async def test_multiple_messages_fifo_order():
    inbox = InboxSystem()

    await inbox.send("alice", "bob", "first")
    await inbox.send("carol", "bob", "second")
    await inbox.send("alice", "bob", "third")

    received = await inbox.receive("bob")
    assert len(received) == 3
    assert received[0].content == "first"
    assert received[1].content == "second"
    assert received[2].content == "third"


# ---------------------------------------------------------------------------
# 6. Concurrent send/receive don't corrupt state (asyncio.Lock)
# ---------------------------------------------------------------------------


async def test_concurrent_send_receive_no_corruption():
    inbox = InboxSystem()
    total_messages = 100

    async def sender(i: int) -> None:
        await inbox.send("sender", "target", f"msg-{i}")

    # Fire off many concurrent sends
    await asyncio.gather(*(sender(i) for i in range(total_messages)))

    received = await inbox.receive("target")
    assert len(received) == total_messages

    # All message contents should be present (order across concurrent tasks
    # is non-deterministic, but all must arrive)
    contents = {m.content for m in received}
    expected = {f"msg-{i}" for i in range(total_messages)}
    assert contents == expected

    # Inbox is now empty
    again = await inbox.receive("target")
    assert again == []


async def test_concurrent_send_and_receive_interleaved():
    """Interleaved sends and receives must not lose or duplicate messages."""
    inbox = InboxSystem()
    collected: list[str] = []
    lock = asyncio.Lock()

    async def producer(start: int, count: int) -> None:
        for i in range(start, start + count):
            await inbox.send("p", "c", f"m-{i}")

    async def consumer() -> None:
        msgs = await inbox.receive("c")
        async with lock:
            collected.extend(m.content for m in msgs)

    # Run producers and consumers concurrently
    await asyncio.gather(
        producer(0, 50),
        producer(50, 50),
        consumer(),
        consumer(),
        consumer(),
    )

    # Drain anything remaining
    remaining = await inbox.receive("c")
    collected.extend(m.content for m in remaining)

    # Every message produced must be collected exactly once
    assert len(collected) == len(set(collected))
    assert set(collected) == {f"m-{i}" for i in range(100)}
