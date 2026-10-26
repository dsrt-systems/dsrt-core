# core/routing/contracts.py
"""
C9 routing contracts — the complete domain object vocabulary.

Every routing decision flows through these structures.
No hardcoded model selection — only capability-oriented,
evidence-driven, policy-filtered routing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.routing.enums import (
    AdaptiveRouteState,
    CapabilityImportance,
    EligibilityStatus,
    EvidenceConfidence,
    EvidenceSourceType,
    ExecutionStage,
    FallbackActionType,
    FallbackTriggerType,
    ModelCapabilityType,
    ProficiencyLevel,
    ProviderHealthStatus,
    QualityLevel,
    RejectionCategory,
    RoutingPriority,
    RoutingStatus,
    TaskDomain,
)
from core.routing.types import (
    ConstraintDict,
    DimensionScores,
    EvidenceRefs,
    PreferenceDict,
    RoutingMetrics,
    ToolList,
)


# ════════════════════════════════════════════════════════════════════
# 1. REQUIREMENT CONTRACTS
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CapabilityRequirement:
    """A single capability needed by a task (spec §8)."""

    capability_id: str
    required: bool = True
    minimum_version: str | None = None
    importance: CapabilityImportance = CapabilityImportance.REQUIRED
    constraints: ConstraintDict = field(default_factory=dict)
    verification_required: bool = False

    def __post_init__(self) -> None:
        if not self.capability_id:
            raise ValueError("capability_id must be non-empty")
        # If marked required, importance must be REQUIRED
        if self.required and self.importance != CapabilityImportance.REQUIRED:
            object.__setattr__(self, "importance", CapabilityImportance.REQUIRED)


@dataclass(frozen=True)
class SecurityRequirements:
    """Security constraints for a task."""

    external_write_actions: bool = False
    external_read_actions: bool = True
    requires_sandbox: bool = False
    allowed_domains: list[str] = field(default_factory=list)
    max_privilege_level: str = "standard"


@dataclass(frozen=True)
class ResourceConstraints:
    """Budget / latency / token constraints for a task."""

    max_cost_usd: float | None = None
    max_duration_seconds: float | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    max_tool_calls: int | None = None

    def __post_init__(self) -> None:
        for attr in (
            "max_cost_usd",
            "max_duration_seconds",
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "max_tool_calls",
        ):
            val = getattr(self, attr)
            if val is not None and val < 0:
                raise ValueError(f"{attr} cannot be negative, got {val}")


@dataclass(frozen=True)
class QualityRequirements:
    """Quality expectations for routing."""

    overall: QualityLevel = QualityLevel.STANDARD
    correctness: QualityLevel = QualityLevel.STANDARD
    evidence_quality: QualityLevel = QualityLevel.STANDARD
    completeness: QualityLevel = QualityLevel.STANDARD


@dataclass(frozen=True)
class TaskClassification:
    """Domain classification of a task (§28). Multi-label."""

    primary_domain: TaskDomain = TaskDomain.GENERAL
    secondary_domains: list[TaskDomain] = field(default_factory=list)
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        # primary must not duplicate in secondary
        if self.primary_domain in self.secondary_domains:
            filtered = [d for d in self.secondary_domains if d != self.primary_domain]
            object.__setattr__(self, "secondary_domains", filtered)

    @property
    def all_domains(self) -> list[TaskDomain]:
        return [self.primary_domain] + list(self.secondary_domains)


@dataclass(frozen=True)
class TaskRequirements:
    """Complete structured requirements for a task (spec §6–7)."""

    task_id: str
    description: str

    classification: TaskClassification = field(
        default_factory=TaskClassification
    )

    capabilities: list[CapabilityRequirement] = field(default_factory=list)

    quality: QualityRequirements = field(default_factory=QualityRequirements)
    resources: ResourceConstraints = field(default_factory=ResourceConstraints)
    security: SecurityRequirements = field(default_factory=SecurityRequirements)

    preferred_tools: ToolList = field(default_factory=list)
    required_tools: ToolList = field(default_factory=list)

    output_type: str = "text"

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not self.description:
            raise ValueError("description must be non-empty")

    @property
    def required_capabilities(self) -> list[CapabilityRequirement]:
        return [c for c in self.capabilities if c.required]

    @property
    def optional_capabilities(self) -> list[CapabilityRequirement]:
        return [c for c in self.capabilities if not c.required]

    def requirements_hash(self) -> str:
        """Deterministic hash of these requirements for cache keying."""
        canonical = {
            "task_id": self.task_id,
            "classification": self.classification.primary_domain.value,
            "capabilities": sorted(
                [c.capability_id for c in self.capabilities]
            ),
            "quality": self.quality.overall.value,
            "resources": {
                "max_cost_usd": self.resources.max_cost_usd,
                "max_duration_seconds": self.resources.max_duration_seconds,
            },
            "security": {
                "external_write_actions": self.security.external_write_actions,
            },
            "required_tools": sorted(self.required_tools),
            "output_type": self.output_type,
        }
        raw = json.dumps(canonical, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()


# ════════════════════════════════════════════════════════════════════
# 2. CAPABILITY PROFILE CONTRACTS
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AgentCapabilityEntry:
    """One capability an agent claims (§9)."""

    capability_id: str
    proficiency: ProficiencyLevel = ProficiencyLevel.SUPPORTED
    verification_supported: bool = False
    version: str | None = None


@dataclass(frozen=True)
class AgentCapabilityProfile:
    """Complete capability profile for an agent version."""

    agent_id: str
    agent_version_id: str
    capabilities: list[AgentCapabilityEntry] = field(default_factory=list)

    def has_capability(self, capability_id: str) -> bool:
        return any(c.capability_id == capability_id for c in self.capabilities)

    def get_capability(self, capability_id: str) -> AgentCapabilityEntry | None:
        for c in self.capabilities:
            if c.capability_id == capability_id:
                return c
        return None


@dataclass(frozen=True)
class ModelCapabilityEntry:
    """One capability a model supports (§10)."""

    capability: ModelCapabilityType
    supported: bool = True
    version: str | None = None


@dataclass(frozen=True)
class ModelLimits:
    """Operational limits of a model."""

    context_tokens: int | None = None
    max_output_tokens: int | None = None
    supports_streaming: bool = True
    supports_tool_calls: bool = True


@dataclass(frozen=True)
class ModelCapabilityProfile:
    """Complete capability profile for a model version (§10)."""

    model_id: str
    model_version_id: str
    provider_id: str
    capabilities: list[ModelCapabilityEntry] = field(default_factory=list)
    limits: ModelLimits = field(default_factory=ModelLimits)

    def has_capability(self, cap_type: ModelCapabilityType) -> bool:
        return any(
            c.capability == cap_type and c.supported for c in self.capabilities
        )


# ════════════════════════════════════════════════════════════════════
# 3. ROUTING EVIDENCE CONTRACTS
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RoutingEvidence:
    """Observed performance data for routing decisions (§12)."""

    source_type: EvidenceSourceType

    benchmark_id: str | None = None
    benchmark_version: str | None = None

    agent_version: str | None = None
    model_version: str | None = None
    world_version: str | None = None

    sample_count: int = 0
    metrics: RoutingMetrics = field(default_factory=dict)

    observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if self.sample_count < 0:
            raise ValueError(
                f"sample_count cannot be negative, got {self.sample_count}"
            )


@dataclass
class AggregatedEvidence:
    """Evidence aggregated across multiple observations."""

    candidate_key: str
    sources: list[RoutingEvidence] = field(default_factory=list)
    aggregated_metrics: RoutingMetrics = field(default_factory=dict)
    total_sample_count: int = 0
    freshness_weight: float = 1.0
    confidence: EvidenceConfidence = EvidenceConfidence.INSUFFICIENT

    @property
    def has_sufficient_evidence(self) -> bool:
        return self.confidence != EvidenceConfidence.INSUFFICIENT


# ════════════════════════════════════════════════════════════════════
# 4. POLICY & PROFILE CONTRACTS
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RoutingConstraints:
    """Hard constraints from a routing policy (§19)."""

    allowed_models: list[str] = field(default_factory=list)  # empty = all
    denied_models: list[str] = field(default_factory=list)
    allowed_agents: list[str] = field(default_factory=list)  # empty = all
    denied_agents: list[str] = field(default_factory=list)
    allowed_providers: list[str] = field(default_factory=list)  # empty = all
    denied_providers: list[str] = field(default_factory=list)
    external_write_actions: bool = False
    max_cost_usd: float | None = None
    max_latency_seconds: float | None = None
    required_security_level: str | None = None

    def is_model_allowed(self, model_id: str) -> bool:
        if model_id in self.denied_models:
            return False
        if self.allowed_models and model_id not in self.allowed_models:
            return False
        return True

    def is_agent_allowed(self, agent_id: str) -> bool:
        if agent_id in self.denied_agents:
            return False
        if self.allowed_agents and agent_id not in self.allowed_agents:
            return False
        return True

    def is_provider_allowed(self, provider_id: str) -> bool:
        if provider_id in self.denied_providers:
            return False
        if self.allowed_providers and provider_id not in self.allowed_providers:
            return False
        return True


@dataclass(frozen=True)
class RoutingPreferences:
    """Soft preferences from a routing policy (§19–21)."""

    quality_priority: RoutingPriority = RoutingPriority.MEDIUM
    cost_priority: RoutingPriority = RoutingPriority.MEDIUM
    latency_priority: RoutingPriority = RoutingPriority.MEDIUM
    reliability_priority: RoutingPriority = RoutingPriority.MEDIUM

    def weights(self) -> DimensionScores:
        """Convert priorities to numeric weights for scoring."""
        mapping = {
            RoutingPriority.HIGH: 3.0,
            RoutingPriority.MEDIUM: 2.0,
            RoutingPriority.LOW: 1.0,
            RoutingPriority.NONE: 0.0,
        }
        return {
            "quality": mapping[self.quality_priority],
            "cost": mapping[self.cost_priority],
            "latency": mapping[self.latency_priority],
            "reliability": mapping[self.reliability_priority],
        }


@dataclass(frozen=True)
class RoutingPolicy:
    """Organisation/task routing policy (§19)."""

    policy_id: str
    name: str
    version: str = "1"
    constraints: RoutingConstraints = field(default_factory=RoutingConstraints)
    preferences: RoutingPreferences = field(default_factory=RoutingPreferences)
    description: str = ""

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")


@dataclass(frozen=True)
class RoutingProfile:
    """Named routing preset (§20–21)."""

    profile_id: str
    name: str
    quality_priority: RoutingPriority = RoutingPriority.MEDIUM
    cost_priority: RoutingPriority = RoutingPriority.MEDIUM
    latency_priority: RoutingPriority = RoutingPriority.MEDIUM
    reliability_priority: RoutingPriority = RoutingPriority.MEDIUM
    description: str = ""

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")

    def to_preferences(self) -> RoutingPreferences:
        return RoutingPreferences(
            quality_priority=self.quality_priority,
            cost_priority=self.cost_priority,
            latency_priority=self.latency_priority,
            reliability_priority=self.reliability_priority,
        )


# ── Built-in profiles ──────────────────────────────────────────────

PROFILE_FAST = RoutingProfile(
    profile_id="builtin_fast",
    name="FAST",
    quality_priority=RoutingPriority.LOW,
    cost_priority=RoutingPriority.HIGH,
    latency_priority=RoutingPriority.HIGH,
    reliability_priority=RoutingPriority.MEDIUM,
    description="Optimise for speed and cost",
)

PROFILE_BALANCED = RoutingProfile(
    profile_id="builtin_balanced",
    name="BALANCED",
    quality_priority=RoutingPriority.MEDIUM,
    cost_priority=RoutingPriority.MEDIUM,
    latency_priority=RoutingPriority.MEDIUM,
    reliability_priority=RoutingPriority.MEDIUM,
    description="Balanced across all dimensions",
)

PROFILE_QUALITY = RoutingProfile(
    profile_id="builtin_quality",
    name="QUALITY",
    quality_priority=RoutingPriority.HIGH,
    cost_priority=RoutingPriority.LOW,
    latency_priority=RoutingPriority.LOW,
    reliability_priority=RoutingPriority.HIGH,
    description="Optimise for quality and reliability",
)

PROFILE_COST_CONTROLLED = RoutingProfile(
    profile_id="builtin_cost_controlled",
    name="COST_CONTROLLED",
    quality_priority=RoutingPriority.MEDIUM,
    cost_priority=RoutingPriority.HIGH,
    latency_priority=RoutingPriority.MEDIUM,
    reliability_priority=RoutingPriority.MEDIUM,
    description="Minimise cost while maintaining acceptable quality",
)

PROFILE_ENTERPRISE_STRICT = RoutingProfile(
    profile_id="builtin_enterprise_strict",
    name="ENTERPRISE_STRICT",
    quality_priority=RoutingPriority.HIGH,
    cost_priority=RoutingPriority.LOW,
    latency_priority=RoutingPriority.LOW,
    reliability_priority=RoutingPriority.HIGH,
    description="Enterprise-grade quality and reliability requirements",
)

BUILTIN_PROFILES: dict[str, RoutingProfile] = {
    p.profile_id: p
    for p in [
        PROFILE_FAST,
        PROFILE_BALANCED,
        PROFILE_QUALITY,
        PROFILE_COST_CONTROLLED,
        PROFILE_ENTERPRISE_STRICT,
    ]
}


# ════════════════════════════════════════════════════════════════════
# 5. CANDIDATE & EVALUATION CONTRACTS
# ════════════════════════════════════════════════════════════════════

@dataclass
class CandidateRejection:
    """Structured reason for why a candidate was rejected (§16)."""

    category: RejectionCategory
    detail: str
    constraint_ref: str | None = None  # which policy constraint triggered it


@dataclass
class RouteCandidate:
    """One possible execution configuration (§13)."""

    candidate_id: str
    agent_id: str
    agent_version_id: str
    model_id: str
    model_version_id: str
    provider_id: str
    world_id: str | None = None
    world_version_id: str | None = None
    tools: ToolList = field(default_factory=list)

    eligibility: EligibilityStatus = EligibilityStatus.ELIGIBLE
    rejections: list[CandidateRejection] = field(default_factory=list)

    capability_fit: dict[str, bool] = field(default_factory=dict)
    constraint_fit: ConstraintDict = field(default_factory=dict)

    def reject(
        self,
        category: RejectionCategory,
        detail: str,
        constraint_ref: str | None = None,
    ) -> None:
        self.eligibility = EligibilityStatus.REJECTED
        self.rejections.append(
            CandidateRejection(
                category=category,
                detail=detail,
                constraint_ref=constraint_ref,
            )
        )

    @property
    def is_eligible(self) -> bool:
        return self.eligibility == EligibilityStatus.ELIGIBLE


@dataclass
class RouteEvaluation:
    """Multi-dimensional scoring of a candidate (§24)."""

    candidate_id: str

    quality_score: float = 0.0
    reliability_score: float = 0.0
    latency_score: float = 0.0
    cost_score: float = 0.0

    quality_evidence: RoutingMetrics = field(default_factory=dict)
    reliability_evidence: RoutingMetrics = field(default_factory=dict)
    estimated_latency: RoutingMetrics = field(default_factory=dict)
    estimated_cost: RoutingMetrics = field(default_factory=dict)

    constraint_fit: ConstraintDict = field(default_factory=dict)
    uncertainty: RoutingMetrics = field(default_factory=dict)

    def weighted_score(self, weights: DimensionScores) -> float:
        """Compute weighted composite score (§23).

        Note: each dimension is retained separately; this is used
        only for final selection ranking, not stored as a permanent
        opaque score.
        """
        total_weight = sum(weights.values())
        if total_weight == 0:
            return 0.0
        raw = (
            self.quality_score * weights.get("quality", 0.0)
            + self.reliability_score * weights.get("reliability", 0.0)
            + self.latency_score * weights.get("latency", 0.0)
            + self.cost_score * weights.get("cost", 0.0)
        )
        return raw / total_weight


# ════════════════════════════════════════════════════════════════════
# 6. ROUTE & DECISION CONTRACTS
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ExecutionStrategy:
    """How the route should be executed."""

    parallelism: int = 1
    max_retries: int = 3
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.parallelism < 1:
            raise ValueError(
                f"parallelism must be >= 1, got {self.parallelism}"
            )
        if self.max_retries < 0:
            raise ValueError(
                f"max_retries must be >= 0, got {self.max_retries}"
            )


@dataclass(frozen=True)
class Route:
    """The complete execution configuration selected by the router (§4)."""

    agent_id: str
    agent_version_id: str
    model_id: str
    model_version_id: str
    provider_id: str

    world_id: str | None = None
    world_version_id: str | None = None

    tools: ToolList = field(default_factory=list)

    context_profile: str | None = None
    verification_policy: str | None = None

    execution_strategy: ExecutionStrategy = field(
        default_factory=ExecutionStrategy
    )

    fallback_policy_id: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteDecision:
    """The auditable routing decision (§17)."""

    decision_id: str
    task_id: str

    status: RoutingStatus = RoutingStatus.PENDING

    requirements: TaskRequirements | None = None

    selected_route: Route | None = None

    routing_policy_id: str | None = None
    routing_policy_version: str | None = None
    routing_profile_id: str | None = None

    candidates_considered: int = 0
    candidates_eligible: int = 0

    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: EvidenceRefs = field(default_factory=list)

    decision_reason: dict[str, Any] = field(default_factory=dict)
    configuration_hash: str | None = None

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("decision_id must be non-empty")
        if not self.task_id:
            raise ValueError("task_id must be non-empty")


# ════════════════════════════════════════════════════════════════════
# 7. FALLBACK & ESCALATION CONTRACTS
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FallbackPolicy:
    """What to do when a route fails (§39–40)."""

    policy_id: str
    name: str
    triggers: list[FallbackTriggerType] = field(default_factory=list)
    action: FallbackActionType = FallbackActionType.RETRY
    fallback_candidates: list[str] = field(default_factory=list)  # model/agent IDs
    max_attempts: int = 3
    backoff_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")
        if self.max_attempts < 1:
            raise ValueError(
                f"max_attempts must be >= 1, got {self.max_attempts}"
            )


@dataclass(frozen=True)
class EscalationPolicy:
    """When to require human review (§41)."""

    policy_id: str
    name: str
    max_fallback_attempts: int = 3
    security_sensitive: bool = False
    policy_mandated_review: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")

    def should_escalate(
        self, fallback_attempts: int, is_security_sensitive: bool = False
    ) -> bool:
        if self.policy_mandated_review:
            return True
        if self.security_sensitive and is_security_sensitive:
            return True
        if fallback_attempts >= self.max_fallback_attempts:
            return True
        return False


# ════════════════════════════════════════════════════════════════════
# 8. ADAPTIVE & STAGE-BASED ROUTING CONTRACTS
# ════════════════════════════════════════════════════════════════════

@dataclass
class RouteChangeRecord:
    """Audit record when route changes mid-execution (§38)."""

    from_model_id: str
    to_model_id: str
    reason: str
    trigger_type: FallbackTriggerType | None = None
    policy_id: str | None = None
    changed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class AdaptiveRoute:
    """Route that can change based on observations (§36–37)."""

    current_route: Route
    state: AdaptiveRouteState = AdaptiveRouteState.ACTIVE
    change_history: list[RouteChangeRecord] = field(default_factory=list)
    fallback_attempts: int = 0
    max_fallback_attempts: int = 3

    @property
    def can_fallback(self) -> bool:
        return self.fallback_attempts < self.max_fallback_attempts

    def record_change(self, record: RouteChangeRecord) -> None:
        self.change_history.append(record)
        self.fallback_attempts += 1


@dataclass(frozen=True)
class StageRoutePreference:
    """Routing preference for a specific execution stage (§34–35)."""

    stage: ExecutionStage
    model_profile: str  # e.g. "reasoning", "tool_efficiency", "quality"
    override_model_id: str | None = None  # explicit override if policy allows


@dataclass(frozen=True)
class StageRoutingConfig:
    """Per-stage routing configuration for a task (§34–35)."""

    stages: list[StageRoutePreference] = field(default_factory=list)

    def get_stage_preference(
        self, stage: ExecutionStage
    ) -> StageRoutePreference | None:
        for s in self.stages:
            if s.stage == stage:
                return s
        return None


# ════════════════════════════════════════════════════════════════════
# 9. PROVIDER HEALTH CONTRACT
# ════════════════════════════════════════════════════════════════════

@dataclass
class ProviderHealthState:
    """Current operational state of a provider (§45–46)."""

    provider_id: str
    status: ProviderHealthStatus = ProviderHealthStatus.UNKNOWN

    latency_p50_ms: float | None = None
    latency_p99_ms: float | None = None
    error_rate: float | None = None

    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None

    observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime | None = None

    @property
    def is_available(self) -> bool:
        return self.status in (
            ProviderHealthStatus.AVAILABLE,
            ProviderHealthStatus.DEGRADED,
        )

    @property
    def is_healthy(self) -> bool:
        return self.status == ProviderHealthStatus.AVAILABLE

    def health_hash(self) -> str:
        """Deterministic hash for cache keying."""
        raw = json.dumps(
            {
                "provider_id": self.provider_id,
                "status": self.status.value,
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ════════════════════════════════════════════════════════════════════
# 10. CAPABILITY MATCH RESULT
# ════════════════════════════════════════════════════════════════════

@dataclass
class CapabilityMatchResult:
    """Result of matching one capability requirement against a profile."""

    capability_id: str
    required: bool
    matched: bool
    proficiency: ProficiencyLevel | None = None
    detail: str = ""


@dataclass
class CapabilityMatchSummary:
    """Overall match summary for an entity against task requirements."""

    entity_id: str  # agent_id, model_id, etc.
    entity_type: str  # "agent", "model", "world"
    matches: list[CapabilityMatchResult] = field(default_factory=list)

    @property
    def all_required_met(self) -> bool:
        return all(m.matched for m in self.matches if m.required)

    @property
    def match_score(self) -> float:
        """Fraction of capabilities matched (0.0 to 1.0)."""
        if not self.matches:
            return 0.0
        return sum(1 for m in self.matches if m.matched) / len(self.matches)

    @property
    def missing_required(self) -> list[str]:
        return [
            m.capability_id for m in self.matches if m.required and not m.matched
        ]