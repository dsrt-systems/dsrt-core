# tests/test_c9_candidates.py
"""
C9.4 — Candidate Generator & Policy Engine.

Tests candidate generation, hard constraint filtering,
soft preference scoring, and profile application.
"""

import pytest

from core.routing.candidates.generator import CandidateGenerator
from core.routing.contracts import (
    AgentCapabilityEntry,
    AgentCapabilityProfile,
    CapabilityMatchResult,
    CapabilityMatchSummary,
    CapabilityRequirement,
    ModelCapabilityEntry,
    ModelCapabilityProfile,
    ModelLimits,
    ResourceConstraints,
    RouteCandidate,
    RoutingConstraints,
    RoutingPolicy,
    RoutingPreferences,
    RoutingProfile,
    SecurityRequirements,
    TaskRequirements,
)
from core.routing.enums import (
    CapabilityImportance,
    EligibilityStatus,
    ModelCapabilityType,
    ProficiencyLevel,
    RejectionCategory,
    RoutingPriority,
)
from core.routing.policies.constraints import HardConstraintChecker
from core.routing.policies.engine import PolicyEngine
from core.routing.policies.preferences import PreferenceScorer
from core.routing.profiles.registry import RoutingProfileRegistry


# ════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════


def _agent(agent_id: str, caps: list[str]) -> AgentCapabilityProfile:
    return AgentCapabilityProfile(
        agent_id=agent_id,
        agent_version_id=f"{agent_id}_v1",
        capabilities=[
            AgentCapabilityEntry(
                capability_id=c, proficiency=ProficiencyLevel.PRODUCTION
            )
            for c in caps
        ],
    )


def _model(
    model_id: str,
    caps: list[ModelCapabilityType],
    provider: str = "provider_a",
    context: int | None = None,
) -> ModelCapabilityProfile:
    return ModelCapabilityProfile(
        model_id=model_id,
        model_version_id=f"{model_id}_v1",
        provider_id=provider,
        capabilities=[ModelCapabilityEntry(capability=c) for c in caps],
        limits=ModelLimits(context_tokens=context),
    )


def _reqs(
    task_id: str = "t1",
    caps: list[str] | None = None,
    required_tools: list[str] | None = None,
    max_cost: float | None = None,
    external_write: bool = False,
    sandbox: bool = False,
    max_input_tokens: int | None = None,
) -> TaskRequirements:
    return TaskRequirements(
        task_id=task_id,
        description="Test task",
        capabilities=[
            CapabilityRequirement(capability_id=c) for c in (caps or [])
        ],
        required_tools=required_tools or [],
        resources=ResourceConstraints(
            max_cost_usd=max_cost,
            max_input_tokens=max_input_tokens,
        ),
        security=SecurityRequirements(
            external_write_actions=external_write,
            requires_sandbox=sandbox,
        ),
    )


# ════════════════════════════════════════════════════════════════════
# CANDIDATE GENERATOR TESTS
# ════════════════════════════════════════════════════════════════════


class TestCandidateGenerator:

    def setup_method(self):
        self.gen = CandidateGenerator()

    def test_single_agent_single_model(self):
        reqs = _reqs()
        agents = [_agent("a1", ["web_research"])]
        models = [_model("m1", [ModelCapabilityType.REASONING])]

        candidates = self.gen.generate(reqs, agents, models)
        assert len(candidates) == 1
        assert candidates[0].agent_id == "a1"
        assert candidates[0].model_id == "m1"
        assert candidates[0].is_eligible

    def test_cartesian_product(self):
        reqs = _reqs()
        agents = [_agent("a1", ["x"]), _agent("a2", ["y"])]
        models = [
            _model("m1", [ModelCapabilityType.REASONING]),
            _model("m2", [ModelCapabilityType.VISION]),
        ]

        candidates = self.gen.generate(reqs, agents, models)
        assert len(candidates) == 4  # 2 agents × 2 models

    def test_with_worlds(self):
        reqs = _reqs()
        agents = [_agent("a1", ["x"])]
        models = [_model("m1", [ModelCapabilityType.REASONING])]
        worlds = [
            {"world_id": "w1", "world_version_id": "v1", "tools": ["web.search"]},
            {"world_id": "w2", "world_version_id": "v1", "tools": ["pdf.extract"]},
        ]

        candidates = self.gen.generate(reqs, agents, models, worlds)
        assert len(candidates) == 2
        assert candidates[0].world_id == "w1"
        assert candidates[1].world_id == "w2"

    def test_required_tools_missing_rejects(self):
        reqs = _reqs(required_tools=["web.search", "pdf.extract"])
        agents = [_agent("a1", ["x"])]
        models = [_model("m1", [ModelCapabilityType.REASONING])]
        worlds = [
            {"world_id": "w1", "world_version_id": "v1", "tools": ["web.search"]},
        ]

        candidates = self.gen.generate(reqs, agents, models, worlds)
        assert len(candidates) == 1
        assert not candidates[0].is_eligible
        assert candidates[0].rejections[0].category == RejectionCategory.TOOL_UNAVAILABLE

    def test_required_tools_satisfied(self):
        reqs = _reqs(required_tools=["web.search"])
        agents = [_agent("a1", ["x"])]
        models = [_model("m1", [ModelCapabilityType.REASONING])]
        worlds = [
            {"world_id": "w1", "world_version_id": "v1", "tools": ["web.search", "pdf.extract"]},
        ]

        candidates = self.gen.generate(reqs, agents, models, worlds)
        assert len(candidates) == 1
        assert candidates[0].is_eligible
        assert "web.search" in candidates[0].tools

    def test_preferred_tools_included_if_available(self):
        reqs = TaskRequirements(
            task_id="t1",
            description="Test",
            required_tools=["web.search"],
            preferred_tools=["pdf.extract", "vision.ocr"],
        )
        agents = [_agent("a1", ["x"])]
        models = [_model("m1", [ModelCapabilityType.REASONING])]
        worlds = [
            {"world_id": "w1", "world_version_id": "v1", "tools": ["web.search", "pdf.extract"]},
        ]

        candidates = self.gen.generate(reqs, agents, models, worlds)
        assert "web.search" in candidates[0].tools
        assert "pdf.extract" in candidates[0].tools
        assert "vision.ocr" not in candidates[0].tools  # not available

    def test_no_worlds_generates_none_world(self):
        reqs = _reqs()
        agents = [_agent("a1", ["x"])]
        models = [_model("m1", [ModelCapabilityType.REASONING])]

        candidates = self.gen.generate(reqs, agents, models)
        assert len(candidates) == 1
        assert candidates[0].world_id is None

    def test_context_window_constraint_fit(self):
        reqs = _reqs(max_input_tokens=200000)
        agents = [_agent("a1", ["x"])]
        models = [_model("m1", [ModelCapabilityType.REASONING], context=128000)]

        candidates = self.gen.generate(reqs, agents, models)
        assert candidates[0].constraint_fit["context_window"] is False

    def test_context_window_sufficient(self):
        reqs = _reqs(max_input_tokens=100000)
        agents = [_agent("a1", ["x"])]
        models = [_model("m1", [ModelCapabilityType.REASONING], context=200000)]

        candidates = self.gen.generate(reqs, agents, models)
        assert candidates[0].constraint_fit["context_window"] is True

    def test_capability_fit_populated(self):
        reqs = _reqs(caps=["reasoning"])
        agents = [_agent("a1", ["x"])]
        models = [_model("m1", [ModelCapabilityType.REASONING])]
        model_matches = {
            "m1": CapabilityMatchSummary(
                entity_id="m1",
                entity_type="model",
                matches=[
                    CapabilityMatchResult("reasoning", True, True),
                ],
            )
        }

        candidates = self.gen.generate(
            reqs, agents, models, model_matches=model_matches
        )
        assert candidates[0].capability_fit.get("model:reasoning") is True

    def test_generate_single_model(self):
        reqs = _reqs()
        agent = _agent("a1", ["x"])
        model = _model("m1", [ModelCapabilityType.REASONING])

        candidate = self.gen.generate_single_model(reqs, agent, model)
        assert candidate.agent_id == "a1"
        assert candidate.model_id == "m1"

    def test_empty_agents_returns_empty(self):
        reqs = _reqs()
        candidates = self.gen.generate(
            reqs, [], [_model("m1", [ModelCapabilityType.REASONING])]
        )
        assert len(candidates) == 0

    def test_empty_models_returns_empty(self):
        reqs = _reqs()
        candidates = self.gen.generate(reqs, [_agent("a1", ["x"])], [])
        assert len(candidates) == 0


# ════════════════════════════════════════════════════════════════════
# HARD CONSTRAINT CHECKER TESTS
# ════════════════════════════════════════════════════════════════════


class TestHardConstraintChecker:

    def setup_method(self):
        self.checker = HardConstraintChecker()

    def _make_candidate(
        self,
        agent: str = "a1",
        model: str = "m1",
        provider: str = "p1",
        world: str | None = "w1",
    ) -> RouteCandidate:
        return RouteCandidate(
            candidate_id="c1",
            agent_id=agent,
            agent_version_id=f"{agent}_v1",
            model_id=model,
            model_version_id=f"{model}_v1",
            provider_id=provider,
            world_id=world,
            constraint_fit={"tools_available": True, "context_window": True},
        )

    def test_all_pass(self):
        c = self._make_candidate()
        constraints = RoutingConstraints()
        reqs = _reqs()
        assert self.checker.check_all(c, constraints, reqs) is True
        assert c.is_eligible

    def test_model_denied(self):
        c = self._make_candidate(model="bad_model")
        constraints = RoutingConstraints(denied_models=["bad_model"])
        reqs = _reqs()
        assert self.checker.check_all(c, constraints, reqs) is False
        assert not c.is_eligible
        assert c.rejections[0].category == RejectionCategory.POLICY_DENIED

    def test_model_not_in_whitelist(self):
        c = self._make_candidate(model="m2")
        constraints = RoutingConstraints(allowed_models=["m1"])
        reqs = _reqs()
        assert self.checker.check_all(c, constraints, reqs) is False

    def test_agent_denied(self):
        c = self._make_candidate(agent="bad_agent")
        constraints = RoutingConstraints(denied_agents=["bad_agent"])
        reqs = _reqs()
        assert self.checker.check_all(c, constraints, reqs) is False

    def test_provider_denied(self):
        c = self._make_candidate(provider="bad_provider")
        constraints = RoutingConstraints(denied_providers=["bad_provider"])
        reqs = _reqs()
        assert self.checker.check_all(c, constraints, reqs) is False

    def test_external_write_violation(self):
        c = self._make_candidate()
        constraints = RoutingConstraints(external_write_actions=False)
        reqs = _reqs(external_write=True)
        assert self.checker.check_all(c, constraints, reqs) is False
        assert c.rejections[0].category == RejectionCategory.SECURITY_VIOLATION

    def test_external_write_allowed(self):
        c = self._make_candidate()
        constraints = RoutingConstraints(external_write_actions=True)
        reqs = _reqs(external_write=True)
        assert self.checker.check_all(c, constraints, reqs) is True

    def test_budget_exceeded(self):
        c = self._make_candidate()
        constraints = RoutingConstraints(max_cost_usd=1.0)
        reqs = _reqs(max_cost=5.0)
        assert self.checker.check_all(c, constraints, reqs) is False
        assert c.rejections[0].category == RejectionCategory.BUDGET_EXCEEDED

    def test_budget_within_limit(self):
        c = self._make_candidate()
        constraints = RoutingConstraints(max_cost_usd=10.0)
        reqs = _reqs(max_cost=5.0)
        assert self.checker.check_all(c, constraints, reqs) is True

    def test_sandbox_no_world(self):
        c = self._make_candidate(world=None)
        constraints = RoutingConstraints()
        reqs = _reqs(sandbox=True)
        assert self.checker.check_all(c, constraints, reqs) is False
        assert c.rejections[0].category == RejectionCategory.SECURITY_VIOLATION

    def test_sandbox_with_world(self):
        c = self._make_candidate(world="w1")
        constraints = RoutingConstraints()
        reqs = _reqs(sandbox=True)
        assert self.checker.check_all(c, constraints, reqs) is True

    def test_context_window_failure(self):
        c = self._make_candidate()
        c.constraint_fit["context_window"] = False
        constraints = RoutingConstraints()
        reqs = _reqs()
        assert self.checker.check_all(c, constraints, reqs) is False
        assert c.rejections[0].category == RejectionCategory.MISSING_CAPABILITY

    def test_multiple_rejections(self):
        c = self._make_candidate(model="bad", agent="bad")
        constraints = RoutingConstraints(
            denied_models=["bad"], denied_agents=["bad"]
        )
        reqs = _reqs()
        self.checker.check_all(c, constraints, reqs)
        assert len(c.rejections) >= 2


# ════════════════════════════════════════════════════════════════════
# PREFERENCE SCORER TESTS
# ════════════════════════════════════════════════════════════════════


class TestPreferenceScorer:

    def setup_method(self):
        self.scorer = PreferenceScorer()

    def _make_candidate(self, cap_fit: dict[str, bool] | None = None) -> RouteCandidate:
        return RouteCandidate(
            candidate_id="c1",
            agent_id="a1",
            agent_version_id="v1",
            model_id="m1",
            model_version_id="v1",
            provider_id="p1",
            capability_fit=cap_fit or {},
        )

    def test_score_with_evidence(self):
        c = self._make_candidate()
        prefs = RoutingPreferences(
            quality_priority=RoutingPriority.HIGH,
            cost_priority=RoutingPriority.LOW,
        )
        evidence = {"quality": 0.9, "reliability": 0.8, "latency": 0.7, "cost": 0.6}
        scores = self.scorer.score_candidate(c, prefs, evidence)

        assert scores["quality"] == pytest.approx(0.9 * 3.0)
        assert scores["cost"] == pytest.approx(0.6 * 1.0)

    def test_score_without_evidence(self):
        c = self._make_candidate({"a": True, "b": True, "c": False})
        prefs = RoutingPreferences()
        scores = self.scorer.score_candidate(c, prefs)
        # Quality estimated from cap_fit: 2/3 ≈ 0.667
        assert scores["quality"] > 0

    def test_rank_candidates(self):
        c1 = RouteCandidate(
            candidate_id="c1", agent_id="a1", agent_version_id="v1",
            model_id="m1", model_version_id="v1", provider_id="p1",
        )
        c2 = RouteCandidate(
            candidate_id="c2", agent_id="a1", agent_version_id="v1",
            model_id="m2", model_version_id="v1", provider_id="p1",
        )
        prefs = RoutingPreferences(quality_priority=RoutingPriority.HIGH)
        evidence = {
            "c1": {"quality": 0.9, "reliability": 0.9, "latency": 0.9, "cost": 0.9},
            "c2": {"quality": 0.3, "reliability": 0.3, "latency": 0.3, "cost": 0.3},
        }
        ranked = self.scorer.rank_candidates([c1, c2], prefs, evidence)
        assert len(ranked) == 2
        assert ranked[0][0].candidate_id == "c1"
        assert ranked[0][1] > ranked[1][1]

    def test_rank_excludes_rejected(self):
        c1 = RouteCandidate(
            candidate_id="c1", agent_id="a1", agent_version_id="v1",
            model_id="m1", model_version_id="v1", provider_id="p1",
        )
        c2 = RouteCandidate(
            candidate_id="c2", agent_id="a1", agent_version_id="v1",
            model_id="m2", model_version_id="v1", provider_id="p1",
        )
        c2.reject(RejectionCategory.POLICY_DENIED, "test")

        prefs = RoutingPreferences()
        ranked = self.scorer.rank_candidates([c1, c2], prefs)
        assert len(ranked) == 1
        assert ranked[0][0].candidate_id == "c1"


# ════════════════════════════════════════════════════════════════════
# POLICY ENGINE TESTS
# ════════════════════════════════════════════════════════════════════


class TestPolicyEngine:

    def setup_method(self):
        self.engine = PolicyEngine()

    def _make_candidates(self, n: int = 3) -> list[RouteCandidate]:
        return [
            RouteCandidate(
                candidate_id=f"c{i}",
                agent_id="a1",
                agent_version_id="v1",
                model_id=f"m{i}",
                model_version_id="v1",
                provider_id="p1",
                constraint_fit={"tools_available": True, "context_window": True},
            )
            for i in range(n)
        ]

    def test_all_eligible(self):
        candidates = self._make_candidates()
        policy = RoutingPolicy(policy_id="p1", name="Open")
        reqs = _reqs()

        eligible, rejected = self.engine.apply(candidates, policy, reqs)
        assert len(eligible) == 3
        assert len(rejected) == 0

    def test_model_restriction(self):
        candidates = self._make_candidates()
        policy = RoutingPolicy(
            policy_id="p1",
            name="Restricted",
            constraints=RoutingConstraints(allowed_models=["m0", "m1"]),
        )
        reqs = _reqs()

        eligible, rejected = self.engine.apply(candidates, policy, reqs)
        assert len(eligible) == 2
        assert len(rejected) == 1
        assert rejected[0].model_id == "m2"

    def test_budget_filter(self):
        candidates = self._make_candidates()
        policy = RoutingPolicy(
            policy_id="p1",
            name="Budget",
            constraints=RoutingConstraints(max_cost_usd=1.0),
        )
        reqs = _reqs(max_cost=5.0)

        eligible, rejected = self.engine.apply(candidates, policy, reqs)
        assert len(eligible) == 0
        assert len(rejected) == 3

    def test_profile_overrides_preferences(self):
        candidates = self._make_candidates()
        policy = RoutingPolicy(
            policy_id="p1",
            name="Default",
            preferences=RoutingPreferences(
                quality_priority=RoutingPriority.LOW,
            ),
        )
        profile = RoutingProfile(
            profile_id="custom",
            name="Quality First",
            quality_priority=RoutingPriority.HIGH,
        )
        reqs = _reqs()

        eligible, _ = self.engine.apply(
            candidates, policy, reqs, profile=profile
        )
        # Check that preference scores reflect the profile, not the policy
        scores = eligible[0].constraint_fit.get("preference_scores", {})
        assert "quality" in scores

    def test_pre_rejected_candidates_stay_rejected(self):
        candidates = self._make_candidates()
        candidates[0].reject(RejectionCategory.TOOL_UNAVAILABLE, "no tools")

        policy = RoutingPolicy(policy_id="p1", name="Open")
        reqs = _reqs()

        eligible, rejected = self.engine.apply(candidates, policy, reqs)
        assert len(eligible) == 2
        assert len(rejected) == 1

    def test_filter_only(self):
        candidates = self._make_candidates()
        policy = RoutingPolicy(
            policy_id="p1",
            name="Restricted",
            constraints=RoutingConstraints(denied_models=["m1"]),
        )
        reqs = _reqs()

        eligible, rejected = self.engine.filter_only(candidates, policy, reqs)
        assert len(eligible) == 2
        assert len(rejected) == 1
        # No preference scores in filter_only mode
        assert "preference_scores" not in eligible[0].constraint_fit

    def test_security_filter(self):
        candidates = self._make_candidates()
        policy = RoutingPolicy(
            policy_id="p1",
            name="No Write",
            constraints=RoutingConstraints(external_write_actions=False),
        )
        reqs = _reqs(external_write=True)

        eligible, rejected = self.engine.apply(candidates, policy, reqs)
        assert len(eligible) == 0
        assert all(
            r.rejections[0].category == RejectionCategory.SECURITY_VIOLATION
            for r in rejected
        )


# ════════════════════════════════════════════════════════════════════
# PROFILE REGISTRY TESTS
# ════════════════════════════════════════════════════════════════════


class TestRoutingProfileRegistry:

    def setup_method(self):
        self.registry = RoutingProfileRegistry()

    def test_builtin_profiles_loaded(self):
        assert self.registry.count == 5
        assert self.registry.has("builtin_fast")
        assert self.registry.has("builtin_balanced")
        assert self.registry.has("builtin_quality")
        assert self.registry.has("builtin_cost_controlled")
        assert self.registry.has("builtin_enterprise_strict")

    def test_get_profile(self):
        p = self.registry.get("builtin_fast")
        assert p is not None
        assert p.name == "FAST"

    def test_get_missing_returns_none(self):
        assert self.registry.get("nonexistent") is None

    def test_get_or_default(self):
        p = self.registry.get_or_default("nonexistent")
        assert p.profile_id == "builtin_balanced"

    def test_get_or_default_with_valid_id(self):
        p = self.registry.get_or_default("builtin_quality")
        assert p.profile_id == "builtin_quality"

    def test_register_custom(self):
        custom = RoutingProfile(
            profile_id="custom_research",
            name="Research Deep",
            quality_priority=RoutingPriority.HIGH,
        )
        self.registry.register(custom)
        assert self.registry.count == 6
        assert self.registry.has("custom_research")

    def test_cannot_override_builtin(self):
        override = RoutingProfile(
            profile_id="builtin_fast",
            name="Fake Fast",
        )
        with pytest.raises(ValueError, match="Cannot override built-in"):
            self.registry.register(override)

    def test_list_all(self):
        all_profiles = self.registry.list_all()
        assert len(all_profiles) == 5

    def test_list_builtin(self):
        builtin = self.registry.list_builtin()
        assert len(builtin) == 5


# ════════════════════════════════════════════════════════════════════
# INTEGRATION: GENERATOR → POLICY ENGINE
# ════════════════════════════════════════════════════════════════════


class TestGeneratorPolicyIntegration:
    """End-to-end: generate candidates then filter with policy."""

    def test_research_pipeline(self):
        gen = CandidateGenerator()
        engine = PolicyEngine()

        reqs = TaskRequirements(
            task_id="research_1",
            description="Research this company",
            capabilities=[
                CapabilityRequirement(capability_id="web_research"),
                CapabilityRequirement(capability_id="vision", required=False,
                                      importance=CapabilityImportance.OPTIONAL),
            ],
            required_tools=["web.search"],
            resources=ResourceConstraints(max_cost_usd=2.0),
            security=SecurityRequirements(external_write_actions=False),
        )

        agents = [
            _agent("research_agent", ["web_research", "citation"]),
            _agent("coding_agent", ["code_generation"]),
        ]
        models = [
            _model("model_a", [ModelCapabilityType.REASONING, ModelCapabilityType.TOOL_USE]),
            _model("model_b", [ModelCapabilityType.VISION]),
            _model("expensive_model", [ModelCapabilityType.REASONING], provider="provider_b"),
        ]
        worlds = [
            {"world_id": "research_world", "world_version_id": "v1", "tools": ["web.search", "pdf.extract"]},
        ]

        # Generate
        candidates = gen.generate(reqs, agents, models, worlds)
        assert len(candidates) == 6  # 2 agents × 3 models × 1 world

        # Apply policy
        policy = RoutingPolicy(
            policy_id="enterprise",
            name="Enterprise",
            constraints=RoutingConstraints(
                denied_providers=["provider_b"],
                external_write_actions=False,
            ),
            preferences=RoutingPreferences(
                quality_priority=RoutingPriority.HIGH,
            ),
        )

        eligible, rejected = engine.apply(candidates, policy, reqs)

        # provider_b model should be rejected
        assert any(
            r.model_id == "expensive_model" for r in rejected
        )
        # All eligible candidates should have web.search
        assert all("web.search" in c.tools for c in eligible)

    def test_strict_security_pipeline(self):
        gen = CandidateGenerator()
        engine = PolicyEngine()

        reqs = _reqs(external_write=True, sandbox=True)
        agents = [_agent("a1", ["x"])]
        models = [_model("m1", [ModelCapabilityType.REASONING])]

        # No world → sandbox fails
        candidates = gen.generate(reqs, agents, models)
        policy = RoutingPolicy(
            policy_id="strict",
            name="Strict",
            constraints=RoutingConstraints(external_write_actions=False),
        )

        eligible, rejected = engine.apply(candidates, policy, reqs)
        assert len(eligible) == 0
        # Should have both security violations
        assert len(rejected) >= 1