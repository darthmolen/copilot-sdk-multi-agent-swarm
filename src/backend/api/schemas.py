"""Pydantic request/response schemas for the swarm API."""

from __future__ import annotations

from pydantic import BaseModel


class SwarmStartRequest(BaseModel):
    goal: str
    template: str | None = None


class SwarmStartResponse(BaseModel):
    swarm_id: str
    status: str = "starting"


class SwarmStatusResponse(BaseModel):
    swarm_id: str
    phase: str
    tasks: list[dict]
    agents: list[dict]
    inbox_recent: list[dict]
    round_number: int


class UpdateTemplateFileRequest(BaseModel):
    content: str


class CreateTemplateRequest(BaseModel):
    key: str
    name: str = ""
    description: str = ""
