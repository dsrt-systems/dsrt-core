"""
Verification Policy Manager (C6 §10, §45-46).

Resolves and applies verification policies based on risk level,
organization configuration, and task requirements.

Policy Hierarchy (C6 §46):
    Organization Policy
        ↓
    Project Policy
        ↓
    Task Policy
        ↓
    Execution Policy
        ↓
    Verification Policy

Most restrictive applicable policy wins.
"""

from __future__ import annotations

from typing import Any

from schemas.domain.verification import (
    FailureAction,
    VerificationPolicy,
    VerificationThresholds,
)

from core.observability.logging import get_logger


logger = get_logger("dsrt.verification.policy")


# Built-in policies for common scenarios
BUILTIN_POLICIES: dict[str, VerificationPolicy] = {
    "minimal": VerificationPolicy(
        id="minimal",
        version="1.0",
        name="Minimal Verification",
        description="Schema and artifact integrity only.",
        required_checks=["SCHEMA_VALID", "ARTIFACT_INTEGRITY"],
        optional_checks=[],
        risk_level="low",
        deterministic_must_pass=True,
    ),
    "standard": VerificationPolicy(
        id="standard",
        version="1.0",
        name="Standard Verification",
        description="Schema, artifact, constraints, and completeness.",
        required_checks=[
            "SCHEMA_VALID",
            "ARTIFACT_INTEGRITY",
            "CONSTRAINT_SATISFIED",
            "COMPLETENESS",
        ],
        optional_checks=[
            "STATE_CONSISTENT",
            "TOOL_RESULT_VALID",
        ],
        risk_level="medium",
        deterministic_must_pass=True,
    ),
    "research_v1": VerificationPolicy(
        id="research_v1",
        version="1.0",
        name="Research Verification",
        description="Full research verification with evidence and citations.",
        required_checks=[
            "SCHEMA_VALID",
            "ARTIFACT_INTEGRITY",
            "CONSTRAINT_SATISFIED",
            "COMPLETENESS",
            "CLAIM_SUPPORTED",
            "CITATION_VALID",
        ],
        optional_checks=[
            "CONTRADICTION_CHECK",
            "STATE_CONSISTENT",
            "TOOL_RESULT_VALID",
            "SEMANTIC_CORRECTNESS",
        ],
        thresholds=VerificationThresholds(
            evidence_coverage=0.85,
            completeness_coverage=0.80,
        ),
        failure_actions={
            "missing_evidence": FailureAction(
                action="RESEARCH_MORE",
                reason="Insufficient evidence for claims.",
            ),
            "artifact_invalid": FailureAction(
                action="REGENERATE",
                reason="Artifact failed integrity check.",
            ),
            "uncertain": FailureAction(
                action="HUMAN_REVIEW",
                reason="Verification inconclusive.",
                requires_human=True,
            ),
        },
        risk_level="high",
        deterministic_must_pass=True,
    ),
    "software_v1": VerificationPolicy(
        id="software_v1",
        version="1.0",
        name="Software Verification",
        description="Code artifact verification with schema and constraints.",
        required_checks=[
            "SCHEMA_VALID",
            "ARTIFACT_INTEGRITY",
            "CONSTRAINT_SATISFIED",
        ],
        optional_checks=[
            "TOOL_RESULT_VALID",
            "STATE_CONSISTENT",
        ],
        risk_level="medium",
        deterministic_must_pass=True,
    ),
    "data_v1": VerificationPolicy(
        id="data_v1",
        version="1.0",
        name="Data Verification",
        description="Dataset verification with schema and completeness.",
        required_checks=[
            "SCHEMA_VALID",
            "ARTIFACT_INTEGRITY",
            "COMPLETENESS",
            "CONSTRAINT_SATISFIED",
        ],
        optional_checks=[
            "STATE_CONSISTENT",
        ],
        risk_level="medium",
        deterministic_must_pass=True,
    ),
}


class VerificationPolicyManager:
    """Manages verification policy resolution and application (C6 §46).

    Usage:
        manager = VerificationPolicyManager()
        policy = manager.resolve("research_v1")
        # or
        policy = manager.resolve_for_risk("high")
    """

    def __init__(
        self,
        custom_policies: dict[str, VerificationPolicy] | None = None,
    ) -> None:
        self._policies: dict[str, VerificationPolicy] = dict(BUILTIN_POLICIES)
        if custom_policies:
            self._policies.update(custom_policies)

    def resolve(self, policy_id: str) -> VerificationPolicy | None:
        """Resolve a policy by ID.

        Returns None if the policy is not found.
        """
        policy = self._policies.get(policy_id)
        if policy:
            logger.debug(
                "policy_resolved",
                policy_id=policy_id,
                risk_level=policy.risk_level,
                required_checks=len(policy.required_checks),
            )
        return policy

    def resolve_for_risk(
        self, risk_level: str,
    ) -> VerificationPolicy:
        """Resolve the default policy for a risk level (C6 §45).

        Low → minimal
        Medium → standard
        High → research_v1 (most comprehensive)
        """
        risk_map = {
            "low": "minimal",
            "medium": "standard",
            "high": "research_v1",
        }
        policy_id = risk_map.get(risk_level, "standard")
        return self._policies[policy_id]

    def register_policy(self, policy: VerificationPolicy) -> None:
        """Register a custom verification policy."""
        self._policies[policy.id] = policy
        logger.info(
            "policy_registered",
            policy_id=policy.id,
            risk_level=policy.risk_level,
        )

    def list_policies(self) -> list[str]:
        """List all registered policy IDs."""
        return list(self._policies.keys())

    def get_policy(self, policy_id: str) -> VerificationPolicy | None:
        """Alias for resolve()."""
        return self.resolve(policy_id)

    def merge_policies(
        self,
        base: VerificationPolicy,
        override: VerificationPolicy,
    ) -> VerificationPolicy:
        """Merge two policies. The override takes precedence (C6 §46).

        Most restrictive applicable policy wins:
          - Required checks are unioned (more checks = more restrictive)
          - Thresholds take the higher value (more restrictive)
          - Risk level takes the higher level
        """
        merged_required = list(set(
            base.required_checks + override.required_checks
        ))
        merged_optional = list(set(
            base.optional_checks + override.optional_checks
        ))
        # Remove from optional if now in required
        merged_optional = [
            c for c in merged_optional if c not in merged_required
        ]

        # Higher threshold = more restrictive
        merged_thresholds = VerificationThresholds(
            evidence_coverage=max(
                base.thresholds.evidence_coverage,
                override.thresholds.evidence_coverage,
            ),
            completeness_coverage=max(
                base.thresholds.completeness_coverage,
                override.thresholds.completeness_coverage,
            ),
            max_verification_attempts=min(
                base.thresholds.max_verification_attempts,
                override.thresholds.max_verification_attempts,
            ),
            max_recovery_cycles=min(
                base.thresholds.max_recovery_cycles,
                override.thresholds.max_recovery_cycles,
            ),
        )

        # Higher risk = more restrictive
        risk_order = {"low": 1, "medium": 2, "high": 3}
        merged_risk = (
            override.risk_level
            if risk_order.get(override.risk_level, 0)
            > risk_order.get(base.risk_level, 0)
            else base.risk_level
        )

        return VerificationPolicy(
            id=f"{base.id}+{override.id}",
            version=override.version,
            name=f"Merged: {base.name} + {override.name}",
            required_checks=merged_required,
            optional_checks=merged_optional,
            thresholds=merged_thresholds,
            failure_actions={**base.failure_actions, **override.failure_actions},
            risk_level=merged_risk,
            deterministic_must_pass=(
                base.deterministic_must_pass
                or override.deterministic_must_pass
            ),
        )