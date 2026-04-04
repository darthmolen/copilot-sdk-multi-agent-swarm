"""EventLogger — EventBus subscriber that persists events to Postgres."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.db.tables import events

log = structlog.get_logger()

# Event types to skip (non-serializable or internal)
_SKIP_TYPES = {"sdk_event"}


class EventLogger:
    """Appends events to the events table. Register as an EventBus subscriber."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Persist a single event."""
        if event_type in _SKIP_TYPES:
            return

        swarm_id_str = data.get("swarm_id")
        swarm_id = UUID(swarm_id_str) if swarm_id_str else None

        # Strip non-serializable values from data
        clean_data = {k: v for k, v in data.items() if _is_json_serializable(v)}

        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    events.insert().values(
                        swarm_id=swarm_id,
                        event_type=event_type,
                        data_json=clean_data,
                    )
                )
        except Exception:
            log.warning("event_logger_write_failed", event_type=event_type)

    async def on_event(self, event_type: str, data: dict[str, Any]) -> None:
        """EventBus subscriber callback."""
        await self.log_event(event_type, data)


def _is_json_serializable(v: Any) -> bool:
    """Quick check — rejects objects that would break JSONB serialization."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return True
    if isinstance(v, (list, tuple)):
        return all(_is_json_serializable(i) for i in v)
    if isinstance(v, dict):
        return all(isinstance(k, str) and _is_json_serializable(val) for k, val in v.items())
    return False
