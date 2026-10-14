"""
Node Verification Hook (C6 §56).

Called by the C5 Node Executor after a node completes execution
but BEFORE the node is marked as COMPLETED.

Flow (C6 §56):
    Node Executor finishes agent execution
        ↓
    NodeVerificationHook.verify_node()
        ↓
    ├── PASSED → Node marked COMPLETED → downstream unblocked
    └── FAILED → Node marked VERIFYING → recovery triggered

This is the primary integration point between C5 and C6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import (
    NodeStatus,
    VerificationStatus,
)
from schemas.domain.verification import (
    C6VerificationResult,
    VerificationRequest,
)

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.verification.engine.engine import VerificationEngine
from core.verification.reliability.classifier import FailureClassifier
from core.verification.reliability.incidents import IncidentManager
from core.verification.reliability.recovery import (
    C6RecoveryDecider,
    RecoveryContext,
)
from schemas.domain.enums import IncidentCategory, IncidentSeverity
from schemas.domain.verification import VerificationPolicy


logger = get_logger("dsrt.verification.integration.node")


@dataclass
class NodeVerificationOutcome:
    """Result of verifying a node's output."""
    node_key: str
    node_execution_id: str
    verified: bool
    verification_status: str
    verification_run_id: str = ""
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recovery_action: str | None = None
    dimensions: dict[str, float] = field(default_factory=dict)
    should_block_downstream: bool = False
    incident_id: str | None = None


class NodeVerificationHook:
    """Verifies node output before marking it COMPLETED (C6 §56).

    Usage (called by C5 Node Executor):
        hook = NodeVerificationHook(session, kernel)
        outcome = await hook.verify_node(
            node_key="research",
            node_execution_id="nex_1",
            execution_id="exe_1",
            agent_output={"report": "...", "claims": [...]},
            policy_id="research_v1",
        )
        if outcome.verified:
            # Mark node COMPLETED
        else:
            # Trigger recovery
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
        default_policy_id: str = "standard",
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._default_policy_id = default_policy_id
        self._engine = VerificationEngine(session, kernel)
        self._classifier = FailureClassifier()
        self._incident_mgr = IncidentManager(session, kernel)
        self._recovery_decider = C6RecoveryDecider(self._classifier)

    async def verify_node(
        self,
        *,
        node_key: str,
        node_execution_id: str,
        execution_id: str,
        agent_output: dict[str, Any],
        policy_id: str | None = None,
        node_type: str = "AGENT_TASK",
        attempt: int = 1,
    ) -> NodeVerificationOutcome:
        """Verify a node's output (C6 §56).

        Args:
            node_key: The plan node key.
            node_execution_id: The specific node execution ID.
            execution_id: The parent orchestration execution.
            agent_output: The output produced by the agent.
            policy_id: Verification policy to use (default: standard).
            node_type: The node type (AGENT_TASK, VERIFICATION, etc.)
            attempt: Current attempt number (for recovery bounds).

        Returns:
            NodeVerificationOutcome with verification result and
            any required recovery action.
        """
        effective_policy = policy_id or self._default_policy_id

        # Skip verification for non-agent nodes
        if node_type in ("CHECKPOINT", "MERGE", "CONDITION"):
            return NodeVerificationOutcome(
                node_key=node_key,
                node_execution_id=node_execution_id,
                verified=True,
                verification_status=VerificationStatus.PASSED.value,
            )

        # Build verification request
        request = VerificationRequest(
            subject_type="node_execution",
            subject_id=node_execution_id,
            policy_id=effective_policy,
            inputs={
                "output": agent_output,
                "node_key": node_key,
                "node_type": node_type,
            },
            metadata={
                "execution_id": execution_id,
                "node_execution_id": node_execution_id,
                "node_key": node_key,
            },
        )

        try:
            result = await self._engine.verify(request)
        except Exception as e:
            logger.error(
                "node_verification_error",
                node_key=node_key,
                error=str(e),
            )
            return NodeVerificationOutcome(
                node_key=node_key,
                node_execution_id=node_execution_id,
                verified=False,
                verification_status=VerificationStatus.INCONCLUSIVE.value,
                failures=[f"Verification engine error: {str(e)[:200]}"],
                should_block_downstream=True,
            )

        # Determine if verified
        verified = result.status in (
            VerificationStatus.PASSED,
            VerificationStatus.PASSED_WITH_WARNINGS,
        )

        # Create reliability incident if failed
        incident_id = None
        recovery_action = None

        if not verified and result.failures:
            # Classify the dominant failure
            failed_checks = [
                c for c in result.checks
                if c.status == VerificationStatus.FAILED
            ]
            if failed_checks:
                classification = self._classifier.classify(failed_checks[0])

                # Create incident
                incident = await self._incident_mgr.create_incident(
                    execution_id=execution_id,
                    category=classification.category,
                    severity=classification.severity,
                    description=(
                        f"Node '{node_key}' verification failed: "
                        f"{result.failures[0][:200]}"
                    ),
                    detected_by="verification_engine",
                    node_execution_id=node_execution_id,
                )
                incident_id = incident.id

                # Determine recovery action
                from schemas.domain.verification import VerificationPolicy as VP
                policy = VP(id=effective_policy)
                recovery_ctx = RecoveryContext(
                    verification_result=result,
                    policy=policy,
                    attempt_number=attempt,
                    execution_id=execution_id,
                    node_execution_id=node_execution_id,
                )
                decision = self._recovery_decider.decide(recovery_ctx)
                recovery_action = decision.action.value

        should_block = not verified and result.status != VerificationStatus.PASSED_WITH_WARNINGS

        logger.info(
            "node_verification_complete",
            node_key=node_key,
            verified=verified,
            status=result.status.value,
            failures=len(result.failures),
            recovery_action=recovery_action,
        )

        return NodeVerificationOutcome(
            node_key=node_key,
            node_execution_id=node_execution_id,
            verified=verified,
            verification_status=result.status.value,
            verification_run_id=result.verification_run_id,
            failures=result.failures,
            warnings=result.warnings,
            recovery_action=recovery_action,
            dimensions=result.dimensions,
            should_block_downstream=should_block,
            incident_id=incident_id,
        )