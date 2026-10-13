"""
OrchestrationSDK Implementation (C5.11).

Bridges the agent-facing OrchestrationSDK Protocol to the actual
C5 orchestration services. This is the ONLY connection between
agent code and the orchestration fabric.

Architecture:
    Agent → sdk.orchestration.delegate(...)
        ↓
    OrchestrationSDKImpl
        ↓
    DelegationManager / SharedStateStore / Replanner / CheckpointManager
        ↓
    Core Orchestration Fabric
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.agents.registry import AgentRegistry
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.orchestration.checkpoints.checkpoint import CheckpointManager
from core.orchestration.delegation.delegation import (
    DelegationManager,
    DelegationRequest,
)
from core.orchestration.replanning.replanner import ReplanRequest, Replanner
from core.orchestration.state.state_store import SharedStateStore
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
)
from core.storage.models.orchestration import (
    NodeExecutionORM,
    PlanORM,
    PlanVersionORM,
)
from sdk.agent.interfaces.orchestration import (
    SDKDelegationResult,
    SDKNodeInfo,
    SDKPlanInfo,
)
from schemas.domain.enums import DelegationStatus
from schemas.domain.orchestration import StatePatch

from sqlalchemy import select


logger = get_logger("sdk.orchestration")


class OrchestrationSDKImpl:
    """Concrete implementation of OrchestrationSDK backed by C5 services."""

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel,
        execution_id: str,
        task_id: str,
        organization_id: str,
        agent_slug: str,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._execution_id = execution_id
        self._task_id = task_id
        self._organization_id = organization_id
        self._agent_slug = agent_slug

        # Lazy-initialized services
        self._state_store: SharedStateStore | None = None
        self._delegation_manager: DelegationManager | None = None
        self._checkpoint_manager: CheckpointManager | None = None
        self._replanner: Replanner | None = None

    def _get_state_store(self) -> SharedStateStore:
        if self._state_store is None:
            self._state_store = SharedStateStore(self._session, self._kernel)
        return self._state_store

    def _get_delegation_manager(self) -> DelegationManager:
        if self._delegation_manager is None:
            agent_repo = AgentRepository(self._session)
            cap_repo = CapabilityRepository(self._session)
            registry = AgentRegistry(agent_repo, cap_repo)
            self._delegation_manager = DelegationManager(
                self._session, self._kernel, registry,
            )
        return self._delegation_manager

    def _get_checkpoint_manager(self) -> CheckpointManager:
        if self._checkpoint_manager is None:
            self._checkpoint_manager = CheckpointManager(
                self._session, self._kernel,
            )
        return self._checkpoint_manager

    def _get_replanner(self) -> Replanner:
        if self._replanner is None:
            self._replanner = Replanner(self._session, self._kernel)
        return self._replanner

    # ------------------------------------------------------------------
    # Delegation (C5 §16, §41)
    # ------------------------------------------------------------------

    async def delegate(
        self,
        capability: str,
        objective: str,
        inputs: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> SDKDelegationResult:
        """Delegate a subtask to another agent by capability."""
        manager = self._get_delegation_manager()

        # Find the current node execution for this agent
        node_exec_id = await self._find_current_node_execution()

        request = DelegationRequest(
            parent_node_execution_id=node_exec_id or self._execution_id,
            orchestration_execution_id=self._execution_id,
            organization_id=self._organization_id,
            task_id=self._task_id,
            requested_capability=capability,
            objective=objective,
            inputs=inputs or {},
            budget_allocation=budget or {},
        )

        result = await manager.delegate(request)

        return SDKDelegationResult(
            delegation_id=result.delegation_id,
            status=result.status,
            selected_agent=result.selected_agent_slug,
            error=result.error_message,
        )

    # ------------------------------------------------------------------
    # Plan & Node Info (C5 §40)
    # ------------------------------------------------------------------

    async def get_plan(self) -> SDKPlanInfo | None:
        """Get the current plan for this execution."""
        stmt = (
            select(PlanORM)
            .where(PlanORM.task_id == self._task_id)
            .order_by(PlanORM.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        plan = result.scalar_one_or_none()

        if not plan:
            return None

        return SDKPlanInfo(
            plan_id=plan.id,
            version=plan.current_version,
            status=plan.status,
            objective=plan.objective,
        )

    async def get_node(self, node_key: str) -> SDKNodeInfo | None:
        """Get the execution status of a specific node."""
        stmt = (
            select(NodeExecutionORM)
            .where(
                NodeExecutionORM.orchestration_execution_id == self._execution_id,
                NodeExecutionORM.plan_node_key == node_key,
            )
            .order_by(NodeExecutionORM.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        node = result.scalar_one_or_none()

        if not node:
            return None

        return SDKNodeInfo(
            node_key=node.plan_node_key,
            node_execution_id=node.id,
            status=node.status,
            attempt=node.attempt,
            output=node.output_reference or {},
            error_code=node.error_code,
        )

    # ------------------------------------------------------------------
    # Shared State (C5 §21, §40)
    # ------------------------------------------------------------------

    async def update_state(
        self,
        patches: list[dict[str, Any]],
    ) -> int:
        """Apply patches to the shared orchestration state."""
        store = self._get_state_store()

        state_patches = []
        for p in patches:
            state_patches.append(StatePatch(
                path=p.get("path", "/"),
                operation=p.get("operation", "add"),
                value=p.get("value"),
                source=self._agent_slug,
                reason=p.get("reason", ""),
                expected_version=p.get("expected_version"),
            ))

        return await store.apply_patches(
            self._execution_id,
            state_patches,
            source=self._agent_slug,
        )

    async def read_state(
        self, path: str = "/",
    ) -> Any:
        """Read a value from the shared orchestration state."""
        store = self._get_state_store()

        if path == "/":
            return await store.get_state(self._execution_id)

        return await store.read_value(self._execution_id, path)

    # ------------------------------------------------------------------
    # Replanning (C5 §33-34, §40)
    # ------------------------------------------------------------------

    async def request_replan(
        self,
        reason: str,
        failed_nodes: list[str] | None = None,
    ) -> str:
        """Request the orchestrator to replan."""
        # Get current plan info
        plan_info = await self.get_plan()
        if not plan_info:
            logger.warning(
                "replan_requested_no_plan",
                execution_id=self._execution_id,
            )
            return "no_plan"

        # Find the current plan version ID
        stmt = (
            select(PlanVersionORM)
            .where(PlanVersionORM.plan_id == plan_info.plan_id)
            .order_by(PlanVersionORM.version.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        version = result.scalar_one_or_none()

        if not version:
            return "no_version"

        replanner = self._get_replanner()
        replan_result = await replanner.replan(ReplanRequest(
            orchestration_execution_id=self._execution_id,
            plan_id=plan_info.plan_id,
            current_plan_version_id=version.id,
            trigger="AGENT_REQUEST",
            reason=reason,
            failed_node_keys=failed_nodes or [],
        ))

        return replan_result.replan_id or "replan_failed"

    # ------------------------------------------------------------------
    # Approval (C5 §37-38, §40)
    # ------------------------------------------------------------------

    async def request_approval(
        self,
        action: str,
        risk_level: str = "HIGH",
        reason: str = "",
    ) -> str:
        """Request human approval for an action.

        C5.11 v1: Creates an approval event. Full integration with
        C3 ApprovalService comes in C5.12.
        """
        await self._kernel.emit_event(
            execution_id=self._execution_id,
            event_type="APPROVAL_REQUESTED",
            source=f"agent.{self._agent_slug}",
            payload={
                "action": action,
                "risk_level": risk_level,
                "reason": reason,
                "agent_slug": self._agent_slug,
            },
        )

        logger.info(
            "approval_requested_via_sdk",
            execution_id=self._execution_id,
            action=action,
            risk_level=risk_level,
        )

        return f"approval_{self._execution_id}_{action}"

    # ------------------------------------------------------------------
    # Checkpoint (C5 §28, §40)
    # ------------------------------------------------------------------

    async def checkpoint(self, reason: str = "agent_requested") -> str:
        """Request a durable checkpoint."""
        manager = self._get_checkpoint_manager()

        # Get current plan version
        plan_info = await self.get_plan()
        plan_version_id = ""
        if plan_info:
            stmt = (
                select(PlanVersionORM)
                .where(PlanVersionORM.plan_id == plan_info.plan_id)
                .order_by(PlanVersionORM.version.desc())
                .limit(1)
            )
            result = await self._session.execute(stmt)
            version = result.scalar_one_or_none()
            if version:
                plan_version_id = version.id

        ckpt = await manager.create_checkpoint(
            orchestration_execution_id=self._execution_id,
            plan_version_id=plan_version_id,
            reason=reason,
        )

        return ckpt.id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _find_current_node_execution(self) -> str | None:
        """Find the most recent node execution for this agent."""
        stmt = (
            select(NodeExecutionORM)
            .where(
                NodeExecutionORM.orchestration_execution_id == self._execution_id,
                NodeExecutionORM.agent_slug == self._agent_slug,
            )
            .order_by(NodeExecutionORM.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        node = result.scalar_one_or_none()
        return node.id if node else None