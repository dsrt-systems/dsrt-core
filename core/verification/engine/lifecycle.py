"""
Verification Lifecycle Manager (C6 §9).

Deterministic state machine for verification runs.

Valid transitions:
  PENDING → RUNNING
  RUNNING → PASSED | PASSED_WITH_WARNINGS | FAILED | INCONCLUSIVE | REVIEW_REQUIRED
  FAILED → RUNNING  (retry)
  INCONCLUSIVE → REVIEW_REQUIRED
  REVIEW_REQUIRED → PASSED | FAILED  (after human decision)

Invalid transitions raise ValueError.
"""

from __future__ import annotations

from schemas.domain.enums import VerificationStatus


# Valid transitions: from_status -> set of allowed to_statuses
_VALID_TRANSITIONS: dict[str, set[str]] = {
    VerificationStatus.PENDING.value: {
        VerificationStatus.RUNNING.value,
    },
    VerificationStatus.RUNNING.value: {
        VerificationStatus.PASSED.value,
        VerificationStatus.PASSED_WITH_WARNINGS.value,
        VerificationStatus.FAILED.value,
        VerificationStatus.INCONCLUSIVE.value,
        VerificationStatus.REVIEW_REQUIRED.value,
    },
    VerificationStatus.FAILED.value: {
        VerificationStatus.RUNNING.value,  # Retry
        VerificationStatus.REVIEW_REQUIRED.value,
    },
    VerificationStatus.INCONCLUSIVE.value: {
        VerificationStatus.REVIEW_REQUIRED.value,
        VerificationStatus.RUNNING.value,  # Re-verify
    },
    VerificationStatus.REVIEW_REQUIRED.value: {
        VerificationStatus.PASSED.value,
        VerificationStatus.PASSED_WITH_WARNINGS.value,
        VerificationStatus.FAILED.value,
    },
    # Terminal states — no outgoing transitions (except via new run)
    VerificationStatus.PASSED.value: set(),
    VerificationStatus.PASSED_WITH_WARNINGS.value: set(),
}

TERMINAL_STATES = frozenset({
    VerificationStatus.PASSED.value,
    VerificationStatus.PASSED_WITH_WARNINGS.value,
})


class VerificationLifecycleManager:
    """Validates and manages verification run state transitions."""

    @staticmethod
    def validate_transition(current: str, target: str) -> None:
        """Validate a state transition. Raises ValueError if invalid."""
        if current == target:
            return  # No-op

        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid verification transition: {current} -> {target}. "
                f"Allowed from {current}: {sorted(allowed)}"
            )

    @staticmethod
    def is_terminal(status: str) -> bool:
        """Check if a status is a terminal (final) state."""
        return status in TERMINAL_STATES

    @staticmethod
    def can_retry(status: str, attempt: int, max_attempts: int) -> bool:
        """Check if a failed verification can be retried."""
        return (
            status in (
                VerificationStatus.FAILED.value,
                VerificationStatus.INCONCLUSIVE.value,
            )
            and attempt < max_attempts
        )

    @staticmethod
    def determine_final_status(
        check_statuses: list[str],
        has_warnings: bool = False,
        requires_review: bool = False,
    ) -> str:
        """Determine the final verification status from individual check results.

        Logic (C6 §32):
          - If any REQUIRED check FAILED → FAILED
          - If requires_review → REVIEW_REQUIRED
          - If all checks PASSED but has_warnings → PASSED_WITH_WARNINGS
          - If all checks PASSED → PASSED
          - If any check INCONCLUSIVE → INCONCLUSIVE
        """
        if requires_review:
            return VerificationStatus.REVIEW_REQUIRED.value

        failed_count = sum(
            1 for s in check_statuses
            if s == VerificationStatus.FAILED.value
        )
        if failed_count > 0:
            return VerificationStatus.FAILED.value

        inconclusive_count = sum(
            1 for s in check_statuses
            if s == VerificationStatus.INCONCLUSIVE.value
        )
        if inconclusive_count > 0:
            return VerificationStatus.INCONCLUSIVE.value

        if has_warnings:
            return VerificationStatus.PASSED_WITH_WARNINGS.value

        return VerificationStatus.PASSED.value