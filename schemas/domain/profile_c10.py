"""
DSRT C10 Model & Execution Profiles (C10 §5, INV-41, INV-42).

A ModelFingerprint is the deterministic identity of a model:
provider × model_identifier × capability_set × context_window × modality.
Two providers may expose the same underlying model under different
names — fingerprints collapse them.

A ModelProfile is the observed performance characteristics for a
fingerprint. Profiles are TIERED (INV-41): basic profiling is cheap
and automatic; expensive benchmarking is explicit opt-in.

An ExecutionProfile is the per-(fingerprint × agent × task-class)
performance record. Reused profiles are flagged (INV-42) so they are
never presented as fresh evaluation.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema


class ProfileTier(str, Enum):
    """Tiered profiling (INV-41)."""
    MINIMAL = "MINIMAL"           # smoke-test only; cheap
    BASIC = "BASIC"               # a few canonical probes
    STANDARD = "STANDARD"         # standard benchmark subset
    COMPREHENSIVE = "COMPREHENSIVE"  # explicit opt-in; expensive


class ProfileFreshness(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    REUSED = "REUSED"             # Flagged under INV-42


class ConnectionStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


# =============================================================================
# ModelFingerprint
# =============================================================================


class ModelFingerprint(DSRTImmutableSchema):
    """Deterministic identity of a model (C10 §5)."""
    id: str

    provider_slug: str
    model_identifier: str

    # Capabilities
    supports_tools: bool = False
    supports_vision: bool = False
    supports_audio: bool = False
    supports_streaming: bool = True
    supports_structured_output: bool = False
    supports_reasoning: bool = False

    # Context
    context_window_tokens: int
    max_output_tokens: int | None = None

    # Modality
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_modalities: list[str] = Field(default_factory=lambda: ["text"])

    # Fingerprint hash (hash of all above fields; collisions = same model)
    fingerprint_hash: str

    first_seen_at: datetime
    last_seen_at: datetime


class ModelFingerprintCreate(DSRTSchema):
    provider_slug: str
    model_identifier: str
    supports_tools: bool = False
    supports_vision: bool = False
    supports_audio: bool = False
    supports_streaming: bool = True
    supports_structured_output: bool = False
    supports_reasoning: bool = False
    context_window_tokens: int
    max_output_tokens: int | None = None
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_modalities: list[str] = Field(default_factory=lambda: ["text"])


# =============================================================================
# ModelProfile
# =============================================================================


class ModelProfile(TimestampedSchema):
    """Observed performance characteristics (INV-41)."""
    id: str

    model_fingerprint_id: str
    tier: ProfileTier

    # Latency (ms)
    median_latency_ms: int | None = None
    p95_latency_ms: int | None = None
    p99_latency_ms: int | None = None

    # Throughput
    median_output_tokens_per_second: float | None = None

    # Quality markers (ONLY populated at STANDARD / COMPREHENSIVE)
    quality_markers: dict[str, float] = Field(default_factory=dict)

    # Sample size
    sample_count: int = 0

    # Observation window
    window_start: datetime | None = None
    window_end: datetime | None = None

    freshness: ProfileFreshness = ProfileFreshness.FRESH

    # Reuse flagging (INV-42)
    reused_from_profile_id: str | None = None
    reuse_reason: str | None = None


# =============================================================================
# ExecutionProfile
# =============================================================================


class ExecutionProfile(TimestampedSchema):
    """Per-(model × agent × task-class) performance (INV-42)."""
    id: str
    organization_id: str

    model_fingerprint_id: str
    agent_slug: str
    agent_version: str
    task_class: str  # e.g. "research", "code", "qa"

    # Aggregated metrics
    executions_observed: int = 0
    success_rate: float | None = None
    median_cost_usd: float | None = None
    median_duration_seconds: float | None = None
    median_quality_score: float | None = None

    # Confidence
    sample_size: int = 0
    confidence: str = "LOW"  # LOW | MEDIUM | HIGH

    freshness: ProfileFreshness = ProfileFreshness.FRESH

    # Reuse flagging
    reused_from_profile_id: str | None = None
    reuse_reason: str | None = None

    window_start: datetime | None = None
    window_end: datetime | None = None


# =============================================================================
# ModelConnection — credential/endpoint binding
# =============================================================================


class ModelConnection(TimestampedSchema):
    """A resolved connection to a model via a specific credential (INV-40)."""
    id: str
    organization_id: str

    model_fingerprint_id: str
    credential_id: str

    endpoint_url: str | None = None
    region: str | None = None

    status: ConnectionStatus = ConnectionStatus.UNKNOWN

    last_health_check_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    consecutive_failures: int = 0

    # INV-40: historical traces reference connection_id even after
    # credential is deleted. We never cascade-delete.
    credential_deleted_at: datetime | None = None