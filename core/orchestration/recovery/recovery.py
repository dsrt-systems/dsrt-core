"""
Recovery Manager (C5 §30-32, §70-71).

Classifies failures and determines the appropriate recovery strategy.

Recovery Strategies (C5 §32):
  RETRY          — Re-execute the same node (with backoff)
  FALLBACK       — Try an alternate model/tool
  REASSIGN       — Assign to a different agent
  SKIP           — Skip the node (SOFT dependency only)
  ROLLBACK       — Rollback to last checkpoint
  REPLAN         — Trigger replanning (C5.10)
  HUMAN_ESCALATION — Request human intervention
  CANCEL         — Cancel the execution

Failure Classification (C5 §31):
  Retryable:     PROVIDER_TIMEOUT, TOOL_TIMEOUT, TEMPORARY_UNAVAILABLE, RATE_LIMITED
  Non-retryable: PERMISSION_DENIED, INVALID_INPUT, POLICY_VIOLATION
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import EventType, NodeStatus, RecoveryAction

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.orchestration.executor.lifecycle import NodeLifecycleManager
from core.storage.models.orchestration import NodeExecutionORM


logger = get_logger("dsrt.orchestration.recovery")


# ------------------------------------------------------------------
# Error Classification (C5 §31)
# ------------------------------------------------------------------

RETRYABLE_ERRORS = frozenset({
    "PROVIDER_TIMEOUT",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_OVERLOADED",
    "TOOL_TIMEOUT",
    "TOOL_NETWORK_FAILURE",
    "TOOL_RATE_LIMITED",
    "TEMPORARY_UNAVAILABLE",
    "RATE_LIMITED",
    "MODEL_NOT_AVAILABLE",
    "CONTEXT_TOO_LARGE",
})

NON_RETRYABLE_ERRORS = frozenset({
    "PERMISSION_DENIED",
    "AUTHORIZATION_DENIED",
    "INVALID_INPUT",
    "VALIDATION_ERROR",
    "POLICY_VIOLATION",
    "AGENT_NOT_FOUND",
    "AGENT_INVALID",
    "TOOL_NOT_FOUND",
    "TOOL_PERMISSION_DENIED",
    "TOOL_INVALID_ARGUMENT",
    "MEMORY_ACCESS_DENIED",
    "CREDENTIAL_INVALID",
    "CREDENTIAL_MISSING",
    "EXECUTION_CANCELLED",
    "UNSUPPORTED_NODE_TYPE",
})


class FailureClassification(str, Enum):
    """How a failure should be treated by the recovery system."""
    RETRYABLE = "RETRYABLE"
    RETRYABLE_WITH_BACKOFF = "RETRYABLE_WITH_BACKOFF"
    NON_RETRYABLE = "NON_RETRYABLE"
    REQUIRES_REPLAN = "REQUIRES_REPLAN"
    UNKNOWN = "UNKNOWN"


@dataclass
class RecoveryDecision:
    """The recovery action determined for a failed node."""
    action: RecoveryAction
    reason: str
    target_node_key: str
    retry_delay_seconds: float = 0.0
    new_agent_slug: str | None = None
    new_model_id: str | None = None
    requires_human: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class RecoveryManager:
    """Classifies failures and determines recovery strategies.

    Usage:
        rm = RecoveryManager(session, kernel)
        decision = rm.classify_and_decide(
            node_key="financial_analysis",
            error_code="PROVIDER_TIMEOUT",
            attempt=1,
            max_attempts=3,
        )
        if decision.action == RecoveryAction.RETRY:
            await asyncio.sleep(decision.retry_delay_seconds)
            # Re-execute node
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
        default_max_attempts: int = 3,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 60.0,
        backoff_multiplier: float = 2.0,
        heartbeat_timeout_seconds: int = 300,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._max_attempts = default_max_attempts
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._backoff_multiplier = backoff_multiplier
        self._heartbeat_timeout = heartbeat_timeout_seconds
        self._lifecycle = NodeLifecycleManager()

    # ------------------------------------------------------------------
    # Failure Classification (C5 §31)
    # ------------------------------------------------------------------

    def classify_failure(self, error_code: str) -> FailureClassification:
        """Classify a failure as retryable or non-retryable (C5 §31).

        Args:
            error_code: The error code from the node execution.

        Returns:
            FailureClassification indicating how to handle the failure.
        """
        if not error_code:
            return FailureClassification.UNKNOWN

        if error_code in NON_RETRYABLE_ERRORS:
            return FailureClassification.NON_RETRYABLE

        if error_code in RETRYABLE_ERRORS:
            # Rate limits get backoff, timeouts get immediate retry
            if "RATE_LIMIT" in error_code or "OVERLOADED" in error_code:
                return FailureClassification.RETRYABLE_WITH_BACKOFF
            return FailureClassification.RETRYABLE

        # Dependency/resource failures may require replanning
        if error_code in (
            "DEPENDENCY_FAILED",
            "RESOURCE_UNAVAILABLE",
            "WORLD_UNAVAILABLE",
            "ENVIRONMENT_UNAVAILABLE",
        ):
            return FailureClassification.REQUIRES_REPLAN

        return FailureClassification.UNKNOWN

    # ------------------------------------------------------------------
    # Recovery Decision (C5 §32)
    # ------------------------------------------------------------------

    def classify_and_decide(
        self,
        node_key: str,
        error_code: str,
        attempt: int,
        max_attempts: int | None = None,
        is_soft_dependency: bool = False,
        error_message: str = "",
    ) -> RecoveryDecision:
        """Classify a failure and determine the recovery action.

        Decision tree (C5 §30-32):
          1. Non-retryable → CANCEL or HUMAN_ESCALATION
          2. Retryable + attempts remaining → RETRY (with backoff)
          3. Retryable + attempts exhausted → FALLBACK or REPLAN
          4. Requires replan → REPLAN
          5. Soft dependency + failed → SKIP
          6. Unknown → HUMAN_ESCALATION

        Args:
            node_key: The failed node's key.
            error_code: The error code.
            attempt: Current attempt number.
            max_attempts: Maximum retry attempts (default from config).
            is_soft_dependency: Whether this node is a SOFT dependency.
            error_message: Human-readable error description.

        Returns:
            RecoveryDecision with the recommended action.
        """
        limit = max_attempts or self._max_attempts
        classification = self.classify_failure(error_code)

        # 1. Non-retryable errors
        if classification == FailureClassification.NON_RETRYABLE:
            return RecoveryDecision(
                action=RecoveryAction.CANCEL,
                reason=(
                    f"Non-retryable error '{error_code}': {error_message}"
                ),
                target_node_key=node_key,
                metadata={"error_code": error_code, "classification": classification.value},
            )

        # 2. Retryable + attempts remaining
        if classification in (
            FailureClassification.RETRYABLE,
            FailureClassification.RETRYABLE_WITH_BACKOFF,
        ) and attempt < limit:
            delay = self._calculate_backoff(attempt, classification)
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                reason=(
                    f"Retryable error '{error_code}', "
                    f"attempt {attempt}/{limit}."
                ),
                target_node_key=node_key,
                retry_delay_seconds=delay,
                metadata={
                    "error_code": error_code,
                    "attempt": attempt,
                    "max_attempts": limit,
                    "classification": classification.value,
                },
            )

        # 3. Retryable + attempts exhausted
        if classification in (
            FailureClassification.RETRYABLE,
            FailureClassification.RETRYABLE_WITH_BACKOFF,
        ) and attempt >= limit:
            return RecoveryDecision(
                action=RecoveryAction.REPLAN,
                reason=(
                    f"Retryable error '{error_code}' exhausted "
                    f"all {limit} attempts."
                ),
                target_node_key=node_key,
                metadata={"error_code": error_code, "attempts_exhausted": True},
            )

        # 4. Requires replan
        if classification == FailureClassification.REQUIRES_REPLAN:
            return RecoveryDecision(
                action=RecoveryAction.REPLAN,
                reason=f"Resource/dependency failure: {error_code}",
                target_node_key=node_key,
                metadata={"error_code": error_code},
            )

        # 5. Soft dependency — can skip
        if is_soft_dependency:
            return RecoveryDecision(
                action=RecoveryAction.SKIP,
                reason=(
                    f"Soft dependency failed with '{error_code}', "
                    f"skipping node."
                ),
                target_node_key=node_key,
                metadata={"error_code": error_code, "soft_dependency": True},
            )

        # 6. Unknown — escalate to human
        return RecoveryDecision(
            action=RecoveryAction.HUMAN_ESCALATION,
            reason=f"Unknown error '{error_code}': {error_message}",
            target_node_key=node_key,
            requires_human=True,
            metadata={"error_code": error_code, "classification": "UNKNOWN"},
        )

    # ------------------------------------------------------------------
    # Retry Execution (C5 §31)
    # ------------------------------------------------------------------

    async def execute_retry(
        self,
        node_execution_id: str,
        decision: RecoveryDecision,
    ) -> bool:
        """Execute a retry for a failed node.

        Updates the node execution status to RETRYING, waits for the
        backoff delay, then transitions to RUNNING for re-execution.

        Returns:
            True if the retry was initiated successfully.
        """
        if decision.action != RecoveryAction.RETRY:
            logger.warning(
                "retry_called_with_non_retry_action",
                action=decision.action.value,
                node=decision.target_node_key,
            )
            return False

        # 1. Update node status to RETRYING
        stmt = (
            update(NodeExecutionORM)
            .where(NodeExecutionORM.id == node_execution_id)
            .values(status=NodeStatus.RETRYING.value)
        )
        await self._session.execute(stmt)
        await self._session.flush()

        # 2. Emit retry event
        await self._emit_event(
            decision.metadata.get("execution_id", ""),
            EventType.AGENT_EVENT,
            {
                "recovery_event": "NODE_RETRIED",
                "node_key": decision.target_node_key,
                "node_execution_id": node_execution_id,
                "delay_seconds": decision.retry_delay_seconds,
                "reason": decision.reason,
            },
        )

        # 3. Wait for backoff delay
        if decision.retry_delay_seconds > 0:
            logger.info(
                "retry_backoff_waiting",
                node=decision.target_node_key,
                delay=decision.retry_delay_seconds,
            )
            await asyncio.sleep(decision.retry_delay_seconds)

        # 4. Transition to RUNNING (ready for re-execution)
        stmt = (
            update(NodeExecutionORM)
            .where(NodeExecutionORM.id == node_execution_id)
            .values(
                status=NodeStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc),
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

        logger.info(
            "retry_initiated",
            node=decision.target_node_key,
            node_execution_id=node_execution_id,
        )

        return True

    # ------------------------------------------------------------------
    # Fallback (C5 §32)
    # ------------------------------------------------------------------

    def decide_fallback(
        self,
        node_key: str,
        failed_model_id: str | None = None,
        available_models: list[str] | None = None,
        failed_agent_slug: str | None = None,
        available_agents: list[str] | None = None,
    ) -> RecoveryDecision:
        """Determine a fallback target when the primary fails.

        Tries model fallback first, then agent fallback.
        """
        # Model fallback
        if failed_model_id and available_models:
            alternates = [m for m in available_models if m != failed_model_id]
            if alternates:
                return RecoveryDecision(
                    action=RecoveryAction.FALLBACK,
                    reason=f"Model '{failed_model_id}' failed, falling back to '{alternates[0]}'.",
                    target_node_key=node_key,
                    new_model_id=alternates[0],
                    metadata={
                        "failed_model": failed_model_id,
                        "fallback_model": alternates[0],
                    },
                )

        # Agent fallback
        if failed_agent_slug and available_agents:
            alternates = [a for a in available_agents if a != failed_agent_slug]
            if alternates:
                return RecoveryDecision(
                    action=RecoveryAction.REASSIGN,
                    reason=f"Agent '{failed_agent_slug}' failed, reassigning to '{alternates[0]}'.",
                    target_node_key=node_key,
                    new_agent_slug=alternates[0],
                    metadata={
                        "failed_agent": failed_agent_slug,
                        "fallback_agent": alternates[0],
                    },
                )

        # No fallback available
        return RecoveryDecision(
            action=RecoveryAction.REPLAN,
            reason="No fallback model or agent available.",
            target_node_key=node_key,
        )

    # ------------------------------------------------------------------
    # Heartbeat Monitoring (C5 §71)
    # ------------------------------------------------------------------

    async def detect_stale_nodes(
        self,
        orchestration_execution_id: str,
        timeout_seconds: int | None = None,
    ) -> list[str]:
        """Detect node executions that have gone stale (C5 §71).

        A node is stale if it's in RUNNING status but hasn't been
        updated within the heartbeat timeout.

        Returns:
            List of stale NodeExecutionORM IDs.
        """
        timeout = timeout_seconds or self._heartbeat_timeout
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout)

        stmt = (
            select(NodeExecutionORM)
            .where(
                NodeExecutionORM.orchestration_execution_id
                == orchestration_execution_id,
                NodeExecutionORM.status == NodeStatus.RUNNING.value,
                NodeExecutionORM.updated_at < cutoff,
            )
        )
        result = await self._session.execute(stmt)
        stale_nodes = list(result.scalars().all())

        stale_ids = [n.id for n in stale_nodes]
        if stale_ids:
            logger.warning(
                "stale_nodes_detected",
                execution_id=orchestration_execution_id,
                stale_count=len(stale_ids),
                timeout_seconds=timeout,
            )

        return stale_ids

    async def recover_stale_nodes(
        self,
        orchestration_execution_id: str,
        timeout_seconds: int | None = None,
    ) -> list[RecoveryDecision]:
        """Detect and initiate recovery for stale nodes.

        Marks stale nodes as FAILED and returns recovery decisions.
        """
        stale_ids = await self.detect_stale_nodes(
            orchestration_execution_id, timeout_seconds,
        )

        decisions: list[RecoveryDecision] = []
        for node_exec_id in stale_ids:
            # Load the node execution to get the node key
            stmt = (
                select(NodeExecutionORM)
                .where(NodeExecutionORM.id == node_exec_id)
            )
            result = await self._session.execute(stmt)
            node_exec = result.scalar_one_or_none()

            if not node_exec:
                continue

            # Mark as FAILED
            node_exec.status = NodeStatus.FAILED.value
            node_exec.error_code = "NODE_STALE"
            node_exec.error_message = (
                f"Node heartbeat timeout after {timeout_seconds or self._heartbeat_timeout}s."
            )
            node_exec.completed_at = datetime.now(timezone.utc)

            # Create recovery decision
            decision = RecoveryDecision(
                action=RecoveryAction.RETRY,
                reason="Node heartbeat timeout — recovering stale execution.",
                target_node_key=node_exec.plan_node_key,
                metadata={
                    "node_execution_id": node_exec_id,
                    "stale_timeout": timeout_seconds or self._heartbeat_timeout,
                },
            )
            decisions.append(decision)

        if decisions:
            await self._session.flush()
            logger.info(
                "stale_nodes_recovered",
                execution_id=orchestration_execution_id,
                recovered_count=len(decisions),
            )

        return decisions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _calculate_backoff(
        self,
        attempt: int,
        classification: FailureClassification,
    ) -> float:
        """Calculate exponential backoff delay (C5 §31).

        Formula: min(base * multiplier^attempt, max_backoff)

        For RETRYABLE (timeouts): base delay
        For RETRYABLE_WITH_BACKOFF (rate limits): exponential delay
        """
        if classification == FailureClassification.RETRYABLE:
            # Fixed short delay for timeouts
            return min(self._base_backoff, self._max_backoff)

        # Exponential backoff for rate limits
        delay = self._base_backoff * (self._backoff_multiplier ** (attempt - 1))
        return min(delay, self._max_backoff)

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        """Emit a recovery event into the execution trajectory."""
        if not self._kernel or not execution_id:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.orchestration.recovery",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "recovery_event_emission_failed",
                execution_id=execution_id,
                error=str(e),
            )