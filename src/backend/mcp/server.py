"""Swarm State MCP server — in-process, streamable HTTP transport.

Mounted on the FastAPI app at /mcp. Gives agent sessions tools to query
live swarm state and restart stuck agents.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from backend.mcp.deps import get_deps
from backend.swarm.models import SwarmState

mcp = FastMCP(
    "swarm-state",
    instructions="Query and manage swarm execution state.",
    # Disable DNS rebinding protection — this is an internal server
    # accessed by agent sessions on the same host.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    # Override default sub-path so mount at /mcp = endpoint at /mcp (not /mcp/mcp)
    streamable_http_path="/",
)

# Eagerly create the streamable HTTP app so the session manager is available
# for lifecycle management in main.py lifespan.
_streamable_app = mcp.streamable_http_app()


def get_session_manager():  # type: ignore[return-type]
    """Return the MCP session manager (created by streamable_http_app())."""
    mgr = mcp._session_manager
    if mgr is None:
        raise RuntimeError("MCP session manager not initialized. Call streamable_http_app() first.")
    return mgr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_swarm(swarm_id: str) -> SwarmState:
    """Return the typed SwarmState for the given swarm_id.

    Raises ToolError if the swarm is not found.
    """
    deps = get_deps()
    state = deps.swarm_store.get(swarm_id)
    if state is None:
        raise ToolError(f"Swarm '{swarm_id}' not found. Available: {list(deps.swarm_store.keys())}")
    return state


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_active_swarms() -> list[dict[str, str | None]]:
    """List all active swarms with their IDs, phase, goal, and template."""
    deps = get_deps()
    return [
        {
            "swarm_id": state["swarm_id"],
            "phase": state["phase"],
            "goal": state["goal"],
            "template": state["template"],
        }
        for state in list(deps.swarm_store.values())
    ]


@mcp.tool()
async def get_swarm_status(swarm_id: str) -> dict:
    """Get current swarm phase, round number, active agent count, and task counts."""
    state = _resolve_swarm(swarm_id)

    orch = state.get("orchestrator")
    if orch is None:
        return {"phase": state["phase"], "round_number": state["round_number"], "agent_count": 0, "task_counts": {}}

    agents = await orch.service.registry.get_all()
    tasks = await orch.service.task_board.get_tasks()

    task_counts: dict[str, int] = {}
    for t in tasks:
        status_val = t.status.value if hasattr(t.status, "value") else str(t.status)
        task_counts[status_val] = task_counts.get(status_val, 0) + 1

    return {
        "swarm_id": state["swarm_id"],
        "phase": state["phase"],
        "round_number": state["round_number"],
        "agent_count": len(agents),
        "task_counts": task_counts,
    }


@mcp.tool()
async def list_tasks(
    swarm_id: str,
    status: str | None = None,
    worker: str | None = None,
) -> list[dict]:
    """List all tasks, optionally filtered by status or worker name."""
    state = _resolve_swarm(swarm_id)

    orch = state.get("orchestrator")
    if orch is None:
        raise ToolError("Swarm has no orchestrator.")

    tasks = await orch.service.task_board.get_tasks(owner=worker)

    if status is not None:
        tasks = [t for t in tasks if t.status.value == status]

    return [t.to_dict() for t in tasks]


@mcp.tool()
async def get_task_detail(swarm_id: str, task_id: str) -> dict:
    """Get full detail for a specific task including result and timeline."""
    state = _resolve_swarm(swarm_id)

    orch = state.get("orchestrator")
    if orch is None:
        raise ToolError("Swarm has no orchestrator.")

    tasks = await orch.service.task_board.get_tasks()
    for t in tasks:
        if t.id == task_id:
            return t.to_dict()
    raise ToolError(f"Task '{task_id}' not found.")


@mcp.tool()
async def get_recent_events(
    swarm_id: str,
    count: int = 20,
    since: str | None = None,
) -> list[dict]:
    """Get recent swarm events. Requires database persistence."""
    deps = get_deps()

    if deps.repository is None:
        raise ToolError("Event history requires database persistence (DATABASE_URL).")

    state = _resolve_swarm(swarm_id)

    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise ToolError(f"Invalid datetime format: '{since}'. Use ISO 8601 (e.g. 2025-01-01T00:00:00).") from exc

    sid: str | UUID = state["swarm_id"]
    with contextlib.suppress(ValueError):
        sid = UUID(sid)
    events = await deps.repository.get_events(sid, since=since_dt)

    return events[-count:] if len(events) > count else events


@mcp.tool()
async def list_agents(swarm_id: str) -> list[dict]:
    """List all agents with their roles, status, and tasks completed."""
    state = _resolve_swarm(swarm_id)

    orch = state.get("orchestrator")
    if orch is None:
        raise ToolError("Swarm has no orchestrator.")

    agents = await orch.service.registry.get_all()
    return [
        {
            "name": a.name,
            "role": a.role,
            "display_name": a.display_name,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "tasks_completed": a.tasks_completed,
        }
        for a in agents
    ]


@mcp.tool()
async def list_artifacts(swarm_id: str) -> list[dict]:
    """List files created in the swarm work directory."""
    deps = get_deps()
    state = _resolve_swarm(swarm_id)

    swarm_dir = Path(deps.work_dir) / state["swarm_id"]
    if not swarm_dir.is_dir():
        return []

    artifacts = []
    for f in swarm_dir.rglob("*"):
        if f.is_file():
            artifacts.append(
                {
                    "name": f.name,
                    "path": str(f.relative_to(swarm_dir)),
                    "size": f.stat().st_size,
                }
            )
    return artifacts


@mcp.tool()
async def read_artifact(swarm_id: str, path: str) -> dict:
    """Read a file from the swarm work directory. Path is relative to the swarm dir."""
    deps = get_deps()
    state = _resolve_swarm(swarm_id)

    swarm_dir = Path(deps.work_dir) / state["swarm_id"]
    target = (swarm_dir / path).resolve()

    # Path traversal guard (is_relative_to avoids prefix collisions like /swarm-1evil)
    if not target.is_relative_to(swarm_dir.resolve()):
        raise ToolError("Path traversal not allowed.")

    if not target.is_file():
        raise ToolError(f"File not found: {path}")

    try:
        content = target.read_text()
    except UnicodeDecodeError as exc:
        raise ToolError(f"File '{path}' is not a text file and cannot be read as text") from exc

    return {"path": path, "content": content}


@mcp.tool()
async def resume_agent(swarm_id: str, agent_name: str, nudge: str = "") -> dict[str, object]:
    """Resume a failed agent's session, preserving its full conversation history.

    Sends a nudge message to guide the agent toward a different approach.
    Unlike restart (which creates a fresh session), resume keeps the agent's
    memory of what it already tried.
    """
    state = _resolve_swarm(swarm_id)

    orch = state.get("orchestrator")
    if orch is None:
        raise ToolError("Swarm has no orchestrator.")

    try:
        await orch.resume_agent(agent_name, nudge)
    except (KeyError, RuntimeError) as exc:
        raise ToolError(exc.args[0] if exc.args else str(exc)) from exc

    return {"ok": True, "agent_name": agent_name, "resumed": True}
