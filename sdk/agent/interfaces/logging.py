"""
Logging SDK Contract (C1 §17).

Agents log through Core's structured logger to preserve trajectory correlation.
"""

from __future__ import annotations

from typing import Any, Protocol


class LoggingSDK(Protocol):
    """Logging SDK — structured, correlated logging."""

    def debug(self, event: str, **fields: Any) -> None: ...
    def info(self, event: str, **fields: Any) -> None: ...
    def warning(self, event: str, **fields: Any) -> None: ...
    def error(self, event: str, **fields: Any) -> None: ...