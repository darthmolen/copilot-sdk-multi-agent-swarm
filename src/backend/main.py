"""FastAPI application: REST endpoints + WebSocket for real-time swarm events."""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.api.rest import configure, router, swarm_store
from backend.api.websocket import ConnectionManager
from backend.events import EventBus
from backend.logging_config import configure_logging
from backend.swarm.template_loader import TemplateLoader

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
configure_logging(json_file=LOG_DIR / "backend.log")
log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Shared singletons
# ---------------------------------------------------------------------------

manager = ConnectionManager()
event_bus = EventBus()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle (startup/shutdown)."""

    # --- Copilot client (optional) ----------------------------------------
    copilot_client = None
    try:
        from copilot import CopilotClient, SubprocessConfig  # type: ignore[import-not-found]

        cli_path = shutil.which("copilot")
        if cli_path:
            copilot_client = CopilotClient(
                SubprocessConfig(cli_path=cli_path, use_stdio=True)
            )
            await copilot_client.start()
            log.info("copilot_cli_connected", cli_path=cli_path)
        else:
            log.warning("copilot_binary_not_found")
    except Exception as exc:
        log.warning("copilot_cli_start_failed", error=str(exc))

    # --- Template loader --------------------------------------------------
    templates_dir = Path("src/templates")
    template_loader = TemplateLoader(templates_dir) if templates_dir.is_dir() else None
    if template_loader:
        log.info("templates_loaded", path=str(templates_dir))
    else:
        log.warning("templates_dir_not_found", path=str(templates_dir))

    # --- Wire dependencies ------------------------------------------------
    configure(event_bus, copilot_client, template_loader)

    # --- EventBus → WebSocket forwarder -----------------------------------
    def _make_ws_forwarder():  # noqa: ANN202
        async def _forward(event_type: str, data: dict) -> None:
            swarm_id = data.pop("swarm_id", None)
            if swarm_id:
                await manager.broadcast(
                    swarm_id, {"type": event_type, "data": data}
                )
            else:
                for sid in list(swarm_store.keys()):
                    await manager.broadcast(
                        sid, {"type": event_type, "data": data}
                    )

        return _forward

    unsub = event_bus.subscribe(_make_ws_forwarder())
    log.info("backend_started", address="http://0.0.0.0:8000")

    yield

    # --- Shutdown ---------------------------------------------------------
    unsub()
    if copilot_client:
        await copilot_client.stop()
        log.info("copilot_cli_stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.websocket("/ws/{swarm_id}")
async def websocket_endpoint(websocket: WebSocket, swarm_id: str) -> None:
    """WebSocket endpoint for streaming swarm events to clients."""
    await manager.connect(websocket, swarm_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, swarm_id)
