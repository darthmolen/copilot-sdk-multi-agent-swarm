"""FastAPI application: REST endpoints + WebSocket for real-time swarm events."""

from __future__ import annotations

import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.rest import configure, router, swarm_store
from backend.api.websocket import ConnectionManager
from backend.events import EventBus
from backend.logging_config import configure_logging
from backend.swarm.template_loader import TemplateLoader

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path(os.environ.get("LOGS_DIR", "logs"))
configure_logging(json_file=LOG_DIR / "backend.log")
log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Shared singletons
# ---------------------------------------------------------------------------

manager = ConnectionManager()
event_bus = EventBus()
ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "").lower()
SWARM_API_KEY: str = os.environ.get("SWARM_API_KEY", "")
_raw_timeout = os.environ.get("SWARM_TASK_TIMEOUT", "")
try:
    SWARM_TASK_TIMEOUT: float = float(_raw_timeout) if _raw_timeout else 1800.0
except ValueError:
    SWARM_TASK_TIMEOUT = 1800.0

_raw_zip_size = os.environ.get("SWARM_MAX_TEMPLATE_ZIP_SIZE", "")
try:
    SWARM_MAX_TEMPLATE_ZIP_SIZE: int = int(_raw_zip_size) if _raw_zip_size else 3 * 1024 * 1024
except ValueError:
    SWARM_MAX_TEMPLATE_ZIP_SIZE = 3 * 1024 * 1024

_raw_max_rounds = os.environ.get("SWARM_MAX_ROUNDS", "")
try:
    SWARM_MAX_ROUNDS: int = int(_raw_max_rounds) if _raw_max_rounds else 3
except ValueError:
    SWARM_MAX_ROUNDS = 3

SWARM_MODEL: str = os.environ.get("SWARM_MODEL", "gemini-3-pro-preview")
CORS_ORIGINS: list[str] = [
    o.strip() for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",") if o.strip()
]
SWARM_WORK_DIR: str = os.environ.get("SWARM_WORK_DIR", "workdir")
TEMPLATES_DIR: str = os.environ.get("TEMPLATES_DIR", "src/templates")
LOGS_DIR: str = os.environ.get("LOGS_DIR", "logs")
STATIC_DIR: str = os.environ.get("STATIC_DIR", "static")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _auth_required() -> bool:
    """Auth is required unless ENVIRONMENT=development AND no key is set."""
    if ENVIRONMENT == "development" and not SWARM_API_KEY:
        return False
    return True


async def verify_api_key(x_api_key: str | None = Header(None, alias="X-API-Key")) -> None:
    """Validate API key on REST endpoints.

    Auth is only disabled when ENVIRONMENT=development and SWARM_API_KEY is empty.
    In any other configuration, a valid key is required — missing key = 401.
    """
    if not _auth_required():
        return
    if not SWARM_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="SWARM_API_KEY not configured. Set it in .env or set ENVIRONMENT=development to disable auth.",
        )
    if x_api_key != SWARM_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


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
    templates_dir = Path(TEMPLATES_DIR)
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
            # Skip internal SDK events (contain non-serializable objects)
            # Log them for backend observability, but don't forward to frontend
            if event_type == "sdk_event":
                agent = data.get("agent", "unknown")
                event_obj = data.get("event")
                sdk_type = getattr(getattr(event_obj, "type", ""), "value", "unknown")
                event_data = getattr(event_obj, "data", None)

                # Extract key fields from SDK event data for observability
                extra: dict[str, str | None] = {}
                if event_data:
                    content = getattr(event_data, "content", None)
                    if content:
                        extra["content"] = str(content)[:300]
                    for field in ("tool_name", "tool_call_id", "error", "message",
                                  "reasoning_effort", "turn_id", "success"):
                        val = getattr(event_data, field, None)
                        if val is not None:
                            extra[field] = str(val)[:200]
                    # Permission request details
                    tool_requests = getattr(event_data, "tool_requests", None)
                    if tool_requests:
                        extra["tool_requests"] = str([
                            getattr(tr, "name", tr) for tr in tool_requests[:5]
                        ])

                log.debug("sdk_event", agent=agent, sdk_type=sdk_type, **extra)
                return

            swarm_id = data.get("swarm_id", None)
            extra_log: dict[str, str] = {}
            if event_type == "leader.chat_tool_start":
                extra_log["tool_name"] = data.get("tool_name", "")
            log.info("event_forwarded", event_type=event_type, swarm_id=swarm_id or "broadcast", **extra_log)

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
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, dependencies=[Depends(verify_api_key)])

# Serve frontend static files in production (when built frontend exists)
_static_dir = Path(STATIC_DIR)
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")


@app.websocket("/ws/{swarm_id}")
async def websocket_endpoint(websocket: WebSocket, swarm_id: str, key: str = Query("")) -> None:
    """WebSocket endpoint for streaming swarm events to clients."""
    if _auth_required() and key != SWARM_API_KEY:
        await websocket.close(code=4001, reason="Invalid API key")
        return
    await manager.connect(websocket, swarm_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, swarm_id)
