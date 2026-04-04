"""MCP server dependency holder — same pattern as rest.py configure()."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPDeps:
    swarm_store: dict[str, dict] = field(default_factory=dict)
    work_dir: str = "workdir"
    event_bus: Any = None
    repository: Any = None  # SwarmRepository, optional


_deps: MCPDeps | None = None


def configure(
    swarm_store: dict[str, dict],
    work_dir: str,
    event_bus: Any = None,
    repository: Any = None,
) -> None:
    """Inject dependencies. Called during app startup."""
    global _deps
    _deps = MCPDeps(
        swarm_store=swarm_store,
        work_dir=work_dir,
        event_bus=event_bus,
        repository=repository,
    )


def get_deps() -> MCPDeps:
    """Return the configured deps or raise if not yet configured."""
    if _deps is None:
        raise RuntimeError("MCP deps not configured. Call configure() during app startup.")
    return _deps
