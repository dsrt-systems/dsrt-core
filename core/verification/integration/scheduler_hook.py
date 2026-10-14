"""
Verification-Aware Scheduler Hook (C6 §57).

Provides verification status as a dependency signal to the C5 Scheduler.

Flow (C6 §57):
    Node A completed
        ↓
    Verification passed → Node B becomes READY
    Verification failed → Node B stays BLOCKED

The C5 Scheduler calls should_unblock_downstream() after a node
completes to determine if downstream nodes should be unblocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import NodeStatus, VerificationStatus
from core.storage.models.verification import VerificationRun
from core.observability.logging import get_logger


logger = get_logger("dsrt.verification.integration.scheduler")


@dataclass
class SchedulingSignal:
    """Signal from verification to the scheduler."""
    node_key: str
    node_execution_id: str
    verification_passed: bool
    verification_status: str
    should_unblock_downstream: bool
    reason: str = ""


class VerificationSchedulerHook:
    """Provides verification signals to the C5 Scheduler (C6 §57).

    Usage (called by C5 Scheduler):
        hook = VerificationSchedulerHook(session)
        signal = await hook.should_unblock_downstream(
            node_execution_id="nex_1",
            node_key="research",
        )
        if signal.should_unblock_downstream:
            # Unblock downstream nodes
        else:
            # Keep downstream blocked
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def should_unblock_downstream(
        self,
        *,
        node_execution_id: str,
        node_key: str,
    ) -> SchedulingSignal:
        """Check if a completed node's verification allows downstream.

        Args:
            node_execution_id: The node execution to check.
            node_key: The node key (for logging).

        Returns:
            SchedulingSignal indicating whether downstream should unblock.
        """
        # Find the latest verification run for this node execution
        stmt = (
            select(VerificationRun)
            .where(
                VerificationRun.subject_type == "node_execution",
                VerificationRun.subject_id == node_execution_id,
            )
            .order_by(VerificationRun.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        run = result.scalar_one_or_none()

        if not run:
            # No verification run — allow downstream by default
            # (verification may not be configured for this node)
            return SchedulingSignal(
                node_key=node_key,
                node_execution_id=node_execution_id,
                verification_passed=True,
                verification_status="NOT_VERIFIED",
                should_unblock_downstream=True,
                reason="No verification configured for this node.",
            )

        passed = run.status in (
            VerificationStatus.PASSED.value,
            VerificationStatus.PASSED_WITH_WARNINGS.value,
        )

        signal = SchedulingSignal(
            node_key=node_key,
            node_execution_id=node_execution_id,
            verification_passed=passed,
            verification_status=run.status,
            should_unblock_downstream=passed,
            reason=(
                f"Verification {run.status}"
                if passed
                else f"Verification {run.status} — downstream blocked."
            ),
        )

        logger.info(
            "scheduler_verification_signal",
            node_key=node_key,
            passed=passed,
            status=run.status,
        )

        return signal

    async def get_blocked_nodes(
        self,
        execution_id: str,
        node_keys: list[str],
    ) -> list[str]:
        """Get node keys that are blocked by failed verification.

        Args:
            execution_id: The orchestration execution.
            node_keys: Candidate node keys to check.

        Returns:
            List of node keys blocked by verification failure.
        """
        blocked: list[str] = []

        for node_key in node_keys:
            # Find node executions for this key
            from core.storage.models.orchestration import NodeExecutionORM
            stmt = (
                select(NodeExecutionORM)
                .where(
                    NodeExecutionORM.orchestration_execution_id == execution_id,
                    NodeExecutionORM.plan_node_key == node_key,
                )
                .order_by(NodeExecutionORM.created_at.desc())
                .limit(1)
            )
            result = await self._session.execute(stmt)
            node_exec = result.scalar_one_or_none()

            if not node_exec:
                continue

            signal = await self.should_unblock_downstream(
                node_execution_id=node_exec.id,
                node_key=node_key,
            )

            if not signal.should_unblock_downstream:
                blocked.append(node_key)

        return blocked