"""
Review Request Manager (C6 §42-44).

Manages the lifecycle of human review requests:
  - Creation from verification failures
  - Assignment to reviewers
  - Decision recording
  - Expiry handling

Review Lifecycle (C6 §44):
    REQUESTED → ASSIGNED → IN_REVIEW → APPROVED
                                    → REJECTED
                                    → RETURNED_FOR_REWORK
                                    → EXPIRED
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import (
    EventType,
    ReviewStatus,
    VerificationStatus,
)

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.reliability import ReviewRequestORM


logger = get_logger("dsrt.verification.review")


class ReviewManager:
    """Manages human review request lifecycle (C6 §43).

    Usage:
        mgr = ReviewManager(session, kernel)
        review = await mgr.create_review(
            verification_run_id="vrn_1",
            reason="Evidence conflict requires human judgment",
            reviewer_role="admin",
        )
        await mgr.assign_review(review.id, user_id="usr_admin")
        await mgr.decide_review(review.id, decision="APPROVED", notes="Verified manually")
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
        default_expiry_hours: int = 24,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._default_expiry = default_expiry_hours

    async def create_review(
        self,
        *,
        verification_run_id: str,
        reason: str,
        reviewer_role: str = "admin",
        evidence_refs: list[str] | None = None,
        execution_id: str | None = None,
    ) -> ReviewRequestORM:
        """Create a new human review request (C6 §43).

        Args:
            verification_run_id: The verification that needs review.
            reason: Why human review is needed.
            reviewer_role: Minimum role required to review.
            evidence_refs: Related evidence IDs for the reviewer.
            execution_id: The parent execution (for event emission).

        Returns:
            The persisted ReviewRequestORM.
        """
        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=self._default_expiry,
        )

        review = ReviewRequestORM(
            id=new_id(IdPrefix.REVIEW_REQUEST),
            verification_run_id=verification_run_id,
            reviewer_role=reviewer_role,
            reason=reason,
            evidence_refs=evidence_refs or [],
            status=ReviewStatus.REQUESTED.value,
            expires_at=expires_at,
        )
        self._session.add(review)
        await self._session.flush()

        # Emit event
        if execution_id:
            await self._emit_event(
                execution_id,
                EventType.AGENT_EVENT,
                {
                    "review_event": "REVIEW_REQUESTED",
                    "review_id": review.id,
                    "verification_run_id": verification_run_id,
                    "reviewer_role": reviewer_role,
                    "expires_at": expires_at.isoformat(),
                },
            )

        logger.info(
            "review_request_created",
            review_id=review.id,
            verification_run_id=verification_run_id,
            reviewer_role=reviewer_role,
            expires_at=expires_at.isoformat(),
        )

        return review

    async def assign_review(
        self,
        review_id: str,
        user_id: str,
    ) -> ReviewRequestORM | None:
        """Assign a review to a specific user.

        Transitions: REQUESTED → ASSIGNED
        """
        review = await self.get_review(review_id)
        if not review:
            return None

        if review.status not in (
            ReviewStatus.REQUESTED.value,
            ReviewStatus.RETURNED_FOR_REWORK.value,
        ):
            logger.warning(
                "review_assign_invalid_state",
                review_id=review_id,
                current_status=review.status,
            )
            return None

        review.status = ReviewStatus.ASSIGNED.value
        review.assigned_to = user_id
        await self._session.flush()

        logger.info(
            "review_assigned",
            review_id=review_id,
            user_id=user_id,
        )

        return review

    async def start_review(
        self,
        review_id: str,
    ) -> ReviewRequestORM | None:
        """Mark a review as in-progress.

        Transitions: ASSIGNED → IN_REVIEW
        """
        review = await self.get_review(review_id)
        if not review:
            return None

        if review.status != ReviewStatus.ASSIGNED.value:
            logger.warning(
                "review_start_invalid_state",
                review_id=review_id,
                current_status=review.status,
            )
            return None

        review.status = ReviewStatus.IN_REVIEW.value
        await self._session.flush()

        logger.info("review_started", review_id=review_id)
        return review

    async def decide_review(
        self,
        review_id: str,
        decision: str,
        notes: str = "",
    ) -> ReviewRequestORM | None:
        """Record a human decision on a review (C6 §43).

        Valid decisions: APPROVED, REJECTED, RETURNED_FOR_REWORK

        Transitions:
            IN_REVIEW → APPROVED
            IN_REVIEW → REJECTED
            IN_REVIEW → RETURNED_FOR_REWORK
        """
        review = await self.get_review(review_id)
        if not review:
            return None

        valid_decisions = {
            ReviewStatus.APPROVED.value,
            ReviewStatus.REJECTED.value,
            ReviewStatus.RETURNED_FOR_REWORK.value,
        }
        if decision not in valid_decisions:
            logger.warning(
                "review_invalid_decision",
                review_id=review_id,
                decision=decision,
                valid=sorted(valid_decisions),
            )
            return None

        if review.status not in (
            ReviewStatus.IN_REVIEW.value,
            ReviewStatus.ASSIGNED.value,
        ):
            logger.warning(
                "review_decide_invalid_state",
                review_id=review_id,
                current_status=review.status,
            )
            return None

        review.status = decision
        review.decision = decision
        review.notes = notes
        await self._session.flush()

        logger.info(
            "review_decided",
            review_id=review_id,
            decision=decision,
        )

        return review

    async def expire_review(
        self,
        review_id: str,
    ) -> ReviewRequestORM | None:
        """Mark a review as expired.

        Transitions: REQUESTED/ASSIGNED/IN_REVIEW → EXPIRED
        """
        review = await self.get_review(review_id)
        if not review:
            return None

        if review.status in (
            ReviewStatus.APPROVED.value,
            ReviewStatus.REJECTED.value,
            ReviewStatus.EXPIRED.value,
        ):
            return review  # Already terminal

        review.status = ReviewStatus.EXPIRED.value
        review.decision = ReviewStatus.EXPIRED.value
        await self._session.flush()

        logger.info("review_expired", review_id=review_id)
        return review

    async def get_review(
        self, review_id: str,
    ) -> ReviewRequestORM | None:
        """Get a review request by ID."""
        stmt = select(ReviewRequestORM).where(
            ReviewRequestORM.id == review_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_reviews_for_verification(
        self,
        verification_run_id: str,
    ) -> list[ReviewRequestORM]:
        """List all reviews for a verification run."""
        stmt = (
            select(ReviewRequestORM)
            .where(
                ReviewRequestORM.verification_run_id == verification_run_id,
            )
            .order_by(ReviewRequestORM.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_pending_reviews(
        self,
        limit: int = 50,
    ) -> list[ReviewRequestORM]:
        """List all pending (non-terminal) reviews."""
        terminal = {
            ReviewStatus.APPROVED.value,
            ReviewStatus.REJECTED.value,
            ReviewStatus.EXPIRED.value,
        }
        stmt = (
            select(ReviewRequestORM)
            .where(ReviewRequestORM.status.notin_(terminal))
            .order_by(ReviewRequestORM.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def expire_stale_reviews(self) -> int:
        """Expire all reviews past their expiry date.

        Returns the count of expired reviews.
        """
        now = datetime.now(timezone.utc)
        stale = await self.list_pending_reviews(limit=1000)
        count = 0

        for review in stale:
            if review.expires_at and review.expires_at <= now:
                await self.expire_review(review.id)
                count += 1

        if count > 0:
            logger.info("stale_reviews_expired", count=count)

        return count

    def review_to_verification_status(
        self,
        review: ReviewRequestORM,
    ) -> VerificationStatus:
        """Map a review decision to a verification status.

        APPROVED → PASSED
        REJECTED → FAILED
        RETURNED_FOR_REWORK → FAILED (triggers recovery)
        EXPIRED → INCONCLUSIVE
        Other → INCONCLUSIVE
        """
        mapping = {
            ReviewStatus.APPROVED.value: VerificationStatus.PASSED,
            ReviewStatus.REJECTED.value: VerificationStatus.FAILED,
            ReviewStatus.RETURNED_FOR_REWORK.value: VerificationStatus.FAILED,
            ReviewStatus.EXPIRED.value: VerificationStatus.INCONCLUSIVE,
        }
        return mapping.get(
            review.status,
            VerificationStatus.INCONCLUSIVE,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.verification.review",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "review_event_emission_failed",
                execution_id=execution_id,
                error=str(e),
            )