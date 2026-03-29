"""Swarm configuration with validated defaults."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class SwarmConfig(BaseModel):
    """Configuration for a swarm run."""

    model: str = os.environ.get("SWARM_MODEL", "gemini-3-pro-preview")
    max_rounds: int = 3
    timeout: float = 1800.0
    max_workers: int = 5
