"""
Verification Request Processor (C6 §8).

Validates and normalizes incoming verification requests before
they are passed to the VerificationEngine.
"""

from __future__ import annotations

from typing import Any

from schemas.domain.verification import VerificationRequest

from core.api.errors.exceptions import ValidationError
from core.observability.logging import get_logger


logger = get_logger("dsrt.verification.request")

# Valid subject types that can be verified
VALID_SUBJECT_TYPES = frozenset({
    "artifact",
    "node_execution",
    "execution",
    "task",
    "claim",
    "tool_result",
    "state",
    "evidence",
})


class VerificationRequestProcessor:
    """Validates and normalizes verification requests."""

    @staticmethod
    def validate(request: VerificationRequest) -> None:
        """Validate a verification request.

        Raises ValidationError if the request is invalid.
        """
        # 1. Subject type validation
        if request.subject_type not in VALID_SUBJECT_TYPES:
            raise ValidationError(
                f"Invalid subject_type '{request.subject_type}'. "
                f"Must be one of: {sorted(VALID_SUBJECT_TYPES)}"
            )

        # 2. Subject ID validation
        if not request.subject_id or not request.subject_id.strip():
            raise ValidationError("subject_id must not be empty.")

        # 3. Policy ID validation
        if not request.policy_id or not request.policy_id.strip():
            raise ValidationError("policy_id must not be empty.")

        # 4. Inputs validation (if provided)
        if request.inputs and not isinstance(request.inputs, dict):
            raise ValidationError("inputs must be a dict.")

        logger.debug(
            "verification_request_validated",
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            policy_id=request.policy_id,
        )

    @staticmethod
    def normalize(request: VerificationRequest) -> VerificationRequest:
        """Normalize a verification request to canonical form.

        Ensures all optional fields have defaults and values are clean.
        """
        return VerificationRequest(
            subject_type=request.subject_type.strip().lower(),
            subject_id=request.subject_id.strip(),
            policy_id=request.policy_id.strip(),
            inputs=request.inputs or {},
            evidence_refs=request.evidence_refs or [],
            constraints=request.constraints or [],
            context_ref=request.context_ref,
            metadata=request.metadata or {},
        )

    @classmethod
    def process(cls, request: VerificationRequest) -> VerificationRequest:
        """Validate and normalize a request in one step."""
        cls.validate(request)
        return cls.normalize(request)