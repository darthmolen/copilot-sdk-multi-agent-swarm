"""REST API endpoints for swarm management."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import shutil

import structlog
import yaml

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

from backend.api.schemas import (
    CreateTemplateRequest,
    SwarmStartRequest,
    SwarmStartResponse,
    SwarmStatusResponse,
    UpdateTemplateFileRequest,
)
from backend.swarm.template_validator import validate_template_file
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


@router.get("/api/templates/{key}")
async def get_template_details(key: str) -> dict:
    """Return full template: metadata + list of files with content."""
    templates_dir = Path("src/templates") / key
    if not templates_dir.is_dir():
        raise HTTPException(status_code=404, detail="Template not found")

    files = []
    for f in sorted(templates_dir.iterdir()):
        if f.is_file():
            files.append({
                "filename": f.name,
                "content": f.read_text(encoding="utf-8"),
            })

    # Read metadata from _template.yaml
    meta_file = templates_dir / "_template.yaml"
    meta: dict = {}
    if meta_file.is_file():
        text = meta_file.read_text(encoding="utf-8")
        # Parse frontmatter
        lines = text.split("\n")
        if lines[0].strip() == "---":
            close_idx = next(
                (i for i in range(1, len(lines)) if lines[i].strip() == "---"),
                None,
            )
            if close_idx:
                meta = yaml.safe_load("\n".join(lines[1:close_idx])) or {}

    return {
        "key": key,
        "name": meta.get("name", key),
        "description": meta.get("description", ""),
        "files": files,
    }


@router.put("/api/templates/{key}/files/{filename}")
async def update_template_file(
    key: str, filename: str, request: UpdateTemplateFileRequest,
) -> dict:
    """Update a template file. Validates before saving. Returns 422 if invalid."""
    templates_dir = Path("src/templates") / key
    if not templates_dir.is_dir():
        raise HTTPException(status_code=404, detail="Template not found")

    content = request.content
    result = validate_template_file(filename, content)

    if not result.valid:
        return JSONResponse(
            status_code=422,
            content={
                "errors": [
                    {"message": e.message, "line": e.line} for e in result.errors
                ],
            },
        )

    file_path = templates_dir / filename
    file_path.write_text(content, encoding="utf-8")
    return {"valid": True, "filename": filename}


@router.post("/api/templates", status_code=201)
async def create_template(request: CreateTemplateRequest) -> dict:
    """Create a new template with scaffolded files."""
    key = request.key
    name = request.name or key
    description = request.description

    if not key:
        raise HTTPException(status_code=400, detail="key is required")

    templates_dir = Path("src/templates") / key
    if templates_dir.exists():
        raise HTTPException(status_code=409, detail="Template already exists")

    templates_dir.mkdir(parents=True)

    # Scaffold files
    (templates_dir / "_template.yaml").write_text(
        f"---\nkey: {key}\nname: {name}\ndescription: {description}\n"
        f'goal_template: "{{user_input}}"\n---\n',
        encoding="utf-8",
    )
    (templates_dir / "leader.md").write_text(
        "---\nname: leader\n---\n\nYou are the leader agent. Decompose the goal into tasks.\n",
        encoding="utf-8",
    )
    (templates_dir / "synthesis.md").write_text(
        "---\nname: synthesis\n---\n\nSynthesize the results into a comprehensive report.\n",
        encoding="utf-8",
    )
    (templates_dir / "worker-default.md").write_text(
        "---\nname: default-worker\ndisplayName: Default Worker\n"
        "description: A general-purpose worker\n---\n\n"
        "Complete the assigned task thoroughly.\n",
        encoding="utf-8",
    )

    return {"key": key, "name": name, "description": description}


@router.delete("/api/templates/{key}")
async def delete_template(key: str) -> dict:
    """Delete a template directory."""
    templates_dir = Path("src/templates") / key
    if not templates_dir.is_dir():
        raise HTTPException(status_code=404, detail="Template not found")

    shutil.rmtree(templates_dir)
    return {"deleted": True, "key": key}
