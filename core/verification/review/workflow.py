"""
Review Workflow (C6 §42-44).

Orchestrates the full human review workflow from verification
failure to final decision. Integrates ReviewManager with the
VerificationEngine and RecoveryDecider.

Workflow:
    Verification INCONCLUSIVE/FAILED
        ↓
    ReviewManager.create_review()
        ↓
    ReviewManager.assign_review()
        ↓
    ReviewManager.start_review()
        ↓
    ReviewManager.decide_review()
        ↓
    Map decision → VerificationStatus
        ↓
    If APPROVED → Accept result
    If REJECTED → Trigger recovery
    If REWORK → Re-execute with constraints
    If EXPIRED → Escalate or fail
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schemas.domain.enums import (
    ReviewStatus,
    VerificationAction,
    VerificationStatus,
)
from schemas.domain.verification import (
    C6RecoveryDecision,
    C6VerificationResult,
    VerificationPolicy,
)

from core.observability.logging import get_logger
from core.storage.models.reliability import ReviewRequestORM
from core.verification.review.requests import ReviewManager


logger = get_logger("dsrt.verification.review.workflow")


@dataclass
class ReviewOutcome:
    """Result of the human review workflow."""
    review_id: str
    decision: str
    verification_status: VerificationStatus
    recovery_action: VerificationAction | None = None
    reason: str = ""
    notes: str = ""


class ReviewWorkflow:
    """Orchestrates the human review workflow (C6 §42-44).

    Usage:
        workflow = ReviewWorkflow(review_manager)

        # Initiate review from a failed verification
        outcome = await workflow.initiate_review(
            verification_result=result,
            policy=policy,
            execution_id="exe_1",
        )

        # Later, when a human decides:
        final = await workflow.complete_review(
            review_id=outcome.review_id,
            decision="APPROVED",
            notes="Verified manually against source documents.",
        )
    """

    def __init__(
        self,
        review_manager: ReviewManager,
    ) -> None:
        self._manager = review_manager

    async def initiate_review(
        self,
        *,
        verification_result: C6VerificationResult,
        policy: VerificationPolicy,
        execution_id: str,
        reviewer_role: str = "admin",
    ) -> ReviewOutcome:
        """Initiate a human review from a verification result.

        Called when verification is INCONCLUSIVE or when the
        RecoveryDecider returns HUMAN_REVIEW.

        Returns:
            ReviewOutcome with the review ID and pending status.
        """
        # Build reason from verification failures
        failures = verification_result.failures
        warnings = verification_result.warnings

        reason_parts = []
        if failures:
            reason_parts.append(
                f"{len(failures)} verification failure(s): "
                + "; ".join(failures[:3])
            )
        if warnings:
            reason_parts.append(
                f"{len(warnings)} warning(s): "
                + "; ".join(warnings[:2])
            )
        if not reason_parts:
            reason_parts.append("Verification inconclusive.")

        reason = " | ".join(reason_parts)

        # Create the review request
        review = await self._manager.create_review(
            verification_run_id=verification_result.verification_run_id,
            reason=reason,
            reviewer_role=reviewer_role,
            evidence_refs=verification_result.evidence_refs,
            execution_id=execution_id,
        )

        logger.info(
            "review_workflow_initiated",
            review_id=review.id,
            verification_run_id=verification_result.verification_run_id,
            execution_id=execution_id,
        )

        return ReviewOutcome(
            review_id=review.id,
            decision=ReviewStatus.REQUESTED.value,
            verification_status=VerificationStatus.REVIEW_REQUIRED,
            reason=reason,
        )

    async def complete_review(
        self,
        *,
        review_id: str,
        decision: str,
        notes: str = "",
    ) -> ReviewOutcome:
        """Complete a human review with a decision.

        Args:
            review_id: The review to complete.
            decision: APPROVED, REJECTED, or RETURNED_FOR_REWORK.
            notes: Human reviewer's notes.

        Returns:
            ReviewOutcome with the mapped verification status
            and any required recovery action.
        """
        # Record the decision
        review = await self._manager.decide_review(
            review_id=review_id,
            decision=decision,
            notes=notes,
        )

        if not review:
            return ReviewOutcome(
                review_id=review_id,
                decision="ERROR",
                verification_status=VerificationStatus.INCONCLUSIVE,
                reason="Review not found or invalid state transition.",
            )

        # Map to verification status
        verification_status = self._manager.review_to_verification_status(
            review,
        )

        # Determine recovery action based on decision
        recovery_action = self._decision_to_recovery(decision)

        logger.info(
            "review_workflow_completed",
            review_id=review_id,
            decision=decision,
            verification_status=verification_status.value,
            recovery_action=recovery_action.value if recovery_action else None,
        )

        return ReviewOutcome(
            review_id=review_id,
            decision=decision,
            verification_status=verification_status,
            recovery_action=recovery_action,
            reason=f"Human review: {decision}",
            notes=notes,
        )

    async def handle_expired_reviews(
        self,
    ) -> int:
        """Expire stale reviews and return the count.

        Should be called periodically by a background worker.
        """
        count = await self._manager.expire_stale_reviews()
        if count > 0:
            logger.warning(
                "expired_reviews_handled",
                count=count,
            )
        return count

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decision_to_recovery(
        decision: str,
    ) -> VerificationAction | None:
        """Map a review decision to a recovery action."""
        if decision == ReviewStatus.APPROVED.value:
            return VerificationAction.ACCEPT
        elif decision == ReviewStatus.REJECTED.value:
            return VerificationAction.REGENERATE
        elif decision == ReviewStatus.RETURNED_FOR_REWORK.value:
            return VerificationAction.RESEARCH_MORE
        elif decision == ReviewStatus.EXPIRED.value:
            return VerificationAction.HUMAN_REVIEW
        return None