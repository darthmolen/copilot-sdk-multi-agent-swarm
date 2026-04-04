"""Point-to-point and broadcast messaging between agents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from backend.swarm.models import InboxMessage


class InboxSystem:
    """Async-safe inbox system for inter-agent messaging."""

    def __init__(self) -> None:
        self._inboxes: dict[str, list[InboxMessage]] = {}
        self._registered_agents: set[str] = set()
        self._lock = asyncio.Lock()

    def register_agent(self, agent_name: str) -> None:
        """Register an agent so it can receive broadcasts."""
        self._registered_agents.add(agent_name)
        if agent_name not in self._inboxes:
            self._inboxes[agent_name] = []

    async def send(self, sender: str, recipient: str, content: str) -> InboxMessage:
        """Send a message from sender to recipient. Returns the created message."""
        message = InboxMessage(
            sender=sender,
            recipient=recipient,
            content=content,
            timestamp=datetime.now(timezone.utc),
        )
        async with self._lock:
            if recipient not in self._inboxes:
                self._inboxes[recipient] = []
            self._inboxes[recipient].append(message)
        return message

    async def receive(self, agent_name: str) -> list[InboxMessage]:
        """Return and clear all messages for agent_name (destructive read)."""
        async with self._lock:
            messages = list(self._inboxes.get(agent_name, []))
            self._inboxes[agent_name] = []
        return messages

    async def peek(self, agent_name: str) -> list[InboxMessage]:
        """Return all messages for agent_name without clearing (non-destructive)."""
        async with self._lock:
            return list(self._inboxes.get(agent_name, []))

    async def broadcast(self, sender: str, content: str, exclude: list[str] | None = None) -> list[InboxMessage]:
        """Send a message to all registered agents except sender and any in exclude."""
        exclude_set = {sender}
        if exclude:
            exclude_set.update(exclude)

        recipients = [a for a in self._registered_agents if a not in exclude_set]
        messages: list[InboxMessage] = []

        async with self._lock:
            for recipient in recipients:
                message = InboxMessage(
                    sender=sender,
                    recipient=recipient,
                    content=content,
                    timestamp=datetime.now(timezone.utc),
                )
                if recipient not in self._inboxes:
                    self._inboxes[recipient] = []
                self._inboxes[recipient].append(message)
                messages.append(message)

        return messages
