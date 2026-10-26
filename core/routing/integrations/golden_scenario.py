"""C9.10 - Golden Scenario Runner (spec sections 57-58)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from core.routing.contracts import (
    AgentCapabilityProfile,
    ModelCapabilityProfile,
    RouteDecision,
    RoutingPolicy,
    RoutingProfile,
    TaskRequirements,
)
from core.routing.requirements.extractor import RequirementExtractor
from core.routing.analyzer.classifier import TaskClassifier
from core.routing.candidates.generator import CandidateGenerator
from core.routing.policies.engine import PolicyEngine
from core.routing.selector.router import IntelligenceRouter
from core.routing.selector.explainer import DecisionExplainer
from core.routing.evidence.aggregator import EvidenceAggregator
from core.routing.integrations.arena_bridge import ArenaEvidenceBridge


@dataclass
class GoldenScenarioResult:
    task_description: str
    requirements: TaskRequirements
    classification_domain: str
    evidence_count: int
    candidates_generated: int
    candidates_after_policy: int
    decision: RouteDecision
    explanation: dict[str, Any]
    pipeline_stages: list[str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GoldenScenarioRunner:
    def __init__(
        self,
        extractor: RequirementExtractor | None = None,
        classifier: TaskClassifier | None = None,
        generator: CandidateGenerator | None = None,
        policy_engine: PolicyEngine | None = None,
        router: IntelligenceRouter | None = None,
        explainer: DecisionExplainer | None = None,
        evidence_aggregator: EvidenceAggregator | None = None,
        arena_bridge: ArenaEvidenceBridge | None = None,
    ) -> None:
        self._extractor = extractor or RequirementExtractor()
        self._classifier = classifier or TaskClassifier()
        self._generator = generator or CandidateGenerator()
        self._policy_engine = policy_engine or PolicyEngine()
        self._router = router or IntelligenceRouter()
        self._explainer = explainer or DecisionExplainer()
        self._evidence_aggregator = evidence_aggregator or EvidenceAggregator()
        self._arena_bridge = arena_bridge or ArenaEvidenceBridge()

    def run(
        self,
        task_description: str,
        task_id: str | None = None,
        agents: list[AgentCapabilityProfile] | None = None,
        models: list[ModelCapabilityProfile] | None = None,
        worlds: list[dict[str, Any]] | None = None,
        policy: RoutingPolicy | None = None,
        profile: RoutingProfile | None = None,
        arena_runs: list[dict[str, Any]] | None = None,
    ) -> GoldenScenarioResult:
        stages: list[str] = []
        task_id = task_id or f"golden_{uuid.uuid4().hex[:12]}"

        stages.append("extract_requirements")
        requirements = self._extractor.extract(task_id=task_id, description=task_description)
        
        # Ensure task_id propagates safely even if it's a frozen dataclass
        if hasattr(requirements, "task_id") and getattr(requirements, "task_id") != task_id:
            try:
                requirements = replace(requirements, task_id=task_id)
            except Exception:
                try:
                    requirements.task_id = task_id
                except Exception:
                    pass

        stages.append("classify_task")
        classification = self._classifier.classify(task_description)

        stages.append("generate_candidates")
        candidates = self._generator.generate(
            requirements=requirements,
            eligible_agents=agents or [],
            eligible_models=models or [],
            available_worlds=worlds,
        )
        candidates_generated = len(candidates)

        stages.append("apply_policies")
        if policy is not None:
            eligible, rejected = self._policy_engine.apply(
                candidates=candidates, policy=policy,
                requirements=requirements, profile=profile,
            )
        else:
            eligible = [c for c in candidates if c.is_eligible]
            rejected = [c for c in candidates if not c.is_eligible]
        candidates_after_policy = len(eligible)

        stages.append("aggregate_evidence")
        evidence_map = {}
        arena_count = 0
        if arena_runs:
            arena_ev = self._arena_bridge.transform_runs_batch(arena_runs)
            arena_count = len(arena_ev)
            for ev in arena_ev:
                key = f"{ev.agent_version}:{ev.model_version}"
                if key not in evidence_map:
                    evidence_map[key] = self._evidence_aggregator.aggregate(key, [ev])

        stages.append("route")
        decision = self._router.route(
            requirements=requirements,
            candidates=eligible if eligible else candidates,
            policy=policy,
            profile=profile,
            evidence_map=evidence_map if evidence_map else None,
        )

        stages.append("generate_explanation")
        explanation = self._explainer.explain(decision)

        return GoldenScenarioResult(
            task_description=task_description,
            requirements=requirements,
            classification_domain=classification.primary_domain.value,
            evidence_count=arena_count,
            candidates_generated=candidates_generated,
            candidates_after_policy=candidates_after_policy,
            decision=decision,
            explanation=explanation,
            pipeline_stages=stages,
        )
