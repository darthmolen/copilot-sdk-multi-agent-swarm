"""Tests for structured logging configuration."""

import json
from pathlib import Path

import structlog

from backend.logging_config import configure_logging


def test_configure_logging_creates_working_logger(tmp_path: Path) -> None:
    """After configure_logging, structlog.get_logger() works."""
    configure_logging(json_file=tmp_path / "test.log")
    log = structlog.get_logger("test")
    log.info("hello", key="value")

    # Verify JSON file has content
    content = (tmp_path / "test.log").read_text()
    assert len(content) > 0
    line = json.loads(content.strip().split("\n")[-1])
    assert line["event"] == "hello"
    assert line["key"] == "value"
    assert "timestamp" in line
    assert "level" in line


def test_bound_context_propagates(tmp_path: Path) -> None:
    """Bound context appears in log output."""
    configure_logging(json_file=tmp_path / "test.log")
    log = structlog.get_logger("test").bind(swarm_id="sw-123", agent="researcher")
    log.info("task_started", task_id="t-1")

    content = (tmp_path / "test.log").read_text()
    line = json.loads(content.strip().split("\n")[-1])
    assert line["swarm_id"] == "sw-123"
    assert line["agent"] == "researcher"
    assert line["task_id"] == "t-1"


def test_configure_logging_without_file() -> None:
    """configure_logging works without json_file (console only)."""
    configure_logging()  # No file -- should not error
    log = structlog.get_logger("test")
    log.info("console_only")  # Should not raise
