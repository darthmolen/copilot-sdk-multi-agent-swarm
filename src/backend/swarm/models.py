"""Pydantic models for the swarm coordination system."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    BLOCKED = "blocked"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class Task(BaseModel):
    id: str
    subject: str
    description: str
    worker_role: str
    worker_name: str
    status: TaskStatus = TaskStatus.PENDING
    blocked_by: list[str] = Field(default_factory=list)
    result: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "worker_role": self.worker_role,
            "worker_name": self.worker_name,
            "status": self.status.value,
            "blocked_by": self.blocked_by,
            "result": self.result,
        }


class AgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    READY = "ready"
    FAILED = "failed"


class AgentInfo(BaseModel):
    name: str
    role: str
    display_name: str = ""
    status: AgentStatus = AgentStatus.IDLE
    tasks_completed: int = 0


class InboxMessage(BaseModel):
    sender: str
    recipient: str
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class _SwarmStateRequired(TypedDict):
    """Required keys for swarm state."""

    swarm_id: str
    goal: str
    template: str | None
    phase: str
    round_number: int


class SwarmState(_SwarmStateRequired, total=False):
    """In-memory swarm state stored in swarm_store.

    Uses TypedDict (not Pydantic) because it holds a live SwarmOrchestrator
    reference that isn't serializable.
    """

    orchestrator: Any  # SwarmOrchestrator — can't import here (circular)
    report: str | None
    error: str | None
