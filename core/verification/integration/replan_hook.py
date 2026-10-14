"""
Verification-Aware Replanning Hook (C6 §58).

Triggers C5 replanning when verification failures cannot be
resolved through simple retry.

Flow (C6 §58):
    Verification failed
        ↓
    RecoveryDecider → REPLAN
        ↓
    VerificationReplanHook.trigger_replan()
        ↓
    C5 Replanner creates new plan version
        ↓
    New nodes added for missing evidence/verification
        ↓
    Execution continues with new plan

This is stronger than simple retry because it can add entirely
new nodes to the plan (e.g., "research additional sources").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import (
    VerificationAction,
    VerificationStatus,
)
from schemas.domain.orchestration import (
    PlanConstraints,
    PlanDependency,
    PlanNode,
)
from schemas.domain.verification import (
    C6RecoveryDecision,
    C6VerificationResult,
    VerificationPolicy,
)

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.verification.reliability.recovery import (
    C6RecoveryDecider,
    RecoveryContext,
)


logger = get_logger("dsrt.verification.integration.replan")


@dataclass
class ReplanTrigger:
    """A trigger for verification-aware replanning."""
    should_replan: bool
    reason: str
    failed_node_keys: list[str] = field(default_factory=list)
    suggested_new_nodes: list[PlanNode] = field(default_factory=list)
    suggested_new_dependencies: list[PlanDependency] = field(default_factory=list)
    recovery_action: str = ""
    verification_run_id: str = ""


class VerificationReplanHook:
    """Triggers replanning based on verification failures (C6 §58).

    Usage (called by C5 Orchestrator after verification failure):
        hook = VerificationReplanHook(session, kernel)
        trigger = await hook.evaluate_replan(
            verification_result=result,
            policy=policy,
            execution_id="exe_1",
            failed_node_key="research",
        )
        if trigger.should_replan:
            # Call C5 Replanner with trigger.suggested_new_nodes
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._decider = C6RecoveryDecider()

    async def evaluate_replan(
        self,
        *,
        verification_result: C6VerificationResult,
        policy: VerificationPolicy,
        execution_id: str,
        failed_node_key: str,
        attempt: int = 1,
        recovery_cycle: int = 0,
        replan_count: int = 0,
        previous_actions: list[str] | None = None,
    ) -> ReplanTrigger:
        """Evaluate whether verification failure should trigger replanning.

        Args:
            verification_result: The failed verification result.
            policy: Active verification policy.
            execution_id: The orchestration execution.
            failed_node_key: The node that failed verification.
            attempt: Current verification attempt.
            recovery_cycle: Current recovery cycle.
            replan_count: Number of replans already done.
            previous_actions: Previously attempted recovery actions.

        Returns:
            ReplanTrigger with decision and suggested new nodes.
        """
        # 1. Check if verification passed (no replan needed)
        if verification_result.status in (
            VerificationStatus.PASSED,
            VerificationStatus.PASSED_WITH_WARNINGS,
        ):
            return ReplanTrigger(
                should_replan=False,
                reason="Verification passed.",
                verification_run_id=verification_result.verification_run_id,
            )

        # 2. Get recovery decision
        context = RecoveryContext(
            verification_result=verification_result,
            policy=policy,
            attempt_number=attempt,
            recovery_cycle=recovery_cycle,
            replan_count=replan_count,
            previous_actions=previous_actions or [],
            execution_id=execution_id,
        )
        decision = self._decider.decide(context)

        # 3. Only replan if the decision says so
        if decision.action not in (
            VerificationAction.REPLAN,
            VerificationAction.RESEARCH_MORE,
            VerificationAction.REGENERATE,
        ):
            return ReplanTrigger(
                should_replan=False,
                reason=f"Recovery action is {decision.action.value}, not replan.",
                recovery_action=decision.action.value,
                verification_run_id=verification_result.verification_run_id,
            )

        # 4. Generate suggested new nodes based on failure type
        new_nodes, new_deps = self._generate_replan_nodes(
            failed_node_key=failed_node_key,
            decision=decision,
            verification_result=verification_result,
        )

        logger.info(
            "replan_triggered_by_verification",
            execution_id=execution_id,
            failed_node=failed_node_key,
            action=decision.action.value,
            new_nodes=len(new_nodes),
        )

        return ReplanTrigger(
            should_replan=True,
            reason=decision.reason,
            failed_node_keys=[failed_node_key],
            suggested_new_nodes=new_nodes,
            suggested_new_dependencies=new_deps,
            recovery_action=decision.action.value,
            verification_run_id=verification_result.verification_run_id,
        )

    def _generate_replan_nodes(
        self,
        failed_node_key: str,
        decision: C6RecoveryDecision,
        verification_result: C6VerificationResult,
    ) -> tuple[list[PlanNode], list[PlanDependency]]:
        """Generate suggested new nodes for the replan.

        Creates nodes that address the specific verification failures.
        """
        nodes: list[PlanNode] = []
        deps: list[PlanDependency] = []

        if decision.action == VerificationAction.RESEARCH_MORE:
            # Add a research node to gather more evidence
            research_key = f"{failed_node_key}_additional_research"
            nodes.append(PlanNode(
                node_key=research_key,
                name=f"Additional Research for {failed_node_key}",
                description=(
                    f"Gather additional evidence to address verification "
                    f"failures: {'; '.join(verification_result.failures[:2])}"
                ),
                node_type="AGENT_TASK",
                required_capabilities=["web_search", "evidence_synthesis"],
                configuration={
                    "is_replan_node": True,
                    "original_node": failed_node_key,
                    "trigger_failures": verification_result.failures[:3],
                },
            ))
            # The new research feeds back into the failed node's retry
            retry_key = f"{failed_node_key}_retry"
            deps.append(PlanDependency(
                source_node_key=research_key,
                target_node_key=retry_key,
                dependency_type="HARD",
            ))

        elif decision.action == VerificationAction.REGENERATE:
            # Add a regeneration node
            regen_key = f"{failed_node_key}_regenerate"
            nodes.append(PlanNode(
                node_key=regen_key,
                name=f"Regenerate {failed_node_key}",
                description=(
                    f"Regenerate output to fix: "
                    f"{'; '.join(verification_result.failures[:2])}"
                ),
                node_type="AGENT_TASK",
                configuration={
                    "is_replan_node": True,
                    "original_node": failed_node_key,
                    "regenerate": True,
                },
            ))

        elif decision.action == VerificationAction.REPLAN:
            # Generic replan — add a verification retry node
            verify_key = f"{failed_node_key}_reverify"
            nodes.append(PlanNode(
                node_key=verify_key,
                name=f"Re-verify {failed_node_key}",
                description="Re-execute and re-verify after plan adjustment.",
                node_type="AGENT_TASK",
                configuration={
                    "is_replan_node": True,
                    "original_node": failed_node_key,
                },
            ))

        return nodes, deps