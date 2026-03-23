"""FastAPI application: REST endpoints + WebSocket for real-time swarm events."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from backend.api.rest import router, swarm_store
from backend.api.websocket import ConnectionManager
from backend.events import EventBus

# Shared singletons
manager = ConnectionManager()
event_bus = EventBus()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle (startup/shutdown)."""
    # Startup: subscribe event_bus to forward events to WebSocket clients
    def _make_ws_forwarder():  # noqa: ANN202
        async def _forward(event_type: str, data: dict) -> None:
            swarm_id = data.get("swarm_id", "")
            if swarm_id:
                await manager.broadcast(
                    swarm_id, {"type": event_type, **data}
                )
        return _forward

    unsub = event_bus.subscribe(_make_ws_forwarder())
    yield
    # Shutdown
    unsub()


app = FastAPI(lifespan=lifespan)
app.include_router(router)


@app.websocket("/ws/{swarm_id}")
async def websocket_endpoint(websocket: WebSocket, swarm_id: str) -> None:
    """WebSocket endpoint for streaming swarm events to clients."""
    await manager.connect(websocket, swarm_id)
    try:
        while True:
            # Keep connection alive; read client messages (ping/commands)
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, swarm_id)
