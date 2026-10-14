"""
Failure Classifier (C6 §37).

Classifies verification failures into the 13-category reliability
taxonomy. This is the bridge between verification check results
and reliability incident records.

Taxonomy (C6 §37):
  PROVIDER       — Model provider failures (timeout, rate limit, etc.)
  TOOL           — Tool execution failures
  AGENT          — Agent execution failures
  ORCHESTRATION  — Planning/scheduling/dependency failures
  STATE          — Shared state corruption or inconsistency
  MEMORY         — Memory retrieval or storage failures
  CONTEXT        — Context compilation failures
  EVIDENCE       — Evidence quality or availability failures
  ARTIFACT       — Artifact integrity or format failures
  VERIFICATION   — Verification engine failures
  SECURITY       — Permission or policy violations
  POLICY         — Organizational policy violations
  WORLD          — World/environment failures
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schemas.domain.enums import (
    CheckType,
    IncidentCategory,
    IncidentSeverity,
    VerificationStatus,
)
from schemas.domain.verification import VerificationCheckResult


@dataclass(frozen=True)
class FailureClassification:
    """Result of classifying a verification failure."""
    category: IncidentCategory
    severity: IncidentSeverity
    description: str
    check_type: str
    suggested_action: str  # VerificationAction value


class FailureClassifier:
    """Classifies verification failures into the reliability taxonomy.

    Usage:
        classifier = FailureClassifier()
        classification = classifier.classify(check_result)
        # classification.category == IncidentCategory.ARTIFACT
        # classification.severity == IncidentSeverity.HIGH
    """

    # Maps check types to their default incident category
    _CHECK_CATEGORY_MAP: dict[str, IncidentCategory] = {
        CheckType.SCHEMA_VALID.value: IncidentCategory.ARTIFACT,
        CheckType.ARTIFACT_INTEGRITY.value: IncidentCategory.ARTIFACT,
        CheckType.ARTIFACT_PARSEABLE.value: IncidentCategory.ARTIFACT,
        CheckType.CLAIM_SUPPORTED.value: IncidentCategory.EVIDENCE,
        CheckType.CITATION_VALID.value: IncidentCategory.EVIDENCE,
        CheckType.CITATION_PRESENT.value: IncidentCategory.EVIDENCE,
        CheckType.SOURCE_ACCESSIBLE.value: IncidentCategory.EVIDENCE,
        CheckType.CONTRADICTION_CHECK.value: IncidentCategory.EVIDENCE,
        CheckType.COMPLETENESS.value: IncidentCategory.AGENT,
        CheckType.CONSTRAINT_SATISFIED.value: IncidentCategory.POLICY,
        CheckType.STATE_CONSISTENT.value: IncidentCategory.STATE,
        CheckType.TOOL_RESULT_VALID.value: IncidentCategory.TOOL,
        CheckType.SEMANTIC_CORRECTNESS.value: IncidentCategory.AGENT,
        CheckType.POLICY_COMPLIANT.value: IncidentCategory.SECURITY,
    }

    # Maps error code prefixes to incident categories
    _ERROR_CATEGORY_MAP: dict[str, IncidentCategory] = {
        "PROVIDER_": IncidentCategory.PROVIDER,
        "MODEL_": IncidentCategory.PROVIDER,
        "CREDENTIAL_": IncidentCategory.SECURITY,
        "TOOL_": IncidentCategory.TOOL,
        "AGENT_": IncidentCategory.AGENT,
        "MEMORY_": IncidentCategory.MEMORY,
        "CONTEXT_": IncidentCategory.CONTEXT,
        "ENVIRONMENT_": IncidentCategory.WORLD,
        "WORLD_": IncidentCategory.WORLD,
        "PERMISSION_": IncidentCategory.SECURITY,
        "AUTH_": IncidentCategory.SECURITY,
        "RESOURCE_": IncidentCategory.ORCHESTRATION,
        "EXECUTION_": IncidentCategory.ORCHESTRATION,
    }

    def classify(
        self,
        check_result: VerificationCheckResult,
    ) -> FailureClassification:
        """Classify a failed verification check (C6 §37).

        Args:
            check_result: The failed check result to classify.

        Returns:
            FailureClassification with category, severity, and description.
        """
        if check_result.status not in (
            VerificationStatus.FAILED,
            VerificationStatus.INCONCLUSIVE,
        ):
            # Not a failure — return a benign classification
            return FailureClassification(
                category=IncidentCategory.VERIFICATION,
                severity=IncidentSeverity.LOW,
                description=f"Check '{check_result.check_type}' did not fail.",
                check_type=check_result.check_type,
                suggested_action="ACCEPT",
            )

        # 1. Determine category from check type
        category = self._CHECK_CATEGORY_MAP.get(
            check_result.check_type,
            IncidentCategory.VERIFICATION,
        )

        # 2. Override from error details if available
        error_code = check_result.details.get("error_code", "")
        if error_code:
            for prefix, cat in self._ERROR_CATEGORY_MAP.items():
                if error_code.startswith(prefix):
                    category = cat
                    break

        # 3. Determine severity
        severity = self._determine_severity(
            category, check_result,
        )

        # 4. Determine suggested action
        action = self._suggest_action(category, severity)

        # 5. Build description
        description = (
            f"Verification check '{check_result.check_type}' failed: "
            f"{check_result.summary}"
        )

        return FailureClassification(
            category=category,
            severity=severity,
            description=description,
            check_type=check_result.check_type,
            suggested_action=action,
        )

    def classify_error_code(
        self,
        error_code: str,
        error_message: str = "",
        execution_id: str = "",
        node_execution_id: str | None = None,
    ) -> FailureClassification:
        """Classify a raw error code (not from a verification check).

        Used when failures occur outside the verification pipeline
        (e.g., infrastructure errors, agent crashes).
        """
        category = IncidentCategory.VERIFICATION
        for prefix, cat in self._ERROR_CATEGORY_MAP.items():
            if error_code.startswith(prefix):
                category = cat
                break

        severity = IncidentSeverity.MEDIUM
        if category in (IncidentCategory.SECURITY, IncidentCategory.PROVIDER):
            severity = IncidentSeverity.HIGH
        if error_code in ("CREDENTIAL_INVALID", "CREDENTIAL_MISSING"):
            severity = IncidentSeverity.CRITICAL

        action = self._suggest_action(category, severity)

        return FailureClassification(
            category=category,
            severity=severity,
            description=f"Error '{error_code}': {error_message}",
            check_type="INFRASTRUCTURE",
            suggested_action=action,
        )

    def classify_batch(
        self,
        check_results: list[VerificationCheckResult],
    ) -> list[FailureClassification]:
        """Classify all failed checks in a batch."""
        return [
            self.classify(cr)
            for cr in check_results
            if cr.status in (
                VerificationStatus.FAILED,
                VerificationStatus.INCONCLUSIVE,
            )
        ]

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _determine_severity(
        self,
        category: IncidentCategory,
        check_result: VerificationCheckResult,
    ) -> IncidentSeverity:
        """Determine incident severity based on category and context."""
        # Security and provider issues are always high
        if category in (IncidentCategory.SECURITY, IncidentCategory.PROVIDER):
            return IncidentSeverity.HIGH

        # Artifact integrity failures are high
        if category == IncidentCategory.ARTIFACT:
            if check_result.check_type == CheckType.ARTIFACT_INTEGRITY.value:
                return IncidentSeverity.HIGH
            return IncidentSeverity.MEDIUM

        # Evidence failures depend on check type
        if category == IncidentCategory.EVIDENCE:
            if check_result.check_type == CheckType.CONTRADICTION_CHECK.value:
                return IncidentSeverity.HIGH
            return IncidentSeverity.MEDIUM

        # State inconsistency is high
        if category == IncidentCategory.STATE:
            return IncidentSeverity.HIGH

        # Policy violations are high
        if category in (IncidentCategory.POLICY, IncidentCategory.SECURITY):
            return IncidentSeverity.HIGH

        # Everything else is medium
        return IncidentSeverity.MEDIUM

    @staticmethod
    def _suggest_action(
        category: IncidentCategory,
        severity: IncidentSeverity,
    ) -> str:
        """Suggest a recovery action based on category and severity."""
        if severity == IncidentSeverity.CRITICAL:
            return "STOP"

        action_map = {
            IncidentCategory.PROVIDER: "RETRY",
            IncidentCategory.TOOL: "RETRY",
            IncidentCategory.AGENT: "REASSIGN",
            IncidentCategory.ORCHESTRATION: "REPLAN",
            IncidentCategory.STATE: "ROLLBACK",
            IncidentCategory.MEMORY: "RETRY",
            IncidentCategory.CONTEXT: "RETRY",
            IncidentCategory.EVIDENCE: "RESEARCH_MORE",
            IncidentCategory.ARTIFACT: "REGENERATE",
            IncidentCategory.VERIFICATION: "RETRY",
            IncidentCategory.SECURITY: "STOP",
            IncidentCategory.POLICY: "HUMAN_REVIEW",
            IncidentCategory.WORLD: "RETRY",
        }

        return action_map.get(category, "HUMAN_REVIEW")