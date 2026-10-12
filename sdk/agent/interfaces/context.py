"""
Context SDK Contract (C1 §22).

Agents receive structured context; not arbitrary prompt strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKAgentContext:
    """Structured execution context (C1 §22)."""

    # Identity block
    execution_id: str
    task_id: str
    organization_id: str
    user_id: str

    # Agent
    agent_slug: str
    agent_version: str

    # Objective
    objective: str
    input_payload: dict[str, Any] = field(default_factory=dict)

    # Working state
    working_state: dict[str, Any] = field(default_factory=dict)

    # Constraints & resources
    constraints: dict[str, Any] = field(default_factory=dict)
    resource_limits: dict[str, Any] = field(default_factory=dict)

    # Future-phase placeholders (C4/C5/C6)
    relevant_memory: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    # Fingerprint for reproducibility
    configuration_hash: str = ""


class ContextSDK(Protocol):
    """Context SDK — structured execution context accessor."""

    async def get(self) -> SDKAgentContext:
        """Fetch the current structured context."""
        ...

    async def update_state(self, patch: dict[str, Any]) -> None:
        """Update agent working state (Core-controlled persistence)."""
        ...