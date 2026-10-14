"""
Verification SDK Contract (C6 §7, §54).

Agents can REQUEST verification and submit evidence.
Core owns the verification infrastructure.
The agent CANNOT mark its own result as verified (C6 §13).

This replaces the C1 stub with the full C6 interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKVerificationResult:
    """Canonical verification result returned to agents."""

    subject_id: str
    policy_id: str
    status: str  # PASSED | PASSED_WITH_WARNINGS | FAILED | INCONCLUSIVE | REVIEW_REQUIRED
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dimensions: dict[str, float] = field(default_factory=dict)
    verification_run_id: str = ""


@dataclass(frozen=True)
class SDKEvidenceResult:
    """Result of attaching evidence to a claim."""

    evidence_id: str
    claim_id: str
    link_type: str
    status: str = "ATTACHED"


class VerificationSDK(Protocol):
    """Verification SDK — independent correctness assessment (C6 §54).

    Agents use this to:
      1. Request verification of their outputs
      2. Attach evidence to claims
      3. Check verification status

    Agents CANNOT:
      - Mark their own results as verified
      - Modify verification policies
      - Access other agents' verification results
    """

    async def verify(
        self,
        subject_id: str,
        policy_id: str,
        subject_type: str = "artifact",
        inputs: dict[str, Any] | None = None,
    ) -> SDKVerificationResult:
        """Request independent verification for a subject under a policy.

        The verification is performed by the Core VerificationEngine,
        not by the agent itself (C6 §13).

        Args:
            subject_id: ID of the artifact, node execution, or claim.
            policy_id: Verification policy to apply.
            subject_type: "artifact", "node_execution", "claim", etc.
            inputs: Additional verification inputs (output, schema, etc.)

        Returns:
            SDKVerificationResult with status and multi-dimensional scores.
        """
        ...

    async def attach_evidence(
        self,
        claim_id: str,
        evidence_ref: str,
        source_type: str = "agent",
        extracted_content: str = "",
        link_type: str = "supports",
    ) -> SDKEvidenceResult:
        """Attach evidence to a claim (C6 §17).

        Args:
            claim_id: The claim to attach evidence to.
            evidence_ref: Reference to the evidence (URL, artifact_id, etc.)
            source_type: "web", "tool_execution", "document", "agent"
            extracted_content: The relevant content from the source.
            link_type: "supports", "contradicts", or "context"

        Returns:
            SDKEvidenceResult with the evidence and link IDs.
        """
        ...

    async def get_verification_status(
        self,
        verification_run_id: str,
    ) -> SDKVerificationResult | None:
        """Check the status of a previous verification request.

        Args:
            verification_run_id: The verification run to check.

        Returns:
            SDKVerificationResult or None if not found.
        """
        ...