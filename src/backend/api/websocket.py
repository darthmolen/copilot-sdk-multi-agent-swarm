"""ConnectionManager: manages WebSocket connections per swarm_id."""

from __future__ import annotations

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections per swarm_id."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, swarm_id: str) -> None:
        """Accept and register a WebSocket connection for *swarm_id*."""
        await websocket.accept()
        if swarm_id not in self._connections:
            self._connections[swarm_id] = []
        self._connections[swarm_id].append(websocket)

    def disconnect(self, websocket: WebSocket, swarm_id: str) -> None:
        """Remove a WebSocket connection for *swarm_id*."""
        conns = self._connections.get(swarm_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns and swarm_id in self._connections:
            del self._connections[swarm_id]

    async def broadcast(self, swarm_id: str, message: dict) -> None:
        """Send a JSON message to all connections for *swarm_id*."""
        for ws in list(self._connections.get(swarm_id, [])):
            await ws.send_json(message)

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        """Send a JSON message to a single WebSocket connection."""
        await websocket.send_json(message)
