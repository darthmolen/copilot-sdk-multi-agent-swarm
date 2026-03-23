"""Swarm configuration with validated defaults."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SwarmConfig(BaseModel):
    """Configuration for a swarm run."""

    model: str = "claude-sonnet-4-6"
    max_rounds: int = 3
    timeout: float = 300.0
    max_workers: int = 5
