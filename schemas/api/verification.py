"""
Verification API Schemas (C6 §47).

Request/response schemas for the Verification REST API.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import (
    ClaimStatus,
    IncidentSeverity,
    ReviewStatus,
    VerificationAction,
    VerificationStatus,
)


# =============================================================================
# Verification Runs
# =============================================================================


class CreateVerificationRequest(DSRTSchema):
    """POST /api/v1/verifications"""
    subject_type: str = Field(..., min_length=1)
    subject_id: str = Field(..., min_length=1)
    policy_id: str = Field(..., min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class VerificationRunResponse(DSRTSchema):
    """Verification run detail."""
    id: str
    execution_id: str
    subject_type: str
    subject_id: str
    policy_id: str
    status: VerificationStatus
    engine_version: str
    started_at: str | None
    completed_at: str | None
    checks_count: int = 0
    failures_count: int = 0


class VerificationCheckResponse(DSRTSchema):
    """Individual check result."""
    check_id: str
    check_type: str
    evaluator: str
    required: bool
    status: VerificationStatus
    summary: str
    uncertainty: str
    duration_ms: int


# =============================================================================
# Claims
# =============================================================================


class ClaimResponse(DSRTSchema):
    """GET /api/v1/claims/{id}"""
    id: str
    execution_id: str
    statement: str
    importance: str
    status: ClaimStatus
    uncertainty: str
    source_refs: list[str]


class ClaimVerificationResponse(DSRTSchema):
    """GET /api/v1/claims/{id}/verification"""
    claim_id: str
    status: ClaimStatus
    reason: str
    supporting_evidence: list[str]
    contradicting_evidence: list[str]


# =============================================================================
# Evidence
# =============================================================================


class AttachEvidenceRequest(DSRTSchema):
    """POST /api/v1/claims/{id}/evidence"""
    source_type: str
    source_ref: str
    extracted_content: str = ""
    location: str | None = None
    relationship: str = "supports"


# =============================================================================
# Artifacts
# =============================================================================


class ArtifactVerificationResponse(DSRTSchema):
    """GET /api/v1/artifacts/{id}/verification"""
    artifact_id: str
    status: VerificationStatus
    checks: list[VerificationCheckResponse] = Field(default_factory=list)
    integrity_valid: bool = False
    schema_valid: bool = False


# =============================================================================
# Reliability
# =============================================================================


class ReliabilityIncidentResponse(DSRTSchema):
    """Reliability incident detail."""
    id: str
    execution_id: str
    category: str
    severity: IncidentSeverity
    description: str
    detected_by: str
    recovery_action: str | None
    resolved: bool


# =============================================================================
# Review
# =============================================================================


class CreateReviewRequest(DSRTSchema):
    """POST /api/v1/verifications/{id}/review"""
    reviewer_role: str = "admin"
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class ReviewResponse(DSRTSchema):
    """Review status."""
    id: str
    verification_run_id: str
    status: ReviewStatus
    reviewer_role: str
    decision: str | None
    notes: str | None