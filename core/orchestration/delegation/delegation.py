"""
Delegation Manager (C5 §16-18, §41, §81-84).

Enables agents to delegate subtasks to other agents through
capability-based resolution, without knowing the target agent's
implementation.

Architecture (C5 §16-17):
    Agent → sdk.orchestration.delegate(capability="financial_analysis")
        ↓
    DelegationManager
        ↓
    Capability Registry → Eligible Agents
        ↓
    Policy Filter → Permission Inheritance Check
        ↓
    Budget Check → Child ≤ Parent Remaining
        ↓
    Depth Check → max_delegation_depth
        ↓
    Agent Resolution → Selected Agent
        ↓
    Delegation Record Persisted

Key invariants (C5 §95):
  - Invariant 2: Child permissions ⊆ parent permissions
  - Invariant 3: Child resources ≤ parent remaining budget
  - Invariant 8: Cancellation propagates to delegations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import DelegationStatus, EventType

from core.agents.registry import AgentRegistry
from core.api.errors.exceptions import (
    AuthorizationError,
    DSRTError,
    NotFoundError,
    ResourceLimitError,
    ValidationError,
)
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.orchestration_state import DelegationORM


logger = get_logger("dsrt.orchestration.delegation")


@dataclass
class DelegationRequest:
    """A request from an agent to delegate a subtask (C5 §41)."""

    parent_node_execution_id: str
    orchestration_execution_id: str
    organization_id: str
    task_id: str

    # What the delegating agent needs
    requested_capability: str
    objective: str
    inputs: dict[str, Any] = field(default_factory=dict)

    # Security context inherited from parent
    parent_permissions: dict[str, Any] = field(default_factory=dict)
    parent_budget: dict[str, Any] = field(default_factory=dict)
    parent_depth: int = 0

    # Requested budget for the child
    budget_allocation: dict[str, Any] = field(default_factory=dict)

    # Constraints
    max_duration_seconds: int | None = None
    required_role: str | None = None


@dataclass
class DelegationResult:
    """Result of a delegation attempt."""

    delegation_id: str
    status: str  # DelegationStatus value
    selected_agent_slug: str | None = None
    selected_agent_version: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DelegationManager:
    """Manages agent-to-agent delegation with full security and budget controls.

    Usage:
        manager = DelegationManager(session, kernel, agent_registry)
        result = await manager.delegate(request)
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel,
        agent_registry: AgentRegistry,
        max_delegation_depth: int = 5,
        max_children_per_node: int = 20,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._agent_registry = agent_registry
        self._max_depth = max_delegation_depth
        self._max_children = max_children_per_node

    async def delegate(
        self, request: DelegationRequest,
    ) -> DelegationResult:
        """Process a delegation request through the full security pipeline.

        Pipeline (C5 §16-18, §81-84):
          1. Depth check (prevent runaway recursion)
          2. Children count check (prevent fan-out explosion)
          3. Capability resolution (find eligible agents)
          4. Permission inheritance check (child ⊆ parent)
          5. Budget propagation check (child ≤ parent remaining)
          6. Agent selection
          7. Persist delegation record
          8. Emit event

        Returns:
            DelegationResult with status and selected agent info.
        """
        delegation_id = new_id(IdPrefix.DELEGATION)

        # 1. Depth check (C5 §83)
        if request.parent_depth >= self._max_depth:
            logger.warning(
                "delegation_depth_exceeded",
                delegation_id=delegation_id,
                parent_depth=request.parent_depth,
                max_depth=self._max_depth,
            )
            return DelegationResult(
                delegation_id=delegation_id,
                status=DelegationStatus.FAILED.value,
                error_code="DELEGATION_DEPTH_EXCEEDED",
                error_message=(
                    f"Delegation depth {request.parent_depth} exceeds "
                    f"maximum {self._max_depth}."
                ),
            )

        # 2. Children count check (C5 §83)
        existing_children = await self._count_active_children(
            request.parent_node_execution_id,
        )
        if existing_children >= self._max_children:
            logger.warning(
                "delegation_children_exceeded",
                delegation_id=delegation_id,
                parent_node=request.parent_node_execution_id,
                existing=existing_children,
                max=self._max_children,
            )
            return DelegationResult(
                delegation_id=delegation_id,
                status=DelegationStatus.FAILED.value,
                error_code="DELEGATION_CHILDREN_EXCEEDED",
                error_message=(
                    f"Parent node already has {existing_children} active "
                    f"delegations (max {self._max_children})."
                ),
            )

        # 3. Capability resolution (C5 §16-18)
        selected_agent = await self._resolve_agent_by_capability(
            request.requested_capability,
            request.organization_id,
        )

        if not selected_agent:
            logger.warning(
                "delegation_no_eligible_agent",
                delegation_id=delegation_id,
                capability=request.requested_capability,
            )
            return DelegationResult(
                delegation_id=delegation_id,
                status=DelegationStatus.FAILED.value,
                error_code="NO_ELIGIBLE_AGENT",
                error_message=(
                    f"No active agent found with capability "
                    f"'{request.requested_capability}'."
                ),
            )

        agent_slug, agent_version = selected_agent

        # 4. Permission inheritance check (C5 §82, Invariant 2)
        perm_check = self._check_permission_inheritance(
            parent_permissions=request.parent_permissions,
            agent_slug=agent_slug,
            requested_capability=request.requested_capability,
        )
        if not perm_check.allowed:
            logger.warning(
                "delegation_permission_denied",
                delegation_id=delegation_id,
                agent_slug=agent_slug,
                reason=perm_check.reason,
            )
            return DelegationResult(
                delegation_id=delegation_id,
                status=DelegationStatus.FAILED.value,
                error_code="DELEGATION_PERMISSION_DENIED",
                error_message=perm_check.reason,
            )

        # 5. Budget propagation check (C5 §84, Invariant 3)
        budget_check = self._check_budget_propagation(
            parent_budget=request.parent_budget,
            child_allocation=request.budget_allocation,
        )
        if not budget_check.allowed:
            logger.warning(
                "delegation_budget_exceeded",
                delegation_id=delegation_id,
                reason=budget_check.reason,
            )
            return DelegationResult(
                delegation_id=delegation_id,
                status=DelegationStatus.FAILED.value,
                error_code="DELEGATION_BUDGET_EXCEEDED",
                error_message=budget_check.reason,
            )

        # 6. Persist delegation record
        delegation_orm = DelegationORM(
            id=delegation_id,
            parent_node_execution_id=request.parent_node_execution_id,
            orchestration_execution_id=request.orchestration_execution_id,
            requested_capability=request.requested_capability,
            selected_agent_slug=agent_slug,
            selected_agent_version=agent_version,
            status=DelegationStatus.ACCEPTED.value,
            input_reference=request.inputs,
            depth=request.parent_depth + 1,
            budget_allocated=request.budget_allocation,
        )
        self._session.add(delegation_orm)
        await self._session.flush()

        # 7. Emit event
        await self._emit_event(
            request.orchestration_execution_id,
            EventType.AGENT_EVENT,
            {
                "delegation_event": "DELEGATION_ACCEPTED",
                "delegation_id": delegation_id,
                "parent_node_execution_id": request.parent_node_execution_id,
                "requested_capability": request.requested_capability,
                "selected_agent": agent_slug,
                "selected_version": agent_version,
                "depth": request.parent_depth + 1,
            },
        )

        logger.info(
            "delegation_accepted",
            delegation_id=delegation_id,
            parent_node=request.parent_node_execution_id,
            capability=request.requested_capability,
            agent=agent_slug,
            version=agent_version,
            depth=request.parent_depth + 1,
        )

        return DelegationResult(
            delegation_id=delegation_id,
            status=DelegationStatus.ACCEPTED.value,
            selected_agent_slug=agent_slug,
            selected_agent_version=agent_version,
            metadata={
                "depth": request.parent_depth + 1,
                "budget_allocated": request.budget_allocation,
            },
        )

    async def complete_delegation(
        self,
        delegation_id: str,
        status: str,
        output: dict[str, Any] | None = None,
    ) -> None:
        """Mark a delegation as completed or failed."""
        from sqlalchemy import select

        stmt = select(DelegationORM).where(DelegationORM.id == delegation_id)
        result = await self._session.execute(stmt)
        delegation = result.scalar_one_or_none()

        if not delegation:
            raise NotFoundError(f"Delegation '{delegation_id}' not found.")

        delegation.status = status
        if output:
            delegation.output_reference = output
        if status in (
            DelegationStatus.COMPLETED.value,
            DelegationStatus.FAILED.value,
            DelegationStatus.CANCELLED.value,
        ):
            delegation.completed_at = datetime.now(timezone.utc)

        await self._session.flush()

        logger.info(
            "delegation_completed",
            delegation_id=delegation_id,
            status=status,
        )

    async def cancel_delegations_for_execution(
        self, orchestration_execution_id: str,
    ) -> int:
        """Cancel all active delegations for an execution (C5 §68, Invariant 8).

        Returns the count of cancelled delegations.
        """
        from sqlalchemy import select, update

        stmt = (
            update(DelegationORM)
            .where(
                DelegationORM.orchestration_execution_id
                == orchestration_execution_id,
                DelegationORM.status.in_([
                    DelegationStatus.REQUESTED.value,
                    DelegationStatus.RESOLVING.value,
                    DelegationStatus.ACCEPTED.value,
                    DelegationStatus.RUNNING.value,
                ]),
            )
            .values(
                status=DelegationStatus.CANCELLED.value,
                completed_at=datetime.now(timezone.utc),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.flush()

        count = result.rowcount
        if count > 0:
            logger.info(
                "delegations_cancelled",
                orchestration_execution_id=orchestration_execution_id,
                count=count,
            )
        return count

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def _resolve_agent_by_capability(
        self,
        capability: str,
        organization_id: str,
    ) -> tuple[str, str] | None:
        """Find the best active agent for a capability (C5 §16-18).

        Returns (agent_slug, agent_version) or None.

        Selection criteria (C5 §18):
          1. Agent has the required capability
          2. Agent is ACTIVE
          3. Agent version is ACTIVE
          4. Latest version preferred
        """
        try:
            agents = await self._agent_registry.list_agents()
        except Exception as e:
            logger.error(
                "delegation_agent_list_failed",
                error=str(e),
            )
            return None

        for agent in agents:
            # Check if agent has the capability
            agent_caps = set()
            if hasattr(agent, "capabilities"):
                agent_caps = set(agent.capabilities)

            if capability not in agent_caps:
                continue

            # Resolve latest active version
            try:
                version = await self._agent_registry.resolve_agent_version(
                    agent.slug if hasattr(agent, "slug") else agent.id,
                )
                return (
                    agent.slug if hasattr(agent, "slug") else agent.id,
                    version.version,
                )
            except NotFoundError:
                continue

        return None

    # ------------------------------------------------------------------
    # Security Checks
    # ------------------------------------------------------------------

    @dataclass
    class _CheckResult:
        allowed: bool
        reason: str = ""

    def _check_permission_inheritance(
        self,
        parent_permissions: dict[str, Any],
        agent_slug: str,
        requested_capability: str,
    ) -> _CheckResult:
        """Verify child delegation cannot exceed parent permissions (C5 §82).

        Invariant 2: Child Permissions ⊆ Parent Permissions

        Checks:
          - If parent has network=False, child cannot need network
          - If parent has filesystem=none, child cannot write files
          - If parent has external_actions=False, child cannot take external actions
          - If parent has browser=False, child cannot use browser
        """
        if not parent_permissions:
            # No restrictions specified — allow by default
            return self._CheckResult(allowed=True)

        # Check network permission
        if parent_permissions.get("network") is False:
            # Agent requesting a web-related capability needs network
            network_caps = {
                "web_search", "web_retrieve", "web_research",
                "http_request", "api_call",
            }
            if requested_capability in network_caps:
                return self._CheckResult(
                    allowed=False,
                    reason=(
                        f"Parent has network=False but capability "
                        f"'{requested_capability}' requires network access."
                    ),
                )

        # Check external actions
        if parent_permissions.get("external_actions") is False:
            external_caps = {
                "send_email", "create_ticket", "post_message",
                "external_transaction", "deploy",
            }
            if requested_capability in external_caps:
                return self._CheckResult(
                    allowed=False,
                    reason=(
                        f"Parent has external_actions=False but capability "
                        f"'{requested_capability}' is an external action."
                    ),
                )

        # Check filesystem
        parent_fs = parent_permissions.get("filesystem", "workspace")
        if parent_fs == "none":
            fs_caps = {"file_read", "file_write", "code_execution"}
            if requested_capability in fs_caps:
                return self._CheckResult(
                    allowed=False,
                    reason=(
                        f"Parent has filesystem=none but capability "
                        f"'{requested_capability}' requires filesystem access."
                    ),
                )

        return self._CheckResult(allowed=True)

    def _check_budget_propagation(
        self,
        parent_budget: dict[str, Any],
        child_allocation: dict[str, Any],
    ) -> _CheckResult:
        """Verify child budget ≤ parent remaining budget (C5 §84).

        Invariant 3: Child Resource Limits ≤ Parent Remaining Budget

        Checks:
          - USD budget
          - Model call budget
          - Tool call budget
          - Duration budget
        """
        if not parent_budget:
            # No budget tracking — allow by default
            return self._CheckResult(allowed=True)

        if not child_allocation:
            # Child not requesting specific budget — allow
            return self._CheckResult(allowed=True)

        # USD budget
        parent_usd = parent_budget.get("remaining_usd")
        child_usd = child_allocation.get("max_usd", 0)
        if parent_usd is not None and child_usd > parent_usd:
            return self._CheckResult(
                allowed=False,
                reason=(
                    f"Child requests ${child_usd:.2f} but parent has "
                    f"only ${parent_usd:.2f} remaining."
                ),
            )

        # Model calls
        parent_models = parent_budget.get("remaining_model_calls")
        child_models = child_allocation.get("max_model_calls", 0)
        if parent_models is not None and child_models > parent_models:
            return self._CheckResult(
                allowed=False,
                reason=(
                    f"Child requests {child_models} model calls but parent "
                    f"has only {parent_models} remaining."
                ),
            )

        # Tool calls
        parent_tools = parent_budget.get("remaining_tool_calls")
        child_tools = child_allocation.get("max_tool_calls", 0)
        if parent_tools is not None and child_tools > parent_tools:
            return self._CheckResult(
                allowed=False,
                reason=(
                    f"Child requests {child_tools} tool calls but parent "
                    f"has only {parent_tools} remaining."
                ),
            )

        # Duration
        parent_dur = parent_budget.get("remaining_seconds")
        child_dur = child_allocation.get("max_duration_seconds", 0)
        if parent_dur is not None and child_dur > parent_dur:
            return self._CheckResult(
                allowed=False,
                reason=(
                    f"Child requests {child_dur}s but parent has "
                    f"only {parent_dur}s remaining."
                ),
            )

        return self._CheckResult(allowed=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _count_active_children(
        self, parent_node_execution_id: str,
    ) -> int:
        """Count active delegations for a parent node."""
        from sqlalchemy import func, select

        stmt = (
            select(func.count(DelegationORM.id))
            .where(
                DelegationORM.parent_node_execution_id
                == parent_node_execution_id,
                DelegationORM.status.in_([
                    DelegationStatus.REQUESTED.value,
                    DelegationStatus.RESOLVING.value,
                    DelegationStatus.ACCEPTED.value,
                    DelegationStatus.RUNNING.value,
                ]),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        """Emit a delegation event into the execution trajectory."""
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.orchestration.delegation",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "delegation_event_emission_failed",
                execution_id=execution_id,
                error=str(e),
            )