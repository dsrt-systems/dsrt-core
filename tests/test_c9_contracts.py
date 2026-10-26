# tests/test_c9_contracts.py
"""
C9.1 — Routing Contracts & Domain Schemas.

Tests every contract, enum, type alias, and validation schema
introduced by the Intelligence Routing Fabric.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

# ── Enum imports ────────────────────────────────────────────────────

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

# ── Contract imports ────────────────────────────────────────────────

from core.routing.contracts import (
    BUILTIN_PROFILES,
    PROFILE_BALANCED,
    PROFILE_COST_CONTROLLED,
    PROFILE_ENTERPRISE_STRICT,
    PROFILE_FAST,
    PROFILE_QUALITY,
    AdaptiveRoute,
    AgentCapabilityEntry,
    AgentCapabilityProfile,
    AggregatedEvidence,
    CapabilityMatchResult,
    CapabilityMatchSummary,
    CapabilityRequirement,
    CandidateRejection,
    EscalationPolicy,
    ExecutionStrategy,
    FallbackPolicy,
    ModelCapabilityEntry,
    ModelCapabilityProfile,
    ModelLimits,
    ProviderHealthState,
    QualityRequirements,
    ResourceConstraints,
    Route,
    RouteCandidate,
    RouteChangeRecord,
    RouteDecision,
    RouteEvaluation,
    RoutingConstraints,
    RoutingEvidence,
    RoutingPolicy,
    RoutingPreferences,
    RoutingProfile,
    SecurityRequirements,
    StageRoutePreference,
    StageRoutingConfig,
    TaskClassification,
    TaskRequirements,
)

# ── Type imports ────────────────────────────────────────────────────

from core.routing.types import (
    ConstraintDict,
    DimensionScores,
    EvidenceRefs,
    PreferenceDict,
    RoutingMetrics,
    ToolList,
)

# ── Schema imports ──────────────────────────────────────────────────

from schemas.routing.schemas import (
    CapabilityRequirementSchema,
    FallbackPolicySchema,
    ResourceConstraintsSchema,
    RoutingConstraintsSchema,
    RoutingEvidenceSchema,
    RoutingPolicySchema,
    RoutingPreferencesSchema,
    RoutingProfileSchema,
    SecurityRequirementsSchema,
    TaskClassificationSchema,
    TaskRequirementsSchema,
    QualityRequirementsSchema,
)


# ════════════════════════════════════════════════════════════════════
# ENUM TESTS
# ════════════════════════════════════════════════════════════════════


class TestEnums:
    """All C9 enumerations are importable and well-formed."""

    def test_task_domain_values(self):
        assert TaskDomain.RESEARCH.value == "RESEARCH"
        assert TaskDomain.CODING.value == "CODING"
        assert len(TaskDomain) == 10

    def test_capability_importance(self):
        assert CapabilityImportance.REQUIRED.value == "REQUIRED"
        assert CapabilityImportance.PREFERRED.value == "PREFERRED"
        assert CapabilityImportance.OPTIONAL.value == "OPTIONAL"

    def test_proficiency_levels(self):
        assert len(ProficiencyLevel) == 4
        assert ProficiencyLevel.CERTIFIED.value == "CERTIFIED"

    def test_eligibility_status(self):
        assert EligibilityStatus.ELIGIBLE.value == "ELIGIBLE"
        assert EligibilityStatus.REJECTED.value == "REJECTED"

    def test_rejection_categories(self):
        assert len(RejectionCategory) == 9
        assert RejectionCategory.MISSING_CAPABILITY.value == "MISSING_CAPABILITY"

    def test_routing_status_lifecycle(self):
        assert len(RoutingStatus) == 10
        assert RoutingStatus.PENDING.value == "PENDING"
        assert RoutingStatus.COMPLETED.value == "COMPLETED"

    def test_provider_health_status(self):
        assert len(ProviderHealthStatus) == 5
        assert ProviderHealthStatus.AVAILABLE.value == "AVAILABLE"
        assert ProviderHealthStatus.UNKNOWN.value == "UNKNOWN"

    def test_routing_priority(self):
        assert len(RoutingPriority) == 4
        assert RoutingPriority.HIGH.value == "HIGH"
        assert RoutingPriority.NONE.value == "NONE"

    def test_fallback_action_types(self):
        assert len(FallbackActionType) == 9
        assert FallbackActionType.SWITCH_MODEL.value == "SWITCH_MODEL"

    def test_fallback_trigger_types(self):
        assert len(FallbackTriggerType) == 7
        assert FallbackTriggerType.PROVIDER_TIMEOUT.value == "PROVIDER_TIMEOUT"

    def test_adaptive_route_state(self):
        assert len(AdaptiveRouteState) == 5
        assert AdaptiveRouteState.ACTIVE.value == "ACTIVE"

    def test_execution_stages(self):
        assert len(ExecutionStage) == 6
        assert ExecutionStage.PLANNING.value == "PLANNING"

    def test_evidence_source_types(self):
        assert len(EvidenceSourceType) == 5
        assert EvidenceSourceType.ARENA_BENCHMARK.value == "ARENA_BENCHMARK"

    def test_evidence_confidence(self):
        assert len(EvidenceConfidence) == 4
        assert EvidenceConfidence.INSUFFICIENT.value == "INSUFFICIENT"

    def test_model_capability_types(self):
        assert len(ModelCapabilityType) == 10
        assert ModelCapabilityType.TOOL_USE.value == "TOOL_USE"

    def test_quality_levels(self):
        assert len(QualityLevel) == 4
        assert QualityLevel.STRICT.value == "STRICT"

    def test_enums_are_str_enums(self):
        """All enums are str Enums for JSON serialisation."""
        assert isinstance(TaskDomain.RESEARCH, str)
        assert isinstance(ProviderHealthStatus.AVAILABLE, str)
        assert isinstance(FallbackActionType.RETRY, str)


# ════════════════════════════════════════════════════════════════════
# TYPE ALIAS TESTS
# ════════════════════════════════════════════════════════════════════


class TestTypes:
    """Type aliases are accessible."""

    def test_routing_metrics_is_dict(self):
        m: RoutingMetrics = {"accuracy": 0.95}
        assert m["accuracy"] == 0.95

    def test_constraint_dict(self):
        c: ConstraintDict = {"max_cost": 2.0}
        assert c["max_cost"] == 2.0

    def test_tool_list(self):
        t: ToolList = ["web.search", "web.retrieve"]
        assert len(t) == 2

    def test_evidence_refs(self):
        e: EvidenceRefs = ["bench_001", "bench_002"]
        assert len(e) == 2

    def test_dimension_scores(self):
        d: DimensionScores = {"quality": 3.0, "cost": 1.0}
        assert d["quality"] == 3.0


# ════════════════════════════════════════════════════════════════════
# CAPABILITY REQUIREMENT TESTS
# ════════════════════════════════════════════════════════════════════


class TestCapabilityRequirement:

    def test_basic_creation(self):
        cr = CapabilityRequirement(capability_id="web_research")
        assert cr.capability_id == "web_research"
        assert cr.required is True
        assert cr.importance == CapabilityImportance.REQUIRED

    def test_optional_capability(self):
        cr = CapabilityRequirement(
            capability_id="vision",
            required=False,
            importance=CapabilityImportance.OPTIONAL,
        )
        assert cr.required is False
        assert cr.importance == CapabilityImportance.OPTIONAL

    def test_required_forces_importance(self):
        """If required=True but importance != REQUIRED, auto-correct."""
        cr = CapabilityRequirement(
            capability_id="tool_use",
            required=True,
            importance=CapabilityImportance.PREFERRED,
        )
        assert cr.importance == CapabilityImportance.REQUIRED

    def test_empty_capability_id_rejected(self):
        with pytest.raises(ValueError, match="capability_id must be non-empty"):
            CapabilityRequirement(capability_id="")

    def test_with_constraints(self):
        cr = CapabilityRequirement(
            capability_id="long_context",
            constraints={"min_tokens": 128000},
        )
        assert cr.constraints["min_tokens"] == 128000

    def test_frozen(self):
        cr = CapabilityRequirement(capability_id="test")
        with pytest.raises(AttributeError):
            cr.capability_id = "changed"  # type: ignore[misc]


# ════════════════════════════════════════════════════════════════════
# SECURITY / RESOURCE / QUALITY REQUIREMENT TESTS
# ════════════════════════════════════════════════════════════════════


class TestSecurityRequirements:

    def test_defaults(self):
        sr = SecurityRequirements()
        assert sr.external_write_actions is False
        assert sr.external_read_actions is True
        assert sr.requires_sandbox is False

    def test_strict_security(self):
        sr = SecurityRequirements(
            external_write_actions=False,
            external_read_actions=False,
            requires_sandbox=True,
            max_privilege_level="minimal",
        )
        assert sr.requires_sandbox is True


class TestResourceConstraints:

    def test_defaults_are_none(self):
        rc = ResourceConstraints()
        assert rc.max_cost_usd is None
        assert rc.max_duration_seconds is None

    def test_set_constraints(self):
        rc = ResourceConstraints(max_cost_usd=2.0, max_duration_seconds=900)
        assert rc.max_cost_usd == 2.0
        assert rc.max_duration_seconds == 900

    def test_negative_cost_rejected(self):
        with pytest.raises(ValueError, match="max_cost_usd cannot be negative"):
            ResourceConstraints(max_cost_usd=-1.0)

    def test_negative_tokens_rejected(self):
        with pytest.raises(ValueError, match="max_input_tokens cannot be negative"):
            ResourceConstraints(max_input_tokens=-100)

    def test_zero_is_allowed(self):
        rc = ResourceConstraints(max_cost_usd=0.0, max_tool_calls=0)
        assert rc.max_cost_usd == 0.0
        assert rc.max_tool_calls == 0


class TestQualityRequirements:

    def test_defaults(self):
        qr = QualityRequirements()
        assert qr.overall == QualityLevel.STANDARD

    def test_strict_quality(self):
        qr = QualityRequirements(
            overall=QualityLevel.STRICT,
            correctness=QualityLevel.HIGH,
        )
        assert qr.overall == QualityLevel.STRICT
        assert qr.correctness == QualityLevel.HIGH


# ════════════════════════════════════════════════════════════════════
# TASK CLASSIFICATION TESTS
# ════════════════════════════════════════════════════════════════════


class TestTaskClassification:

    def test_default_general(self):
        tc = TaskClassification()
        assert tc.primary_domain == TaskDomain.GENERAL
        assert tc.all_domains == [TaskDomain.GENERAL]

    def test_multi_domain(self):
        tc = TaskClassification(
            primary_domain=TaskDomain.RESEARCH,
            secondary_domains=[TaskDomain.WRITING, TaskDomain.DATA_ANALYSIS],
        )
        assert len(tc.all_domains) == 3

    def test_confidence_bounds(self):
        with pytest.raises(ValueError, match="confidence must be in"):
            TaskClassification(confidence=1.5)
        with pytest.raises(ValueError, match="confidence must be in"):
            TaskClassification(confidence=-0.1)

    def test_primary_not_duplicated_in_secondary(self):
        tc = TaskClassification(
            primary_domain=TaskDomain.CODING,
            secondary_domains=[TaskDomain.CODING, TaskDomain.WRITING],
        )
        assert TaskDomain.CODING not in tc.secondary_domains
        assert tc.all_domains == [TaskDomain.CODING, TaskDomain.WRITING]


# ════════════════════════════════════════════════════════════════════
# TASK REQUIREMENTS TESTS
# ════════════════════════════════════════════════════════════════════


class TestTaskRequirements:

    def test_basic_creation(self):
        tr = TaskRequirements(
            task_id="task_001",
            description="Research this company",
        )
        assert tr.task_id == "task_001"
        assert tr.classification.primary_domain == TaskDomain.GENERAL

    def test_with_capabilities(self):
        tr = TaskRequirements(
            task_id="task_002",
            description="Research task",
            capabilities=[
                CapabilityRequirement(capability_id="web_research"),
                CapabilityRequirement(
                    capability_id="vision",
                    required=False,
                    importance=CapabilityImportance.OPTIONAL,
                ),
            ],
        )
        assert len(tr.required_capabilities) == 1
        assert len(tr.optional_capabilities) == 1

    def test_empty_task_id_rejected(self):
        with pytest.raises(ValueError, match="task_id must be non-empty"):
            TaskRequirements(task_id="", description="test")

    def test_empty_description_rejected(self):
        with pytest.raises(ValueError, match="description must be non-empty"):
            TaskRequirements(task_id="t1", description="")

    def test_requirements_hash_deterministic(self):
        tr = TaskRequirements(
            task_id="t1",
            description="test",
            capabilities=[
                CapabilityRequirement(capability_id="a"),
                CapabilityRequirement(capability_id="b"),
            ],
        )
        h1 = tr.requirements_hash()
        h2 = tr.requirements_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_different_requirements_different_hash(self):
        tr1 = TaskRequirements(task_id="t1", description="test1")
        tr2 = TaskRequirements(task_id="t2", description="test2")
        assert tr1.requirements_hash() != tr2.requirements_hash()

    def test_full_requirements(self):
        tr = TaskRequirements(
            task_id="full_task",
            description="Full research task",
            classification=TaskClassification(
                primary_domain=TaskDomain.RESEARCH,
                secondary_domains=[TaskDomain.WRITING],
            ),
            capabilities=[
                CapabilityRequirement(capability_id="web_research"),
                CapabilityRequirement(capability_id="evidence_synthesis"),
            ],
            quality=QualityRequirements(overall=QualityLevel.HIGH),
            resources=ResourceConstraints(max_cost_usd=2.0, max_duration_seconds=900),
            security=SecurityRequirements(external_write_actions=False),
            required_tools=["web.search", "web.retrieve"],
            output_type="document",
        )
        assert tr.classification.primary_domain == TaskDomain.RESEARCH
        assert len(tr.required_capabilities) == 2
        assert tr.resources.max_cost_usd == 2.0
        assert tr.security.external_write_actions is False


# ════════════════════════════════════════════════════════════════════
# AGENT CAPABILITY PROFILE TESTS
# ════════════════════════════════════════════════════════════════════


class TestAgentCapabilityProfile:

    def test_creation(self):
        profile = AgentCapabilityProfile(
            agent_id="research_intelligence",
            agent_version_id="v1",
            capabilities=[
                AgentCapabilityEntry(
                    capability_id="web_research",
                    proficiency=ProficiencyLevel.PRODUCTION,
                ),
                AgentCapabilityEntry(
                    capability_id="report_generation",
                    proficiency=ProficiencyLevel.SUPPORTED,
                ),
            ],
        )
        assert profile.has_capability("web_research")
        assert not profile.has_capability("vision")

    def test_get_capability(self):
        entry = AgentCapabilityEntry(
            capability_id="analysis",
            proficiency=ProficiencyLevel.CERTIFIED,
            verification_supported=True,
        )
        profile = AgentCapabilityProfile(
            agent_id="a1", agent_version_id="v1", capabilities=[entry]
        )
        result = profile.get_capability("analysis")
        assert result is not None
        assert result.proficiency == ProficiencyLevel.CERTIFIED
        assert result.verification_supported is True

    def test_get_missing_capability(self):
        profile = AgentCapabilityProfile(
            agent_id="a1", agent_version_id="v1"
        )
        assert profile.get_capability("anything") is None


# ════════════════════════════════════════════════════════════════════
# MODEL CAPABILITY PROFILE TESTS
# ════════════════════════════════════════════════════════════════════


class TestModelCapabilityProfile:

    def test_creation(self):
        profile = ModelCapabilityProfile(
            model_id="model_x",
            model_version_id="v1",
            provider_id="provider_a",
            capabilities=[
                ModelCapabilityEntry(capability=ModelCapabilityType.REASONING),
                ModelCapabilityEntry(capability=ModelCapabilityType.TOOL_USE),
                ModelCapabilityEntry(
                    capability=ModelCapabilityType.VISION, supported=False
                ),
            ],
        )
        assert profile.has_capability(ModelCapabilityType.REASONING)
        assert profile.has_capability(ModelCapabilityType.TOOL_USE)
        assert not profile.has_capability(ModelCapabilityType.VISION)

    def test_model_limits(self):
        limits = ModelLimits(context_tokens=128000, max_output_tokens=4096)
        profile = ModelCapabilityProfile(
            model_id="m1",
            model_version_id="v1",
            provider_id="p1",
            limits=limits,
        )
        assert profile.limits.context_tokens == 128000


# ════════════════════════════════════════════════════════════════════
# ROUTING EVIDENCE TESTS
# ════════════════════════════════════════════════════════════════════


class TestRoutingEvidence:

    def test_creation(self):
        ev = RoutingEvidence(
            source_type=EvidenceSourceType.ARENA_BENCHMARK,
            benchmark_id="bench_001",
            model_version="v1",
            sample_count=142,
            metrics={"accuracy": 0.92, "latency_p50": 1200},
        )
        assert ev.sample_count == 142
        assert ev.metrics["accuracy"] == 0.92

    def test_negative_sample_count_rejected(self):
        with pytest.raises(ValueError, match="sample_count cannot be negative"):
            RoutingEvidence(
                source_type=EvidenceSourceType.ARENA_BENCHMARK,
                sample_count=-1,
            )

    def test_observed_at_defaults_to_now(self):
        ev = RoutingEvidence(source_type=EvidenceSourceType.PRODUCTION_OBSERVATION)
        assert isinstance(ev.observed_at, datetime)
        assert ev.observed_at.tzinfo is not None


class TestAggregatedEvidence:

    def test_insufficient_by_default(self):
        ae = AggregatedEvidence(candidate_key="c1")
        assert ae.confidence == EvidenceConfidence.INSUFFICIENT
        assert not ae.has_sufficient_evidence

    def test_sufficient_evidence(self):
        ae = AggregatedEvidence(
            candidate_key="c1",
            total_sample_count=100,
            confidence=EvidenceConfidence.HIGH,
        )
        assert ae.has_sufficient_evidence


# ════════════════════════════════════════════════════════════════════
# ROUTING POLICY TESTS
# ════════════════════════════════════════════════════════════════════


class TestRoutingConstraints:

    def test_defaults_allow_all(self):
        rc = RoutingConstraints()
        assert rc.is_model_allowed("any_model")
        assert rc.is_agent_allowed("any_agent")
        assert rc.is_provider_allowed("any_provider")

    def test_allowed_models_whitelist(self):
        rc = RoutingConstraints(allowed_models=["model_a", "model_b"])
        assert rc.is_model_allowed("model_a")
        assert not rc.is_model_allowed("model_c")

    def test_denied_models_blacklist(self):
        rc = RoutingConstraints(denied_models=["model_bad"])
        assert not rc.is_model_allowed("model_bad")
        assert rc.is_model_allowed("model_good")

    def test_denied_overrides_allowed(self):
        rc = RoutingConstraints(
            allowed_models=["model_a", "model_b"],
            denied_models=["model_a"],
        )
        assert not rc.is_model_allowed("model_a")
        assert rc.is_model_allowed("model_b")

    def test_agent_filtering(self):
        rc = RoutingConstraints(allowed_agents=["research_intelligence"])
        assert rc.is_agent_allowed("research_intelligence")
        assert not rc.is_agent_allowed("other_agent")

    def test_provider_filtering(self):
        rc = RoutingConstraints(denied_providers=["provider_x"])
        assert not rc.is_provider_allowed("provider_x")
        assert rc.is_provider_allowed("provider_y")


class TestRoutingPreferences:

    def test_defaults(self):
        rp = RoutingPreferences()
        assert rp.quality_priority == RoutingPriority.MEDIUM
        assert rp.cost_priority == RoutingPriority.MEDIUM

    def test_weights(self):
        rp = RoutingPreferences(
            quality_priority=RoutingPriority.HIGH,
            cost_priority=RoutingPriority.LOW,
            latency_priority=RoutingPriority.NONE,
            reliability_priority=RoutingPriority.MEDIUM,
        )
        w = rp.weights()
        assert w["quality"] == 3.0
        assert w["cost"] == 1.0
        assert w["latency"] == 0.0
        assert w["reliability"] == 2.0


class TestRoutingPolicy:

    def test_creation(self):
        policy = RoutingPolicy(
            policy_id="enterprise_default",
            name="Enterprise Default",
            constraints=RoutingConstraints(
                allowed_models=["model_a", "model_b"],
                external_write_actions=False,
            ),
            preferences=RoutingPreferences(
                quality_priority=RoutingPriority.HIGH,
            ),
        )
        assert policy.policy_id == "enterprise_default"
        assert policy.constraints.is_model_allowed("model_a")
        assert not policy.constraints.is_model_allowed("model_c")

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="policy_id must be non-empty"):
            RoutingPolicy(policy_id="", name="test")

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="name must be non-empty"):
            RoutingPolicy(policy_id="p1", name="")


# ════════════════════════════════════════════════════════════════════
# ROUTING PROFILE TESTS
# ════════════════════════════════════════════════════════════════════


class TestRoutingProfile:

    def test_creation(self):
        profile = RoutingProfile(
            profile_id="custom_fast",
            name="Custom Fast",
            latency_priority=RoutingPriority.HIGH,
            cost_priority=RoutingPriority.HIGH,
        )
        assert profile.profile_id == "custom_fast"

    def test_to_preferences(self):
        profile = RoutingProfile(
            profile_id="p1",
            name="P1",
            quality_priority=RoutingPriority.HIGH,
            cost_priority=RoutingPriority.LOW,
        )
        prefs = profile.to_preferences()
        assert prefs.quality_priority == RoutingPriority.HIGH
        assert prefs.cost_priority == RoutingPriority.LOW

    def test_builtin_profiles_exist(self):
        assert len(BUILTIN_PROFILES) == 5
        assert "builtin_fast" in BUILTIN_PROFILES
        assert "builtin_balanced" in BUILTIN_PROFILES
        assert "builtin_quality" in BUILTIN_PROFILES
        assert "builtin_cost_controlled" in BUILTIN_PROFILES
        assert "builtin_enterprise_strict" in BUILTIN_PROFILES

    def test_fast_profile(self):
        assert PROFILE_FAST.latency_priority == RoutingPriority.HIGH
        assert PROFILE_FAST.cost_priority == RoutingPriority.HIGH
        assert PROFILE_FAST.quality_priority == RoutingPriority.LOW

    def test_quality_profile(self):
        assert PROFILE_QUALITY.quality_priority == RoutingPriority.HIGH
        assert PROFILE_QUALITY.reliability_priority == RoutingPriority.HIGH
        assert PROFILE_QUALITY.latency_priority == RoutingPriority.LOW

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="profile_id must be non-empty"):
            RoutingProfile(profile_id="", name="test")


# ════════════════════════════════════════════════════════════════════
# ROUTE CANDIDATE TESTS
# ════════════════════════════════════════════════════════════════════


class TestRouteCandidate:

    def test_creation(self):
        rc = RouteCandidate(
            candidate_id="c1",
            agent_id="research_intelligence",
            agent_version_id="v1",
            model_id="model_x",
            model_version_id="v1",
            provider_id="provider_a",
            tools=["web.search"],
        )
        assert rc.is_eligible
        assert rc.eligibility == EligibilityStatus.ELIGIBLE

    def test_reject(self):
        rc = RouteCandidate(
            candidate_id="c2",
            agent_id="a1",
            agent_version_id="v1",
            model_id="m1",
            model_version_id="v1",
            provider_id="p1",
        )
        rc.reject(
            RejectionCategory.MISSING_CAPABILITY,
            "Model does not support vision",
        )
        assert not rc.is_eligible
        assert rc.eligibility == EligibilityStatus.REJECTED
        assert len(rc.rejections) == 1
        assert rc.rejections[0].category == RejectionCategory.MISSING_CAPABILITY

    def test_multiple_rejections(self):
        rc = RouteCandidate(
            candidate_id="c3",
            agent_id="a1",
            agent_version_id="v1",
            model_id="m1",
            model_version_id="v1",
            provider_id="p1",
        )
        rc.reject(RejectionCategory.BUDGET_EXCEEDED, "Too expensive")
        rc.reject(RejectionCategory.POLICY_DENIED, "Not in allowed list")
        assert len(rc.rejections) == 2
        assert not rc.is_eligible


class TestCandidateRejection:

    def test_creation(self):
        cr = CandidateRejection(
            category=RejectionCategory.SECURITY_VIOLATION,
            detail="Requires external write access",
            constraint_ref="security.external_write_actions",
        )
        assert cr.category == RejectionCategory.SECURITY_VIOLATION
        assert cr.constraint_ref == "security.external_write_actions"


# ════════════════════════════════════════════════════════════════════
# ROUTE EVALUATION TESTS
# ════════════════════════════════════════════════════════════════════


class TestRouteEvaluation:

    def test_creation(self):
        ev = RouteEvaluation(
            candidate_id="c1",
            quality_score=0.9,
            reliability_score=0.85,
            latency_score=0.7,
            cost_score=0.6,
        )
        assert ev.quality_score == 0.9

    def test_weighted_score(self):
        ev = RouteEvaluation(
            candidate_id="c1",
            quality_score=1.0,
            reliability_score=0.5,
            latency_score=0.0,
            cost_score=0.0,
        )
        # quality=3.0, reliability=2.0, latency=0, cost=0
        weights: DimensionScores = {
            "quality": 3.0,
            "reliability": 2.0,
            "latency": 0.0,
            "cost": 0.0,
        }
        score = ev.weighted_score(weights)
        expected = (1.0 * 3.0 + 0.5 * 2.0 + 0.0 + 0.0) / 5.0
        assert abs(score - expected) < 1e-9

    def test_weighted_score_all_zero_weights(self):
        ev = RouteEvaluation(candidate_id="c1", quality_score=1.0)
        weights: DimensionScores = {
            "quality": 0.0,
            "reliability": 0.0,
            "latency": 0.0,
            "cost": 0.0,
        }
        assert ev.weighted_score(weights) == 0.0

    def test_equal_weights(self):
        ev = RouteEvaluation(
            candidate_id="c1",
            quality_score=0.8,
            reliability_score=0.8,
            latency_score=0.8,
            cost_score=0.8,
        )
        weights: DimensionScores = {
            "quality": 1.0,
            "reliability": 1.0,
            "latency": 1.0,
            "cost": 1.0,
        }
        assert abs(ev.weighted_score(weights) - 0.8) < 1e-9


# ════════════════════════════════════════════════════════════════════
# ROUTE & ROUTE DECISION TESTS
# ════════════════════════════════════════════════════════════════════


class TestExecutionStrategy:

    def test_defaults(self):
        es = ExecutionStrategy()
        assert es.parallelism == 1
        assert es.max_retries == 3

    def test_invalid_parallelism(self):
        with pytest.raises(ValueError, match="parallelism must be >= 1"):
            ExecutionStrategy(parallelism=0)

    def test_invalid_retries(self):
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            ExecutionStrategy(max_retries=-1)


class TestRoute:

    def test_creation(self):
        route = Route(
            agent_id="research_intelligence",
            agent_version_id="v1",
            model_id="model_x",
            model_version_id="v1",
            provider_id="provider_a",
            world_id="research_world",
            tools=["web.search", "web.retrieve"],
            context_profile="research_deep",
            verification_policy="research_strict",
        )
        assert route.agent_id == "research_intelligence"
        assert len(route.tools) == 2

    def test_minimal_route(self):
        route = Route(
            agent_id="a1",
            agent_version_id="v1",
            model_id="m1",
            model_version_id="v1",
            provider_id="p1",
        )
        assert route.world_id is None
        assert route.tools == []
        assert route.fallback_policy_id is None


class TestRouteDecision:

    def test_creation(self):
        rd = RouteDecision(
            decision_id="rd_001",
            task_id="task_001",
        )
        assert rd.status == RoutingStatus.PENDING
        assert rd.candidates_considered == 0
        assert isinstance(rd.created_at, datetime)

    def test_with_selected_route(self):
        route = Route(
            agent_id="a1",
            agent_version_id="v1",
            model_id="m1",
            model_version_id="v1",
            provider_id="p1",
        )
        rd = RouteDecision(
            decision_id="rd_002",
            task_id="task_002",
            status=RoutingStatus.SELECTED,
            selected_route=route,
            candidates_considered=5,
            candidates_eligible=3,
            decision_reason={"primary": "highest quality evidence"},
        )
        assert rd.selected_route is not None
        assert rd.candidates_eligible == 3

    def test_empty_decision_id_rejected(self):
        with pytest.raises(ValueError, match="decision_id must be non-empty"):
            RouteDecision(decision_id="", task_id="t1")

    def test_empty_task_id_rejected(self):
        with pytest.raises(ValueError, match="task_id must be non-empty"):
            RouteDecision(decision_id="d1", task_id="")


# ════════════════════════════════════════════════════════════════════
# FALLBACK & ESCALATION TESTS
# ════════════════════════════════════════════════════════════════════


class TestFallbackPolicy:

    def test_creation(self):
        fp = FallbackPolicy(
            policy_id="fb_001",
            name="Default Fallback",
            triggers=[
                FallbackTriggerType.PROVIDER_TIMEOUT,
                FallbackTriggerType.PROVIDER_RATE_LIMIT,
            ],
            action=FallbackActionType.SWITCH_MODEL,
            fallback_candidates=["model_b", "model_c"],
        )
        assert len(fp.triggers) == 2
        assert fp.action == FallbackActionType.SWITCH_MODEL

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="policy_id must be non-empty"):
            FallbackPolicy(policy_id="", name="test")

    def test_invalid_max_attempts(self):
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            FallbackPolicy(policy_id="fb1", name="test", max_attempts=0)


class TestEscalationPolicy:

    def test_creation(self):
        ep = EscalationPolicy(
            policy_id="esc_001",
            name="Default Escalation",
            max_fallback_attempts=3,
        )
        assert ep.policy_id == "esc_001"

    def test_should_escalate_on_attempts(self):
        ep = EscalationPolicy(
            policy_id="e1", name="e1", max_fallback_attempts=3
        )
        assert not ep.should_escalate(2)
        assert ep.should_escalate(3)
        assert ep.should_escalate(10)

    def test_should_escalate_on_security(self):
        ep = EscalationPolicy(
            policy_id="e1", name="e1", security_sensitive=True
        )
        assert ep.should_escalate(0, is_security_sensitive=True)
        assert not ep.should_escalate(0, is_security_sensitive=False)

    def test_should_escalate_policy_mandated(self):
        ep = EscalationPolicy(
            policy_id="e1", name="e1", policy_mandated_review=True
        )
        assert ep.should_escalate(0)


# ════════════════════════════════════════════════════════════════════
# ADAPTIVE & STAGE-BASED ROUTING TESTS
# ════════════════════════════════════════════════════════════════════


class TestRouteChangeRecord:

    def test_creation(self):
        rcr = RouteChangeRecord(
            from_model_id="model_a",
            to_model_id="model_b",
            reason="verification_failure",
            trigger_type=FallbackTriggerType.VERIFICATION_FAILURE,
            policy_id="fb_001",
        )
        assert rcr.from_model_id == "model_a"
        assert rcr.to_model_id == "model_b"
        assert isinstance(rcr.changed_at, datetime)


class TestAdaptiveRoute:

    def test_creation(self):
        route = Route(
            agent_id="a1",
            agent_version_id="v1",
            model_id="m1",
            model_version_id="v1",
            provider_id="p1",
        )
        ar = AdaptiveRoute(current_route=route)
        assert ar.state == AdaptiveRouteState.ACTIVE
        assert ar.can_fallback

    def test_record_change(self):
        route = Route(
            agent_id="a1",
            agent_version_id="v1",
            model_id="m1",
            model_version_id="v1",
            provider_id="p1",
        )
        ar = AdaptiveRoute(current_route=route, max_fallback_attempts=2)

        change = RouteChangeRecord(
            from_model_id="m1", to_model_id="m2", reason="timeout"
        )
        ar.record_change(change)
        assert ar.fallback_attempts == 1
        assert len(ar.change_history) == 1
        assert ar.can_fallback

        change2 = RouteChangeRecord(
            from_model_id="m2", to_model_id="m3", reason="failure"
        )
        ar.record_change(change2)
        assert ar.fallback_attempts == 2
        assert not ar.can_fallback


class TestStageRouting:

    def test_stage_route_preference(self):
        pref = StageRoutePreference(
            stage=ExecutionStage.PLANNING,
            model_profile="reasoning",
        )
        assert pref.stage == ExecutionStage.PLANNING
        assert pref.model_profile == "reasoning"
        assert pref.override_model_id is None

    def test_stage_routing_config(self):
        config = StageRoutingConfig(
            stages=[
                StageRoutePreference(
                    stage=ExecutionStage.PLANNING, model_profile="reasoning"
                ),
                StageRoutePreference(
                    stage=ExecutionStage.RETRIEVAL, model_profile="tool_efficiency"
                ),
                StageRoutePreference(
                    stage=ExecutionStage.SYNTHESIS, model_profile="quality"
                ),
            ]
        )
        pref = config.get_stage_preference(ExecutionStage.PLANNING)
        assert pref is not None
        assert pref.model_profile == "reasoning"

        assert config.get_stage_preference(ExecutionStage.VERIFICATION) is None


# ════════════════════════════════════════════════════════════════════
# PROVIDER HEALTH STATE TESTS
# ════════════════════════════════════════════════════════════════════


class TestProviderHealthState:

    def test_creation(self):
        phs = ProviderHealthState(
            provider_id="provider_a",
            status=ProviderHealthStatus.AVAILABLE,
            latency_p50_ms=120.0,
        )
        assert phs.is_available
        assert phs.is_healthy

    def test_degraded_is_available_not_healthy(self):
        phs = ProviderHealthState(
            provider_id="p1", status=ProviderHealthStatus.DEGRADED
        )
        assert phs.is_available
        assert not phs.is_healthy

    def test_unavailable(self):
        phs = ProviderHealthState(
            provider_id="p1", status=ProviderHealthStatus.UNAVAILABLE
        )
        assert not phs.is_available
        assert not phs.is_healthy

    def test_unknown(self):
        phs = ProviderHealthState(
            provider_id="p1", status=ProviderHealthStatus.UNKNOWN
        )
        assert not phs.is_available

    def test_health_hash_deterministic(self):
        phs = ProviderHealthState(
            provider_id="p1", status=ProviderHealthStatus.AVAILABLE
        )
        h1 = phs.health_hash()
        h2 = phs.health_hash()
        assert h1 == h2
        assert len(h1) == 16

    def test_different_status_different_hash(self):
        phs1 = ProviderHealthState(
            provider_id="p1", status=ProviderHealthStatus.AVAILABLE
        )
        phs2 = ProviderHealthState(
            provider_id="p1", status=ProviderHealthStatus.DEGRADED
        )
        assert phs1.health_hash() != phs2.health_hash()


# ════════════════════════════════════════════════════════════════════
# CAPABILITY MATCH RESULT TESTS
# ════════════════════════════════════════════════════════════════════


class TestCapabilityMatchResult:

    def test_creation(self):
        mr = CapabilityMatchResult(
            capability_id="web_research",
            required=True,
            matched=True,
            proficiency=ProficiencyLevel.PRODUCTION,
        )
        assert mr.matched


class TestCapabilityMatchSummary:

    def test_all_required_met(self):
        summary = CapabilityMatchSummary(
            entity_id="a1",
            entity_type="agent",
            matches=[
                CapabilityMatchResult("c1", required=True, matched=True),
                CapabilityMatchResult("c2", required=True, matched=True),
                CapabilityMatchResult("c3", required=False, matched=False),
            ],
        )
        assert summary.all_required_met
        assert summary.match_score == pytest.approx(2 / 3)
        assert summary.missing_required == []

    def test_missing_required(self):
        summary = CapabilityMatchSummary(
            entity_id="a1",
            entity_type="agent",
            matches=[
                CapabilityMatchResult("c1", required=True, matched=True),
                CapabilityMatchResult("c2", required=True, matched=False),
            ],
        )
        assert not summary.all_required_met
        assert summary.missing_required == ["c2"]

    def test_empty_matches(self):
        summary = CapabilityMatchSummary(
            entity_id="a1", entity_type="agent"
        )
        assert summary.all_required_met  # vacuously true
        assert summary.match_score == 0.0
        assert summary.missing_required == []


# ════════════════════════════════════════════════════════════════════
# PYDANTIC SCHEMA VALIDATION TESTS
# ════════════════════════════════════════════════════════════════════


class TestPydanticSchemas:

    def test_capability_requirement_schema(self):
        schema = CapabilityRequirementSchema(capability_id="web_research")
        assert schema.capability_id == "web_research"

    def test_capability_requirement_schema_empty_id(self):
        with pytest.raises(Exception):
            CapabilityRequirementSchema(capability_id="")

    def test_resource_constraints_schema(self):
        schema = ResourceConstraintsSchema(max_cost_usd=2.0)
        assert schema.max_cost_usd == 2.0

    def test_resource_constraints_negative_rejected(self):
        with pytest.raises(Exception):
            ResourceConstraintsSchema(max_cost_usd=-1.0)

    def test_task_requirements_schema(self):
        schema = TaskRequirementsSchema(
            task_id="t1",
            description="Research task",
            capabilities=[
                CapabilityRequirementSchema(capability_id="web_research"),
            ],
            resources=ResourceConstraintsSchema(max_cost_usd=2.0),
        )
        assert schema.task_id == "t1"
        assert len(schema.capabilities) == 1

    def test_task_requirements_schema_empty_id(self):
        with pytest.raises(Exception):
            TaskRequirementsSchema(task_id="", description="test")

    def test_routing_policy_schema(self):
        schema = RoutingPolicySchema(
            policy_id="p1",
            name="Test Policy",
            constraints=RoutingConstraintsSchema(
                allowed_models=["model_a"],
            ),
            preferences=RoutingPreferencesSchema(
                quality_priority=RoutingPriority.HIGH,
            ),
        )
        assert schema.policy_id == "p1"
        assert schema.constraints.allowed_models == ["model_a"]

    def test_routing_profile_schema(self):
        schema = RoutingProfileSchema(
            profile_id="prof1",
            name="Test Profile",
            quality_priority=RoutingPriority.HIGH,
        )
        assert schema.quality_priority == RoutingPriority.HIGH

    def test_fallback_policy_schema(self):
        schema = FallbackPolicySchema(
            policy_id="fb1",
            name="Fallback",
            triggers=[FallbackTriggerType.PROVIDER_TIMEOUT],
            action=FallbackActionType.SWITCH_MODEL,
            max_attempts=3,
        )
        assert schema.action == FallbackActionType.SWITCH_MODEL

    def test_fallback_policy_schema_invalid_attempts(self):
        with pytest.raises(Exception):
            FallbackPolicySchema(
                policy_id="fb1", name="test", max_attempts=0
            )

    def test_routing_evidence_schema(self):
        schema = RoutingEvidenceSchema(
            source_type=EvidenceSourceType.ARENA_BENCHMARK,
            benchmark_id="bench_001",
            sample_count=50,
            metrics={"accuracy": 0.9},
        )
        assert schema.sample_count == 50

    def test_routing_evidence_schema_negative_samples(self):
        with pytest.raises(Exception):
            RoutingEvidenceSchema(
                source_type=EvidenceSourceType.ARENA_BENCHMARK,
                sample_count=-1,
            )

    def test_task_classification_schema(self):
        schema = TaskClassificationSchema(
            primary_domain=TaskDomain.RESEARCH,
            secondary_domains=[TaskDomain.WRITING],
            confidence=0.9,
        )
        assert schema.primary_domain == TaskDomain.RESEARCH

    def test_task_classification_schema_invalid_confidence(self):
        with pytest.raises(Exception):
            TaskClassificationSchema(confidence=2.0)

    def test_security_schema(self):
        schema = SecurityRequirementsSchema(
            external_write_actions=False,
            requires_sandbox=True,
        )
        assert schema.requires_sandbox is True

    def test_quality_schema(self):
        schema = QualityRequirementsSchema(
            overall=QualityLevel.HIGH,
            correctness=QualityLevel.STRICT,
        )
        assert schema.overall == QualityLevel.HIGH