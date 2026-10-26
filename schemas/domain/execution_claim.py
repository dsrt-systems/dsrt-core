"""
DSRT C10 Execution Claim Classification (D10 refinement, INV-34).

Core distinguishes between what a model SAID it did and what the
system can PROVE it did.

Classification states:
  GENERATED   — Model produced output claiming action; no qualifying evidence
  INITIATED   — Action was dispatched (e.g. API call sent) but completion unconfirmed
  EXECUTED    — Tool invocation succeeded AND produced qualifying evidence
  UNVERIFIED  — No claim detected / not applicable

Promotion rules:
  Default classification is GENERATED.
  To be promoted to EXECUTED, the claim must link to one or more
  pieces of evidence that satisfy the EvidenceQualification criteria
  (e.g. tool_execution.status == COMPLETED AND produced observations).
  To be promoted to INITIATED, the claim must link to a tool invocation
  that was dispatched but whose terminal result was non-COMPLETED or absent.

This classification is OWNED BY CORE. Agents cannot self-classify.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema


class ClaimClassification(str, Enum):
    """Core-owned classification of an agent's execution claim (D10)."""
    GENERATED = "GENERATED"
    INITIATED = "INITIATED"
    EXECUTED = "EXECUTED"
    UNVERIFIED = "UNVERIFIED"


class ClaimActionType(str, Enum):
    """What kind of action the claim describes."""
    DATA_RETRIEVAL = "DATA_RETRIEVAL"
    COMPUTATION = "COMPUTATION"
    FILE_WRITE = "FILE_WRITE"
    FILE_READ = "FILE_READ"
    EXTERNAL_API_CALL = "EXTERNAL_API_CALL"
    DATABASE_WRITE = "DATABASE_WRITE"
    DATABASE_READ = "DATABASE_READ"
    EMAIL_SEND = "EMAIL_SEND"
    MESSAGE_SEND = "MESSAGE_SEND"
    TRANSACTION = "TRANSACTION"
    OTHER = "OTHER"


class EvidenceQualificationLevel(str, Enum):
    """Required evidence to promote GENERATED → EXECUTED."""
    NONE = "NONE"                        # No evidence present
    INVOCATION_RECORDED = "INVOCATION_RECORDED"  # Tool was called (not enough)
    INVOCATION_SUCCEEDED = "INVOCATION_SUCCEEDED"  # Tool returned success
    OBSERVATION_CAPTURED = "OBSERVATION_CAPTURED"  # Tool produced observations
    ARTIFACT_PRODUCED = "ARTIFACT_PRODUCED"      # Tool wrote a verified artifact
    EXTERNAL_CONFIRMATION = "EXTERNAL_CONFIRMATION"  # Third-party receipt/ack


class ExecutionClaim(DSRTImmutableSchema):
    """A single classified claim about something an execution did (D10, INV-34)."""
    id: str
    execution_trace_id: str
    step_id: str | None = None

    # What the agent claimed (verbatim or summarized)
    claim_text: str
    action_type: ClaimActionType

    # Core-owned classification
    classification: ClaimClassification

    # Evidence trail
    evidence_level: EvidenceQualificationLevel
    linked_tool_execution_ids: list[str] = Field(default_factory=list)
    linked_observation_ids: list[str] = Field(default_factory=list)
    linked_artifact_ids: list[str] = Field(default_factory=list)

    # Classification rationale (human-auditable)
    classification_rationale: str

    # If the claim describes an irreversible/external action, we are
    # EXTRA strict about promotion to EXECUTED
    is_irreversible: bool = False
    requires_external_confirmation: bool = False

    # Qualification criteria that must hold for promotion to EXECUTED,
    # per the agent manifest or default policy
    required_evidence_level: EvidenceQualificationLevel = (
        EvidenceQualificationLevel.OBSERVATION_CAPTURED
    )

    classified_at: datetime
    classified_by: str = "dsrt.core.c10.classifier"


class ExecutionClaimCreate(DSRTSchema):
    execution_trace_id: str
    step_id: str | None = None
    claim_text: str
    action_type: ClaimActionType
    is_irreversible: bool = False
    requires_external_confirmation: bool = False
    required_evidence_level: EvidenceQualificationLevel = (
        EvidenceQualificationLevel.OBSERVATION_CAPTURED
    )


class ClaimClassificationRequest(DSRTSchema):
    """Request to the ClaimClassifier."""
    execution_trace_id: str
    step_id: str | None = None
    claim_text: str
    action_type: ClaimActionType
    tool_execution_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    is_irreversible: bool = False
    requires_external_confirmation: bool = False
    required_evidence_level: EvidenceQualificationLevel = (
        EvidenceQualificationLevel.OBSERVATION_CAPTURED
    )