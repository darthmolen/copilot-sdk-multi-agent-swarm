"""Pydantic request/response schemas for the swarm API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SwarmStartRequest(BaseModel):
    goal: str
    template: str | None = None


class SwarmStartResponse(BaseModel):
    swarm_id: str
    status: str = "starting"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    active_file: str | None = None


class EnsureReportRequest(BaseModel):
    report: str = Field(..., min_length=1)


class TaskSummary(BaseModel):
    id: str
    subject: str
    description: str
    worker_role: str
    worker_name: str
    status: str
    blocked_by: list[str] = Field(default_factory=list)
    result: str = ""


class AgentSummary(BaseModel):
    name: str
    role: str
    display_name: str
    status: str
    tasks_completed: int = 0


class SwarmStatusResponse(BaseModel):
    swarm_id: str
    phase: str
    tasks: list[TaskSummary]
    agents: list[AgentSummary]
    inbox_recent: list[dict]
    round_number: int
    report: str | None = None


class UpdateTemplateFileRequest(BaseModel):
    content: str


class CreateTemplateRequest(BaseModel):
    key: str
    name: str = ""
    description: str = ""
