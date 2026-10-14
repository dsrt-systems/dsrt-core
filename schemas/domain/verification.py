"""
Verification & Reliability Schemas (C1 + C6).

C1 schemas are preserved for backward compatibility.
C6 schemas extend the verification fabric with policies, claims,
evidence, constraints, reliability incidents, and human review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema
from schemas.domain.enums import (
    CheckType,
    ClaimStatus,
    EvidenceStatus,
    IncidentCategory,
    IncidentSeverity,
    ReviewStatus,
    UncertaintyLevel,
    VerificationAction,
    VerificationStatus,
)


# =============================================================================
# C1 Verification Schemas (PRESERVED — backward compatible)
# =============================================================================


class VerificationRequest(DSRTSchema):
    """C1 verification request — extended in C6 with optional fields."""
    subject_type: str = Field(min_length=1, max_length=50)
    subject_id: str = Field(min_length=1, max_length=64)
    policy_id: str = Field(min_length=1, max_length=200)
    # C6 extensions (optional, backward compatible)
    inputs: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    context_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationCheck(DSRTSchema):
    """C1 verification check — preserved for backward compatibility."""
    check_type: str
    status: VerificationStatus
    summary: str = ""
    details: dict = Field(default_factory=dict)
    evidence_refs: list = Field(default_factory=list)


class VerificationResult(DSRTSchema):
    """C1 verification result — preserved for backward compatibility."""
    id: str
    verification_run_id: str
    check_type: str
    status: VerificationStatus
    summary: str
    details: dict
    evidence_refs: list


class VerificationRun(TimestampedSchema):
    """C1 verification run — preserved for backward compatibility."""
    id: str
    execution_id: str
    subject_type: str
    subject_id: str
    policy_id: str
    status: VerificationStatus
    engine_version: str
    started_at: datetime | None
    completed_at: datetime | None
    results: list[VerificationResult] = Field(default_factory=list)


# =============================================================================
# C6 Verification Policy (C6 §10, §45-46)
# =============================================================================


class VerificationThresholds(DSRTSchema):
    """Numeric thresholds for verification checks."""
    evidence_coverage: float = Field(default=0.9, ge=0.0, le=1.0)
    completeness_coverage: float = Field(default=0.8, ge=0.0, le=1.0)
    max_verification_attempts: int = Field(default=3, ge=1)
    max_recovery_cycles: int = Field(default=3, ge=1)
    max_replans: int = Field(default=5, ge=1)


class FailureAction(DSRTSchema):
    """Maps a failure type to a recovery action (C6 §10)."""
    action: VerificationAction
    reason: str = ""
    requires_human: bool = False


class VerificationPolicy(DSRTSchema):
    """Configurable verification policy (C6 §10, §45).

    Defines what must be demonstrated — not merely how a model feels.
    """
    id: str = Field(..., min_length=1, max_length=200)
    version: str = "1.0"
    name: str = ""
    description: str = ""

    # Required check types (from CheckType enum)
    required_checks: list[str] = Field(default_factory=list)

    # Optional checks (run but don't fail the verification)
    optional_checks: list[str] = Field(default_factory=list)

    # Thresholds
    thresholds: VerificationThresholds = Field(default_factory=VerificationThresholds)

    # Failure → Action mapping
    failure_actions: dict[str, FailureAction] = Field(default_factory=dict)

    # Risk level determines verification depth
    risk_level: str = Field(default="medium", description="low|medium|high")

    # Deterministic checks must pass (cannot be overridden by semantic)
    deterministic_must_pass: bool = True

    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# C6 Verification Check Result (C6 §11-12)
# =============================================================================


class VerificationCheckResult(DSRTSchema):
    """Result of a single verification check (C6 §11)."""
    check_id: str
    check_type: str  # CheckType value
    evaluator: str = Field(default="deterministic", description="deterministic|model|human|hybrid")
    required: bool = True
    status: VerificationStatus = VerificationStatus.PENDING
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    uncertainty: UncertaintyLevel = UncertaintyLevel.UNKNOWN
    duration_ms: int = 0


# =============================================================================
# C6 Full Verification Result (C6 §9)
# =============================================================================


class C6VerificationResult(TimestampedSchema):
    """Complete verification result with multi-dimensional assessment (C6 §9).

    Preserves independent dimensions — never collapses to a single score.
    """
    id: str
    verification_run_id: str
    status: VerificationStatus

    # Individual check results
    checks: list[VerificationCheckResult] = Field(default_factory=list)

    # Evidence chain
    evidence_refs: list[str] = Field(default_factory=list)

    # Failures and warnings
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # Required recovery actions
    required_actions: list[VerificationAction] = Field(default_factory=list)

    # Multi-dimensional scores (NOT a single quality score)
    dimensions: dict[str, float] = Field(default_factory=dict)

    # Provenance
    policy_id: str = ""
    engine_version: str = "1.0.0"
    verifier_model: str | None = None
    evidence_snapshot: str | None = None


# =============================================================================
# C6 Evidence (C6 §16-17)
# =============================================================================


class Evidence(DSRTSchema):
    """First-class evidence object (C6 §16)."""
    id: str
    source_type: str  # "web", "tool_execution", "document", "database", "agent"
    source_ref: str  # URL, artifact_id, tool_execution_id, etc.
    location: str | None = None
    extracted_content: str = ""
    captured_at: datetime | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    verification_status: EvidenceStatus = EvidenceStatus.CAPTURED


class EvidenceReference(DSRTImmutableSchema):
    """Lightweight reference to an evidence item."""
    evidence_id: str
    source_type: str
    source_ref: str
    relationship: str = "supports"  # supports|contradicts|context


# =============================================================================
# C6 Claims (C6 §14-15, §18-19)
# =============================================================================


class Claim(DSRTSchema):
    """A structured claim extracted from an agent's output (C6 §14)."""
    id: str
    execution_id: str
    node_execution_id: str | None = None
    statement: str = Field(..., min_length=1)
    source_refs: list[str] = Field(default_factory=list)
    importance: str = Field(default="normal", description="low|normal|high|critical")
    status: ClaimStatus = ClaimStatus.EXTRACTED
    uncertainty: UncertaintyLevel = UncertaintyLevel.UNKNOWN
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimVerification(DSRTSchema):
    """Result of verifying a single claim (C6 §15)."""
    id: str
    claim_id: str
    verification_run_id: str
    status: ClaimStatus
    reason: str = ""
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    uncertainty: UncertaintyLevel = UncertaintyLevel.UNKNOWN


# =============================================================================
# C6 Constraints (C6 §22)
# =============================================================================


class Constraint(DSRTSchema):
    """An executable verification constraint (C6 §22)."""
    id: str
    description: str
    constraint_type: str  # "temporal", "budget", "policy", "schema", "custom"
    expression: dict[str, Any] = Field(default_factory=dict)
    severity: IncidentSeverity = IncidentSeverity.MEDIUM


class ConstraintResult(DSRTSchema):
    """Result of evaluating a constraint."""
    constraint_id: str
    satisfied: bool
    actual_value: Any = None
    expected_value: Any = None
    details: str = ""


# =============================================================================
# C6 Reliability (C6 §36-39)
# =============================================================================


class ReliabilityIncident(TimestampedSchema):
    """First-class reliability incident record (C6 §36)."""
    id: str
    execution_id: str
    node_execution_id: str | None = None
    category: IncidentCategory
    severity: IncidentSeverity
    description: str
    detected_by: str  # "verification_engine", "scheduler", "agent", "human"
    recovery_action: VerificationAction | None = None
    resolved: bool = False
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class C6RecoveryDecision(DSRTSchema):
    """Recovery decision driven by verification failure (C6 §39).

    Distinct from C5's RecoveryDecision — this is verification-specific.
    """
    action: VerificationAction
    reason: str
    target_node: str | None = None
    new_constraints: dict[str, Any] = Field(default_factory=dict)
    retry_allowed: bool = True
    requires_human: bool = False
    verification_run_id: str | None = None


# =============================================================================
# C6 Human Review (C6 §42-44)
# =============================================================================


class ReviewRequest(TimestampedSchema):
    """Human review request for inconclusive verifications (C6 §43)."""
    id: str
    verification_run_id: str
    reviewer_role: str = "admin"
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.REQUESTED
    decision: str | None = None
    notes: str | None = None
    assigned_to: str | None = None
    expires_at: datetime | None = None


# =============================================================================
# C6 Confidence (C6 §34)
# =============================================================================


class ConfidenceRecord(DSRTSchema):
    """Provenance-backed confidence assessment (C6 §34).

    Never stores a bare number — always explains why.
    """
    basis: list[str] = Field(default_factory=list)  # e.g., ["source_count", "agreement"]
    generated_by: str = ""  # verifier version
    policy_id: str = ""
    value: float = Field(default=0.5, ge=0.0, le=1.0)
    uncertainty: UncertaintyLevel = UncertaintyLevel.UNKNOWN


# =============================================================================
# C6 Requirements (C6 §20-21)
# =============================================================================


class Requirement(DSRTSchema):
    """A task requirement for completeness verification (C6 §21)."""
    id: str
    description: str
    priority: str = Field(default="required", description="required|optional|nice_to_have")
    verification_policy: str = ""
    mapped_node_key: str | None = None
    satisfied: bool = False
    evidence_refs: list[str] = Field(default_factory=list)