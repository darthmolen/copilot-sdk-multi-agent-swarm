"""REST API endpoints for swarm management."""

from __future__ import annotations

import asyncio
import io
import uuid
import zipfile
from pathlib import Path
from typing import Any

import shutil

import structlog
import yaml

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from backend.api.schemas import (
    AgentSummary,
    ChatRequest,
    CreateTemplateRequest,
    EnsureReportRequest,
    SwarmStartRequest,
    SwarmStartResponse,
    SwarmStatusResponse,
    TaskSummary,
    UpdateTemplateFileRequest,
)
from backend.swarm.models import SwarmState
from backend.swarm.template_validator import validate_template_file
from backend.swarm.template_loader import TemplateLoader
from backend.swarm.templates import format_goal
from backend.swarm.templates import list_templates as _list_templates

log = structlog.get_logger()

router = APIRouter()

# In-memory swarm state store, keyed by swarm_id.
# Each entry holds the mutable state for one swarm run.
swarm_store: dict[str, SwarmState] = {}

# Injected dependencies (set by main.py lifespan)
_event_bus: Any = None
_copilot_client: Any = None
_client_factory: Any = None
_repository: Any = None
_template_loader: TemplateLoader | None = None


def _get_work_dir() -> str:
    """Lazy import to avoid circular dependency with main.py."""
    from backend.main import SWARM_WORK_DIR
    return SWARM_WORK_DIR


def configure(
    event_bus: Any,
    copilot_client: Any = None,
    template_loader: TemplateLoader | None = None,
    client_factory: Any = None,
    repository: Any = None,
) -> None:
    """Inject dependencies. Called during app startup."""
    global _event_bus, _copilot_client, _template_loader, _client_factory, _repository
    _event_bus = event_bus
    _copilot_client = copilot_client
    _template_loader = template_loader
    _client_factory = client_factory
    _repository = repository


def _create_swarm_state(swarm_id: str, goal: str, template: str | None) -> SwarmState:
    """Create initial swarm state and store it."""
    state: SwarmState = {
        "swarm_id": swarm_id,
        "goal": goal,
        "template": template,
        "phase": "starting",
        "round_number": 0,
    }
    swarm_store[swarm_id] = state
    return state


async def _run_swarm(swarm_id: str, goal: str, template_key: str | None = None) -> None:
    """Background task: create orchestrator and run the swarm."""
    from backend.swarm.orchestrator import SwarmOrchestrator

    log.info("swarm_task_started", swarm_id=swarm_id, template=template_key,
             goal_len=len(goal))

    if _event_bus is None:
        log.error("eventbus_not_configured", swarm_id=swarm_id)
        return

    if _copilot_client is None:
        error_msg = (
            "Copilot SDK client is not available. "
            "Install the github-copilot-sdk package and ensure the CLI binary is on PATH."
        )
        log.error("swarm_no_client", swarm_id=swarm_id, error=error_msg)
        swarm_store[swarm_id]["phase"] = "failed"
        await _event_bus.emit("swarm.error", {
            "message": error_msg, "swarm_id": swarm_id,
        })
        await _event_bus.emit("swarm.phase_changed", {
            "phase": "failed", "swarm_id": swarm_id,
        })
        return

    loaded_template = None
    if template_key and _template_loader:
        try:
            loaded_template = _template_loader.load(template_key)
            log.info("swarm_template_loaded", swarm_id=swarm_id,
                     template=template_key,
                     workers=len(loaded_template.agents),
                     skills=len(loaded_template.all_skill_names),
                     has_mcp=loaded_template.mcp_servers is not None)
        except (FileNotFoundError, ValueError) as e:
            log.warning("template_load_failed", swarm_id=swarm_id,
                        template=template_key, error=str(e))

    system_preamble = _template_loader.system_preamble if _template_loader else ""
    system_tools = _template_loader.system_tools if _template_loader else []
    from backend.main import SWARM_TASK_TIMEOUT, SWARM_MAX_ROUNDS, SWARM_MODEL, SWARM_WORK_DIR

    work_base = Path(SWARM_WORK_DIR)
    config = {"max_rounds": SWARM_MAX_ROUNDS, "timeout": SWARM_TASK_TIMEOUT}
    log.info("swarm_config", swarm_id=swarm_id, model=SWARM_MODEL,
             max_rounds=SWARM_MAX_ROUNDS, timeout=SWARM_TASK_TIMEOUT)

    # Create SwarmService with optional repo for persistence
    from backend.services.swarm_service import SwarmService
    service = SwarmService(repo=_repository) if _repository else SwarmService()
    await service.create_swarm(swarm_id, goal=goal, template_key=template_key)

    orch = SwarmOrchestrator(
        client=_copilot_client, event_bus=_event_bus,
        config=config,
        template=loaded_template, system_preamble=system_preamble,
        system_tools=system_tools,
        swarm_id=swarm_id, work_base=work_base,
        model=SWARM_MODEL,
        client_factory=_client_factory,
        service=service,
    )
    swarm_store[swarm_id]["orchestrator"] = orch

    try:
        effective_goal = goal

        # Q&A phase: leader interviews user before planning
        if loaded_template and loaded_template.qa_enabled:
            log.info("swarm_qa_starting", swarm_id=swarm_id)
            swarm_store[swarm_id]["phase"] = "qa"
            effective_goal = await orch.start_qa(goal)
            log.info("swarm_qa_complete", swarm_id=swarm_id,
                     refined_goal_len=len(effective_goal))

        swarm_store[swarm_id]["phase"] = "planning"
        log.info("swarm_run_starting", swarm_id=swarm_id)
        report = await orch.run(effective_goal)
        swarm_store[swarm_id]["phase"] = "complete"
        swarm_store[swarm_id]["report"] = report
        log.info("swarm_run_complete", swarm_id=swarm_id,
                 report_len=len(report) if report else 0)
    except Exception as e:
        log.error("swarm_failed", swarm_id=swarm_id, error=str(e),
                  exc_info=True)
        swarm_store[swarm_id]["phase"] = "failed"
        await _event_bus.emit("swarm.phase_changed", {
            "phase": "failed", "swarm_id": swarm_id,
        })


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
    orch = state.get("orchestrator")

    tasks: list[TaskSummary] = []
    agents: list[AgentSummary] = []

    if orch is not None:
        live_tasks = await orch.service.task_board.get_tasks()
        tasks = [TaskSummary(**t.to_dict()) for t in live_tasks]
        live_agents = await orch.service.registry.get_all()
        agents = [
            AgentSummary(
                name=a.name, role=a.role, display_name=a.display_name,
                status=a.status.value, tasks_completed=a.tasks_completed,
            )
            for a in live_agents
        ]

    return SwarmStatusResponse(
        swarm_id=state["swarm_id"],
        phase=state["phase"],
        tasks=tasks,
        agents=agents,
        inbox_recent=[],
        round_number=state.get("round_number", 0),
        report=state.get("report"),
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


@router.post("/api/swarm/{swarm_id}/chat")
async def chat_with_swarm(
    swarm_id: str, request: ChatRequest, background_tasks: BackgroundTasks,
) -> dict:
    """Send a chat message to a swarm's synthesis agent.

    Works for both live swarms in memory and past sessions that can be
    resumed via the SDK's resume_session (session ID is deterministic:
    ``synth-{swarm_id}``).
    """
    log.info("chat_request_received", swarm_id=swarm_id, message_length=len(request.message))
    orch = None

    is_qa = False
    if swarm_id in swarm_store:
        state = swarm_store[swarm_id]
        phase = state["phase"]
        if phase == "qa":
            is_qa = True
            orch = state.get("orchestrator")
        elif phase == "complete":
            orch = state.get("orchestrator")
        else:
            raise HTTPException(status_code=409, detail="Swarm not yet complete")

    # Q&A phase: route to qa_chat
    if is_qa and orch and getattr(orch, "qa_session", None):
        background_tasks.add_task(orch.qa_chat, request.message)
        return {"status": "streaming"}

    # Create a lightweight orchestrator on-the-fly for past sessions
    if not orch or not getattr(orch, "synthesis_session_id", None):
        if _copilot_client is None or _event_bus is None:
            raise HTTPException(status_code=400, detail="No synthesis session available")
        log.info("chat_creating_on_the_fly", swarm_id=swarm_id,
                 session_id=f"synth-{swarm_id}")
        from backend.swarm.orchestrator import SwarmOrchestrator
        orch = SwarmOrchestrator(
            client=_copilot_client, event_bus=_event_bus, swarm_id=swarm_id,
        )
        orch.synthesis_session_id = f"synth-{swarm_id}"
        # Cache it so subsequent messages reuse the same orchestrator
        if swarm_id not in swarm_store:
            _create_swarm_state(swarm_id, "(resumed)", None)
            swarm_store[swarm_id]["phase"] = "complete"
        swarm_store[swarm_id]["orchestrator"] = orch

    background_tasks.add_task(orch.chat, request.message, active_file=request.active_file)
    return {"status": "streaming"}


@router.get("/api/swarm/{swarm_id}/files")
async def list_swarm_files(swarm_id: str) -> dict:
    """List files in a swarm's work directory."""
    work_dir = Path(_get_work_dir()) / swarm_id
    if not work_dir.is_dir():
        return {"files": []}
    files = []
    for f in sorted(work_dir.rglob("*")):
        if f.is_file():
            files.append({
                "name": f.name,
                "path": str(f.relative_to(work_dir)),
                "size": f.stat().st_size,
            })
    return {"files": files}


@router.get("/api/swarm/{swarm_id}/files/download-zip")
async def download_swarm_zip(swarm_id: str) -> StreamingResponse:
    """Download all files in a swarm's work directory as a ZIP archive."""
    base = Path(_get_work_dir()).resolve()
    work_dir = Path(_get_work_dir()) / swarm_id

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if work_dir.is_dir():
            for f in sorted(work_dir.rglob("*")):
                if not f.is_file():
                    continue
                # Path traversal protection: skip files that resolve outside workdir
                resolved = f.resolve()
                if not str(resolved).startswith(str(base)):
                    continue
                arcname = str(f.relative_to(work_dir))
                zf.write(f, arcname)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{swarm_id}.zip"',
        },
    )


@router.get("/api/swarm/{swarm_id}/files/{file_path:path}")
async def get_swarm_file(swarm_id: str, file_path: str) -> dict:
    """Read a file from a swarm's work directory."""
    base = Path(_get_work_dir()).resolve()
    target = (Path(_get_work_dir()) / swarm_id / file_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": target.read_text(encoding="utf-8", errors="replace")}


@router.post("/api/swarm/{swarm_id}/files/ensure-report")
async def ensure_report(swarm_id: str, request: EnsureReportRequest) -> dict:
    """Ensure the synthesis report file exists in the workdir, creating it from localStorage if needed."""
    work_dir = Path(_get_work_dir()) / swarm_id
    work_dir.mkdir(parents=True, exist_ok=True)
    report_path = work_dir / "synthesis_report.md"
    created = False
    if not report_path.exists():
        report_path.write_text(request.report, encoding="utf-8")
        created = True
    return {"created": created, "path": "synthesis_report.md"}


def _safe_template_path(key: str) -> Path:
    """Resolve a template key to a safe directory path. Raises 403 on traversal."""
    from backend.main import TEMPLATES_DIR

    base = Path(TEMPLATES_DIR).resolve()
    target = (Path(TEMPLATES_DIR) / key).resolve()
    if not str(target).startswith(str(base) + "/") and target != base:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    return target


def _safe_template_file_path(key: str, filename: str) -> Path:
    """Resolve a template file path safely. Raises 403 on traversal."""
    template_dir = _safe_template_path(key)
    base = template_dir.resolve()
    target = (template_dir / filename).resolve()
    if not str(target).startswith(str(base) + "/") and target != base:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    return target


@router.get("/api/templates")
async def list_templates() -> dict:
    """Return available swarm templates."""
    if _template_loader:
        return {"templates": _template_loader.list_available()}
    return {"templates": _list_templates()}


@router.get("/api/templates/{key}")
async def get_template_details(key: str) -> dict:
    """Return full template: metadata + list of files with content."""
    templates_dir = _safe_template_path(key)
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
    templates_dir = _safe_template_path(key)
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

    file_path = _safe_template_file_path(key, filename)
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

    # Reject keys with path separators or traversal components
    if "/" in key or "\\" in key or ".." in key:
        raise HTTPException(status_code=400, detail="Invalid template key")

    templates_dir = _safe_template_path(key)
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
    templates_dir = _safe_template_path(key)
    if not templates_dir.is_dir():
        raise HTTPException(status_code=404, detail="Template not found")

    shutil.rmtree(templates_dir)
    return {"deleted": True, "key": key}


@router.post("/api/templates/deploy", status_code=201)
async def deploy_template_zip(file: UploadFile) -> dict:
    """Deploy a template pack from a zip file.

    Validates structure, checks for zipslip, enforces size limit,
    and validates frontmatter before extracting.
    """
    from backend.main import SWARM_MAX_TEMPLATE_ZIP_SIZE
    from backend.swarm.template_validator import validate_template_file

    # Size check (compressed)
    contents = await file.read()
    if len(contents) > SWARM_MAX_TEMPLATE_ZIP_SIZE:
        raise HTTPException(status_code=413, detail="Zip file exceeds size limit")

    try:
        zf = zipfile.ZipFile(io.BytesIO(contents))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")

    # Uncompressed size + file count limits
    max_uncompressed = SWARM_MAX_TEMPLATE_ZIP_SIZE * 10  # 30MB default
    max_members = 200
    total_uncompressed = sum(info.file_size for info in zf.infolist())
    if total_uncompressed > max_uncompressed:
        raise HTTPException(status_code=413, detail="Zip uncompressed size exceeds limit")
    if len(zf.namelist()) > max_members:
        raise HTTPException(status_code=413, detail="Zip contains too many files")

    # Zipslip protection + find _template.yaml at root level only
    template_yaml_path = None
    for name in zf.namelist():
        # Reject path traversal: .., absolute paths (Unix and Windows)
        if ".." in name or name.startswith("/") or name.startswith("\\"):
            raise HTTPException(status_code=400, detail="Path traversal detected in zip")
        if Path(name).is_absolute():
            raise HTTPException(status_code=400, detail="Path traversal detected in zip")
        # Only accept _template.yaml at exactly one level deep: {root}/_template.yaml
        parts = name.split("/")
        if len(parts) == 2 and parts[1] == "_template.yaml":
            template_yaml_path = name

    if not template_yaml_path:
        raise HTTPException(status_code=400, detail="Zip must contain {key}/_template.yaml at root level")

    # Parse _template.yaml to get key
    meta_content = zf.read(template_yaml_path).decode("utf-8")
    # Parse frontmatter (may have --- delimiters)
    lines = meta_content.split("\n")
    if lines[0].strip() == "---":
        close_idx = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if close_idx is not None:
            meta = yaml.safe_load("\n".join(lines[1:close_idx])) or {}
        else:
            meta = yaml.safe_load(meta_content) or {}
    else:
        meta = yaml.safe_load(meta_content) or {}

    if "key" not in meta:
        raise HTTPException(status_code=400, detail="_template.yaml missing 'key' field")

    template_key = meta["key"]

    # Verify directory name matches key
    zip_root = template_yaml_path.split("/")[0]
    if zip_root != template_key:
        raise HTTPException(
            status_code=400,
            detail=f"Zip directory '{zip_root}' does not match template key '{template_key}'",
        )

    # Reject keys with path separators
    if "/" in template_key or "\\" in template_key or ".." in template_key:
        raise HTTPException(status_code=400, detail="Invalid template key")

    # Validate _template.yaml itself
    result = validate_template_file("_template.yaml", meta_content)
    if not result.valid:
        raise HTTPException(
            status_code=422,
            detail=f"Validation failed for _template.yaml: {result.errors[0].message}",
        )

    # Validate frontmatter on .md files
    for name in zf.namelist():
        if name.endswith(".md"):
            filename = name.split("/")[-1]
            content = zf.read(name).decode("utf-8")
            result = validate_template_file(filename, content)
            if not result.valid:
                raise HTTPException(
                    status_code=422,
                    detail=f"Validation failed for {filename}: {result.errors[0].message}",
                )

    # Extract to templates directory
    target = _safe_template_path(template_key)
    if target.exists():
        shutil.rmtree(target)

    target.mkdir(parents=True)
    for name in zf.namelist():
        if name.endswith("/"):
            continue  # skip directories
        # Strip the root directory prefix
        relative = name[len(zip_root) + 1:]
        if not relative:
            continue
        # Final safety: ensure relative path stays within target
        dest = (target / relative).resolve()
        if not str(dest).startswith(str(target.resolve())):
            continue  # skip files that would escape target
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(name))

    return {
        "key": template_key,
        "name": meta.get("name", template_key),
        "description": meta.get("description", ""),
    }


# ---------------------------------------------------------------------------
# Event replay + Swarm list (requires persistence)
# ---------------------------------------------------------------------------


@router.get("/api/swarm/{swarm_id}/events")
async def get_swarm_events(swarm_id: uuid.UUID, since: str | None = None):
    """Return event log for replay. Requires DATABASE_URL configured."""
    if _repository is None:
        return JSONResponse({"error": "Persistence not configured"}, status_code=404)
    from datetime import datetime

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format")
    from fastapi.encoders import jsonable_encoder

    events = await _repository.get_events(swarm_id, since=since_dt)
    return {"events": jsonable_encoder(events)}


@router.get("/api/swarms")
async def list_swarms():
    """Return all swarms from DB. Requires DATABASE_URL configured."""
    if _repository is None:
        return JSONResponse({"error": "Persistence not configured"}, status_code=404)
    from fastapi.encoders import jsonable_encoder

    swarms = await _repository.list_swarms()
    return {"swarms": jsonable_encoder(swarms)}
