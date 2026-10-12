"""
LoggingSDK Implementation.

Wraps structlog to inject execution correlation into every log line.
"""

from __future__ import annotations

from typing import Any

from core.observability.logging import get_logger


class LoggingSDKImpl:
    """Concrete implementation of LoggingSDK."""

    def __init__(
        self,
        agent_slug: str,
        execution_id: str,
        task_id: str,
        organization_id: str,
    ) -> None:
        self._logger = get_logger(f"agent.{agent_slug}").bind(
            execution_id=execution_id,
            task_id=task_id,
            organization_id=organization_id,
            agent_slug=agent_slug,
        )

    def debug(self, event: str, **fields: Any) -> None:
        self._logger.debug(event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._logger.info(event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._logger.warning(event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._logger.error(event, **fields)