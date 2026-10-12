"""
ModelGateway SDK Contract (C1 §18-19).

Agents request reasoning; Core decides which provider/model handles it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKModelRequest:
    """Canonical model request — provider-neutral (C1 §19)."""

    purpose: str
    messages: list[dict[str, Any]]
    system_context: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    response_schema: dict[str, Any] | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SDKModelUsage:
    """Model usage accounting."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class SDKModelResponse:
    """Canonical model response."""

    output: str | None
    structured_output: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "completed"
    usage: SDKModelUsage = field(default_factory=SDKModelUsage)
    model_identifier: str = "abstract"
    latency_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelSDK(Protocol):
    """Model Gateway SDK — the reasoning capability."""

    async def generate(self, request: SDKModelRequest) -> SDKModelResponse:
        """Request model reasoning."""
        ...