"""
Orchestration SDK Contract (C5 §6, §40).

The agent-facing interface for orchestration capabilities.
Agents use this to delegate, manage state, request replans,
and interact with the orchestration fabric.

Agents must NEVER import from core.orchestration directly.
This Protocol is the only supported interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKPlanInfo:
    """Read-only plan information exposed to agents."""
    plan_id: str
    version: int
    status: str
    objective: str
    node_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SDKNodeInfo:
    """Read-only node execution information exposed to agents."""
    node_key: str
    node_execution_id: str
    status: str
    attempt: int
    output: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


@dataclass(frozen=True)
class SDKDelegationResult:
    """Result of a delegation request."""
    delegation_id: str
    status: str
    selected_agent: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class OrchestrationSDK(Protocol):
    """Orchestration SDK — agent-facing orchestration interface (C5 §40).

    Capabilities:
      - delegate: Request another agent to handle a subtask
      - get_plan: Read the current plan
      - get_node: Read a node's execution status
      - update_state: Write to the shared orchestration state
      - read_state: Read from the shared orchestration state
      - request_replan: Request the orchestrator to replan
      - request_approval: Request human approval for an action
      - checkpoint: Request a durable checkpoint
    """

    async def delegate(
        self,
        capability: str,
        objective: str,
        inputs: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> SDKDelegationResult:
        """Delegate a subtask to another agent by capability (C5 §16, §41).

        The Core resolves which agent to use. The calling agent does not
        need to know the target agent's identity or implementation.

        Args:
            capability: Required capability (e.g., 'financial_analysis').
            objective: What the delegated agent should accomplish.
            inputs: Data to pass to the delegated agent.
            budget: Resource budget for the delegation.

        Returns:
            SDKDelegationResult with status and output.
        """
        ...

    async def get_plan(self) -> SDKPlanInfo | None:
        """Get the current plan for this execution (C5 §40).

        Returns:
            SDKPlanInfo or None if no plan exists.
        """
        ...

    async def get_node(self, node_key: str) -> SDKNodeInfo | None:
        """Get the execution status of a specific node (C5 §40).

        Args:
            node_key: The node's unique key within the plan.

        Returns:
            SDKNodeInfo or None if the node doesn't exist.
        """
        ...

    async def update_state(
        self,
        patches: list[dict[str, Any]],
    ) -> int:
        """Apply patches to the shared orchestration state (C5 §21, §40).

        Each patch is a dict with:
          - path: JSON Pointer path (e.g., '/research/findings')
          - operation: 'add', 'replace', or 'remove'
          - value: The value to set (for add/replace)
          - reason: Optional explanation

        Args:
            patches: List of patch dicts to apply atomically.

        Returns:
            The new state version number.

        Raises:
            ConflictError if optimistic concurrency check fails.
        """
        ...

    async def read_state(
        self, path: str = "/",
    ) -> Any:
        """Read a value from the shared orchestration state (C5 §40).

        Args:
            path: JSON Pointer path. Default '/' returns the full state.

        Returns:
            The value at the given path, or None if not found.
        """
        ...

    async def request_replan(
        self,
        reason: str,
        failed_nodes: list[str] | None = None,
    ) -> str:
        """Request the orchestrator to replan (C5 §33-34, §40).

        Args:
            reason: Why replanning is needed.
            failed_nodes: Node keys that triggered the replan.

        Returns:
            The replan request ID.
        """
        ...

    async def request_approval(
        self,
        action: str,
        risk_level: str = "HIGH",
        reason: str = "",
    ) -> str:
        """Request human approval for an action (C5 §37-38, §40).

        Args:
            action: Description of the action requiring approval.
            risk_level: LOW, MEDIUM, HIGH, or CRITICAL.
            reason: Why approval is needed.

        Returns:
            The approval request ID.
        """
        ...

    async def checkpoint(self, reason: str = "agent_requested") -> str:
        """Request a durable checkpoint of the current state (C5 §28, §40).

        Args:
            reason: Why the checkpoint is being created.

        Returns:
            The checkpoint ID.
        """
        ...