"""
Base Check Interface (C6 §11).

All verification checks implement this abstract base class.
The VerificationEngine calls execute() on each registered check.

Design:
  - Checks are stateless and reusable
  - Checks receive inputs via the `inputs` dict (not direct DB access)
  - Checks return a VerificationCheckResult
  - Checks must be deterministic (same inputs → same output)
  - Checks must NOT call LLMs (that's the semantic verifier's job)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from schemas.domain.enums import UncertaintyLevel, VerificationStatus
from schemas.domain.verification import VerificationCheckResult, VerificationPolicy


class BaseCheck(ABC):
    """Abstract base class for all deterministic verification checks."""

    @property
    @abstractmethod
    def check_type(self) -> str:
        """The CheckType enum value this check handles."""
        ...

    @property
    def evaluator_type(self) -> str:
        """How this check evaluates. Default: deterministic."""
        return "deterministic"

    @abstractmethod
    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ) -> VerificationCheckResult:
        """Execute the check and return a result.

        Args:
            subject_type: What is being verified (artifact, node_execution, etc.)
            subject_id: The ID of the subject.
            inputs: Verification inputs from the request. Contents vary by
                    subject_type but typically include:
                      - "output": The produced output (dict, str, etc.)
                      - "expected_schema": JSON schema to validate against
                      - "requirements": List of required fields/sections
                      - "constraints": List of constraint dicts
                      - "state": Shared state snapshot
                      - "tool_results": List of tool execution results
                      - "claims": List of extracted claims
                      - "evidence": List of evidence items
            policy: The active verification policy.

        Returns:
            VerificationCheckResult with status, summary, and details.
        """
        ...

    def _passed(
        self,
        summary: str = "",
        details: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> VerificationCheckResult:
        """Helper to create a PASSED result."""
        return VerificationCheckResult(
            check_id="",  # Assigned by engine
            check_type=self.check_type,
            evaluator=self.evaluator_type,
            required=True,
            status=VerificationStatus.PASSED,
            summary=summary or f"{self.check_type} check passed.",
            details=details or {},
            evidence_refs=evidence_refs or [],
            uncertainty=UncertaintyLevel.CERTAIN,
        )

    def _failed(
        self,
        summary: str,
        details: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> VerificationCheckResult:
        """Helper to create a FAILED result."""
        return VerificationCheckResult(
            check_id="",
            check_type=self.check_type,
            evaluator=self.evaluator_type,
            required=True,
            status=VerificationStatus.FAILED,
            summary=summary,
            details=details or {},
            evidence_refs=evidence_refs or [],
            uncertainty=UncertaintyLevel.CERTAIN,
        )

    def _warning(
        self,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> VerificationCheckResult:
        """Helper to create a PASSED_WITH_WARNINGS result."""
        return VerificationCheckResult(
            check_id="",
            check_type=self.check_type,
            evaluator=self.evaluator_type,
            required=True,
            status=VerificationStatus.PASSED_WITH_WARNINGS,
            summary=summary,
            details=details or {},
            uncertainty=UncertaintyLevel.SUPPORTED,
        )

    def _inconclusive(
        self,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> VerificationCheckResult:
        """Helper to create an INCONCLUSIVE result."""
        return VerificationCheckResult(
            check_id="",
            check_type=self.check_type,
            evaluator=self.evaluator_type,
            required=True,
            status=VerificationStatus.INCONCLUSIVE,
            summary=summary,
            details=details or {},
            uncertainty=UncertaintyLevel.UNKNOWN,
        )