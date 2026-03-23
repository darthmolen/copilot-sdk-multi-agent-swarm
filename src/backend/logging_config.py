"""Centralized structured logging configuration using structlog."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def configure_logging(
    json_file: Path | None = None,
    level: str = "INFO",
) -> None:
    """Configure structlog for the application.

    - Console: colored dev-friendly output
    - File (optional): JSON lines for machine parsing
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging (structlog wraps it)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler: dev-friendly
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=True),
        foreign_pre_chain=shared_processors,
    ))
    root.addHandler(console)

    # File handler: JSON lines
    if json_file:
        json_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(json_file, mode="a")
        file_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        ))
        root.addHandler(file_handler)
