"""FastAPI application: REST endpoints + WebSocket for real-time swarm events."""

from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.api.rest import configure, router, swarm_store
from backend.api.websocket import ConnectionManager
from backend.events import EventBus
from backend.swarm.template_loader import TemplateLoader

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "backend.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

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
            logger.info("Copilot CLI connected: %s", cli_path)
        else:
            logger.warning("copilot binary not found in PATH — swarms will not execute")
    except Exception as exc:
        logger.warning("Failed to start Copilot CLI: %s — swarms will not execute", exc)

    # --- Template loader --------------------------------------------------
    templates_dir = Path("src/templates")
    template_loader = TemplateLoader(templates_dir) if templates_dir.is_dir() else None
    if template_loader:
        logger.info("Loaded templates from %s", templates_dir)
    else:
        logger.warning("Templates directory not found: %s", templates_dir)

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
    logger.info("Backend started — listening on http://0.0.0.0:8000")

    yield

    # --- Shutdown ---------------------------------------------------------
    unsub()
    if copilot_client:
        await copilot_client.stop()
        logger.info("Copilot CLI stopped")


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
