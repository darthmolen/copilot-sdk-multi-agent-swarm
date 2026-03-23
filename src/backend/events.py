"""EventBus: decouples event producers from consumers with async and sync emit."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Union

logger = logging.getLogger(__name__)

Callback = Callable[[str, dict], Union[Awaitable[None], None]]


class EventBus:
    """A publish-subscribe event bus supporting both async and sync emission.

    Subscribers receive ``(event_type, data)`` for every emitted event.
    ``emit`` is used from async contexts; ``emit_sync`` schedules delivery
    from synchronous code onto the running event loop.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._subscribers: list[Callback] = []
        self._loop = loop

    def subscribe(self, callback: Callback) -> Callable[[], None]:
        """Subscribe *callback* to all future events.

        Returns an unsubscribe callable. Calling it removes the subscription.
        """
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass  # already removed

        return unsubscribe

    async def emit(self, event_type: str, data: dict) -> None:
        """Emit an event to all current subscribers (async context).

        If a subscriber raises, the exception is logged and remaining
        subscribers still receive the event.
        """
        for cb in list(self._subscribers):
            try:
                result = cb(event_type, data)
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except Exception:
                logger.exception(
                    "Subscriber %r raised on event %s", cb, event_type
                )

    def emit_sync(self, event_type: str, data: dict) -> None:
        """Schedule event delivery from a synchronous context.

        Uses the captured event loop (or falls back to get_running_loop) to
        schedule an ``emit`` coroutine. Safe for SDK callbacks running in
        threads or synchronous contexts.
        """
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("emit_sync: no event loop available, dropping event %s", event_type)
                return
        loop.call_soon_threadsafe(asyncio.ensure_future, self.emit(event_type, data))
