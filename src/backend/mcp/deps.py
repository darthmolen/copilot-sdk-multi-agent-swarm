"""MCP server dependency holder — same pattern as rest.py configure()."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.swarm.models import SwarmState

if TYPE_CHECKING:
    from backend.db.repository import SwarmRepository
    from backend.events import EventBus
    from backend.swarm.template_loader import TemplateLoader

StartSwarmFn = Callable[[str, str, str | None], Coroutine[None, None, None]]


@dataclass
class MCPDeps:
    swarm_store: dict[str, SwarmState] = field(default_factory=dict)
    work_dir: str = "workdir"
    event_bus: EventBus | None = None
    repository: SwarmRepository | None = None
    template_loader: TemplateLoader | None = None
    start_swarm: StartSwarmFn | None = None


_deps: MCPDeps | None = None


def configure(
    swarm_store: dict[str, SwarmState],
    work_dir: str,
    event_bus: EventBus | None = None,
    repository: SwarmRepository | None = None,
    template_loader: TemplateLoader | None = None,
    start_swarm: StartSwarmFn | None = None,
) -> None:
    """Inject dependencies. Called during app startup."""
    global _deps
    _deps = MCPDeps(
        swarm_store=swarm_store,
        work_dir=work_dir,
        event_bus=event_bus,
        repository=repository,
        template_loader=template_loader,
        start_swarm=start_swarm,
    )


def get_deps() -> MCPDeps:
    """Return the configured deps or raise if not yet configured."""
    if _deps is None:
        raise RuntimeError("MCP deps not configured. Call configure() during app startup.")
    return _deps
