"""REST API endpoints for swarm management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    SwarmStartRequest,
    SwarmStartResponse,
    SwarmStatusResponse,
)

router = APIRouter()

# In-memory swarm state store, keyed by swarm_id.
# Each entry holds the mutable state for one swarm run.
swarm_store: dict[str, dict] = {}

TEMPLATES = {
    "research": {
        "name": "research",
        "description": "Research and analysis team",
        "roles": ["researcher", "analyst", "writer"],
    },
    "coding": {
        "name": "coding",
        "description": "Software development team",
        "roles": ["architect", "developer", "reviewer"],
    },
    "content": {
        "name": "content",
        "description": "Content creation team",
        "roles": ["strategist", "writer", "editor"],
    },
}


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
    }
    swarm_store[swarm_id] = state
    return state


@router.post("/api/swarm/start")
async def start_swarm(request: SwarmStartRequest) -> SwarmStartResponse:
    """Start a new swarm with the given goal."""
    swarm_id = str(uuid.uuid4())
    _create_swarm_state(swarm_id, request.goal, request.template)
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


@router.get("/api/templates")
async def list_templates() -> dict:
    """Return available swarm templates."""
    return {"templates": list(TEMPLATES.values())}
