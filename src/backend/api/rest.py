"""REST API endpoints for swarm management."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import structlog

from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend.api.schemas import (
    SwarmStartRequest,
    SwarmStartResponse,
    SwarmStatusResponse,
)
from backend.swarm.template_loader import TemplateLoader
from backend.swarm.templates import format_goal
from backend.swarm.templates import list_templates as _list_templates

log = structlog.get_logger()

router = APIRouter()

# In-memory swarm state store, keyed by swarm_id.
# Each entry holds the mutable state for one swarm run.
swarm_store: dict[str, dict] = {}

# Injected dependencies (set by main.py lifespan)
_event_bus: Any = None
_copilot_client: Any = None
_template_loader: TemplateLoader | None = None


def configure(event_bus: Any, copilot_client: Any = None, template_loader: TemplateLoader | None = None) -> None:
    """Inject dependencies. Called during app startup."""
    global _event_bus, _copilot_client, _template_loader
    _event_bus = event_bus
    _copilot_client = copilot_client
    _template_loader = template_loader


def _create_swarm_state(swarm_id: str, goal: str, template: str | None) -> dict:
    """Create initial swarm state and store it."""
    state = {
        "swarm_id": swarm_id,
        "goal": goal,
        "template": template,
        "phase": "starting",
        "tasks": [],
        "agents": [],
        "inbox_recent": [],
        "round_number": 0,
        "orchestrator": None,
    }
    swarm_store[swarm_id] = state
    return state


async def _run_swarm(swarm_id: str, goal: str, template_key: str | None = None) -> None:
    """Background task: create orchestrator and run the swarm."""
    from backend.swarm.orchestrator import SwarmOrchestrator

    if _event_bus is None:
        log.error("eventbus_not_configured")
        return

    loaded_template = None
    if template_key and _template_loader:
        try:
            loaded_template = _template_loader.load(template_key)
        except (FileNotFoundError, ValueError) as e:
            log.warning("template_load_failed", template=template_key, error=str(e))

    system_preamble = _template_loader.system_preamble if _template_loader else ""
    system_tools = _template_loader.system_tools if _template_loader else []
    work_base = Path("workdir")
    orch = SwarmOrchestrator(
        client=_copilot_client, event_bus=_event_bus,
        template=loaded_template, system_preamble=system_preamble,
        system_tools=system_tools,
        swarm_id=swarm_id, work_base=work_base,
    )
    swarm_store[swarm_id]["orchestrator"] = orch

    try:
        swarm_store[swarm_id]["phase"] = "planning"
        report = await orch.run(goal)
        swarm_store[swarm_id]["phase"] = "complete"
        swarm_store[swarm_id]["report"] = report
    except Exception as e:
        log.error("swarm_failed", swarm_id=swarm_id, error=str(e))
        swarm_store[swarm_id]["phase"] = "failed"


@router.post("/api/swarm/start")
async def start_swarm(request: SwarmStartRequest, background_tasks: BackgroundTasks) -> SwarmStartResponse:
    """Start a new swarm with the given goal."""
    swarm_id = str(uuid.uuid4())
    goal = (
        format_goal(request.template, request.goal)
        if request.template
        else request.goal
    )
    _create_swarm_state(swarm_id, goal, request.template)

    if _copilot_client is not None:
        background_tasks.add_task(_run_swarm, swarm_id, goal, request.template)

    return SwarmStartResponse(swarm_id=swarm_id, status="starting")


@router.get("/api/swarm/{swarm_id}/status")
async def get_swarm_status(swarm_id: str) -> SwarmStatusResponse:
    """Return current status of a swarm."""
    if swarm_id not in swarm_store:
        raise HTTPException(status_code=404, detail="Swarm not found")

    state = swarm_store[swarm_id]
    return SwarmStatusResponse(
        swarm_id=state["swarm_id"],
        phase=state["phase"],
        tasks=state["tasks"],
        agents=state["agents"],
        inbox_recent=state["inbox_recent"],
        round_number=state["round_number"],
    )


@router.post("/api/swarm/{swarm_id}/cancel")
async def cancel_swarm(swarm_id: str) -> dict:
    """Cancel a running swarm."""
    if swarm_id not in swarm_store:
        raise HTTPException(status_code=404, detail="Swarm not found")
    orch = swarm_store[swarm_id].get("orchestrator")
    if orch:
        await orch.cancel()
    swarm_store[swarm_id]["phase"] = "cancelled"
    return {"status": "cancelled"}


@router.get("/api/templates")
async def list_templates() -> dict:
    """Return available swarm templates."""
    if _template_loader:
        return {"templates": _template_loader.list_available()}
    return {"templates": _list_templates()}
