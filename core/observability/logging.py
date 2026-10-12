"""
DSRT Core Structured Logging

Every DSRT log entry is structured with execution context.
Natural-language log scraping should never be required.
"""

from __future__ import annotations

import logging

import structlog

from core.config import get_settings


_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def _resolve_level(name: str) -> int:
    """Resolve a level name to a numeric logging level."""
    return _LOG_LEVELS.get(name.upper(), logging.INFO)


def setup_logging() -> None:
    """Configure structured logging for DSRT Core."""
    settings = get_settings()
    level = _resolve_level(settings.log_level)

    # Configure stdlib logging so uvicorn/fastapi logs are also captured.
    logging.basicConfig(
        format="%(message)s",
        level=level,
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger with the given name."""
    return structlog.get_logger(name)