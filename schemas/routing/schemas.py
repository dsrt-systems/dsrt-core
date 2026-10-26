# schemas/routing/schemas.py
"""
Pydantic validation schemas for C9 routing API boundaries.

These validate external input before constructing internal contracts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from core.routing.enums import (
    CapabilityImportance,
    EvidenceSourceType,
    FallbackActionType,
    FallbackTriggerType,
    QualityLevel,
    RoutingPriority,
    TaskDomain,
)


# ── Requirement schemas ────────────────────────────────────────────

class CapabilityRequirementSchema(BaseModel):
    """Validates a single capability requirement from API input."""

    capability_id: str = Field(..., min_length=1)
    required: bool = True
    minimum_version: str | None = None
    importance: CapabilityImportance = CapabilityImportance.REQUIRED
    constraints: dict[str, Any] = Field(default_factory=dict)
    verification_required: bool = False


class SecurityRequirementsSchema(BaseModel):
    """Validates security constraints from API input."""

    external_write_actions: bool = False
    external_read_actions: bool = True
    requires_sandbox: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    max_privilege_level: str = "standard"


class ResourceConstraintsSchema(BaseModel):
    """Validates resource constraints from API input."""

    max_cost_usd: float | None = Field(None, ge=0)
    max_duration_seconds: float | None = Field(None, ge=0)
    max_input_tokens: int | None = Field(None, ge=0)
    max_output_tokens: int | None = Field(None, ge=0)
    max_total_tokens: int | None = Field(None, ge=0)
    max_tool_calls: int | None = Field(None, ge=0)


class QualityRequirementsSchema(BaseModel):
    """Validates quality requirements from API input."""

    overall: QualityLevel = QualityLevel.STANDARD
    correctness: QualityLevel = QualityLevel.STANDARD
    evidence_quality: QualityLevel = QualityLevel.STANDARD
    completeness: QualityLevel = QualityLevel.STANDARD


class TaskClassificationSchema(BaseModel):
    """Validates task classification from API input."""

    primary_domain: TaskDomain = TaskDomain.GENERAL
    secondary_domains: list[TaskDomain] = Field(default_factory=list)
    confidence: float = Field(1.0, ge=0.0, le=1.0)


class TaskRequirementsSchema(BaseModel):
    """Validates complete task requirements from API input."""

    task_id: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    classification: TaskClassificationSchema = Field(
        default_factory=TaskClassificationSchema
    )
    capabilities: list[CapabilityRequirementSchema] = Field(
        default_factory=list
    )
    quality: QualityRequirementsSchema = Field(
        default_factory=QualityRequirementsSchema
    )
    resources: ResourceConstraintsSchema = Field(
        default_factory=ResourceConstraintsSchema
    )
    security: SecurityRequirementsSchema = Field(
        default_factory=SecurityRequirementsSchema
    )
    preferred_tools: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    output_type: str = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Policy schemas ─────────────────────────────────────────────────

class RoutingConstraintsSchema(BaseModel):
    """Validates routing constraints from API input."""

    allowed_models: list[str] = Field(default_factory=list)
    denied_models: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    denied_agents: list[str] = Field(default_factory=list)
    allowed_providers: list[str] = Field(default_factory=list)
    denied_providers: list[str] = Field(default_factory=list)
    external_write_actions: bool = False
    max_cost_usd: float | None = Field(None, ge=0)
    max_latency_seconds: float | None = Field(None, ge=0)
    required_security_level: str | None = None


class RoutingPreferencesSchema(BaseModel):
    """Validates routing preferences from API input."""

    quality_priority: RoutingPriority = RoutingPriority.MEDIUM
    cost_priority: RoutingPriority = RoutingPriority.MEDIUM
    latency_priority: RoutingPriority = RoutingPriority.MEDIUM
    reliability_priority: RoutingPriority = RoutingPriority.MEDIUM


class RoutingPolicySchema(BaseModel):
    """Validates a complete routing policy from API input."""

    policy_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    version: str = "1"
    constraints: RoutingConstraintsSchema = Field(
        default_factory=RoutingConstraintsSchema
    )
    preferences: RoutingPreferencesSchema = Field(
        default_factory=RoutingPreferencesSchema
    )
    description: str = ""


class RoutingProfileSchema(BaseModel):
    """Validates a routing profile from API input."""

    profile_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    quality_priority: RoutingPriority = RoutingPriority.MEDIUM
    cost_priority: RoutingPriority = RoutingPriority.MEDIUM
    latency_priority: RoutingPriority = RoutingPriority.MEDIUM
    reliability_priority: RoutingPriority = RoutingPriority.MEDIUM
    description: str = ""


# ── Fallback schemas ───────────────────────────────────────────────

class FallbackPolicySchema(BaseModel):
    """Validates a fallback policy from API input."""

    policy_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    triggers: list[FallbackTriggerType] = Field(default_factory=list)
    action: FallbackActionType = FallbackActionType.RETRY
    fallback_candidates: list[str] = Field(default_factory=list)
    max_attempts: int = Field(3, ge=1)
    backoff_seconds: float = Field(1.0, ge=0)


# ── Evidence schemas ───────────────────────────────────────────────

class RoutingEvidenceSchema(BaseModel):
    """Validates routing evidence from API input."""

    source_type: EvidenceSourceType
    benchmark_id: str | None = None
    benchmark_version: str | None = None
    agent_version: str | None = None
    model_version: str | None = None
    world_version: str | None = None
    sample_count: int = Field(0, ge=0)
    metrics: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None