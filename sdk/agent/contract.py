"""
DSRT Agent Contract v1 (C1 §9).

Every DSRT Agent MUST implement this Protocol. The Core will only load,
initialize, execute, cancel, and health-check agents that conform.

Any change to this file is a BREAKING contract change and requires
incrementing AGENT_CONTRACT_VERSION.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from schemas.domain import AgentIdentity, AgentManifest
from sdk.agent.sdk import DSRTAgentSDK


# --- Initialization ---

@dataclass(frozen=True)
class AgentInitializationRequest:
    """Passed to Agent.initialize()."""

    execution_id: str
    task_id: str
    organization_id: str
    agent_version_id: str
    sdk_version: str
    contract_version: str


@dataclass(frozen=True)
class AgentInitializationResult:
    """Returned from Agent.initialize()."""

    status: str = "READY"  # "READY" | "FAILED"
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# --- Execution ---

@dataclass(frozen=True)
class AgentExecutionRequest:
    """Passed to Agent.execute()."""

    execution_id: str
    task_id: str
    objective: str
    input_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentExecutionResult:
    """Returned from Agent.execute()."""

    status: str = "COMPLETED"  # "COMPLETED" | "FAILED" | "CANCELLED"
    result_summary: dict[str, Any] = field(default_factory=dict)
    artifacts_created: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# --- Health ---

@dataclass(frozen=True)
class AgentHealth:
    """Returned from Agent.health()."""

    status: str = "healthy"  # "healthy" | "degraded" | "unhealthy"
    details: dict[str, Any] = field(default_factory=dict)


# --- The Contract Protocol ---

class DSRTAgent(Protocol):
    """DSRT Agent Contract v1 (C1 §9).

    Every agent implementation MUST expose:
      - identity: AgentIdentity (immutable)
      - manifest: AgentManifest (immutable for this version)
      - initialize(sdk, request) → AgentInitializationResult
      - execute(request) → AgentExecutionResult
      - cancel() → None
      - health() → AgentHealth
    """

    identity: AgentIdentity
    manifest: AgentManifest

    async def initialize(
        self,
        sdk: DSRTAgentSDK,
        request: AgentInitializationRequest,
    ) -> AgentInitializationResult:
        """Initialize the agent with the injected SDK."""
        ...

    async def execute(
        self, request: AgentExecutionRequest,
    ) -> AgentExecutionResult:
        """Execute the professional intelligence workflow."""
        ...

    async def cancel(self) -> None:
        """Gracefully handle a cancellation signal."""
        ...

    async def health(self) -> AgentHealth:
        """Report agent operational health."""
        ...