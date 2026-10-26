"""
Phase C11.1: Task Intelligence Analyzer

Main entry point for task classification, complexity scoring, risk profiling,
constraint extraction, dependency graph analysis, and profile persistence.
"""

import uuid
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from schemas.domain.task_intelligence import (
    TaskIntelligenceRequest,
    TaskProfile,
)
from core.optimization.task_intelligence.classifier import TaskClassifier
from core.optimization.task_intelligence.extractor import ConstraintExtractor, DependencyAnalyzer
from core.storage.models.optimization_c11 import TaskProfileModel, OptimizationRequestModel


class TaskIntelligenceAnalyzer:
    """
    Main orchestrator for task intelligence analysis.
    Constructs comprehensive task profiles without executing policy mutations.
    """

    def __init__(
        self,
        classifier: Optional[TaskClassifier] = None,
        constraint_extractor: Optional[ConstraintExtractor] = None,
        dependency_analyzer: Optional[DependencyAnalyzer] = None,
    ):
        self.classifier = classifier or TaskClassifier()
        self.constraint_extractor = constraint_extractor or ConstraintExtractor()
        self.dependency_analyzer = dependency_analyzer or DependencyAnalyzer()

    def analyze(
        self,
        request: TaskIntelligenceRequest,
        session: Optional[Session] = None,
    ) -> TaskProfile:
        if not request.task_id or not request.organization_id:
            raise ValueError("task_id and organization_id are required for task analysis")

        if not request.task_description and not request.payload:
            raise ValueError("task_description or payload must be provided for task analysis")

        classification = self.classifier.classify_domain_and_intent(
            text=request.task_description,
            payload=request.payload,
        )

        complexity = self.classifier.compute_complexity(
            text=request.task_description,
            payload=request.payload,
        )

        risk = self.classifier.evaluate_risk(
            text=request.task_description,
            payload=request.payload,
        )

        constraints = self.constraint_extractor.extract_constraints(
            provided=request.provided_constraints,
            payload=request.payload,
        )

        dependencies = self.dependency_analyzer.analyze_dependencies(
            payload=request.payload,
        )

        profile_id = str(uuid.uuid4())

        profile = TaskProfile(
            profile_id=profile_id,
            task_id=request.task_id,
            organization_id=request.organization_id,
            classification=classification,
            complexity=complexity,
            risk=risk,
            constraints=constraints,
            dependencies=dependencies,
            metadata={
                "optimization_goal": request.optimization_goal.value,
                "payload_keys": list(request.payload.keys()),
            },
        )

        if session is not None:
            db_profile = TaskProfileModel(
                id=profile.profile_id,
                task_id=profile.task_id,
                organization_id=profile.organization_id,
                primary_domain=profile.classification.primary_domain.value,
                primary_intent=profile.classification.primary_intent.value,
                complexity_score=profile.complexity.score,
                complexity_level=profile.complexity.level.value,
                risk_level=profile.risk.overall_level.value,
                risk_score=profile.risk.score,
                created_at=profile.created_at,
            )
            db_profile.set_profile_data(profile.model_dump(mode="json"))
            session.add(db_profile)

            opt_req_id = str(uuid.uuid4())
            db_request = OptimizationRequestModel(
                id=opt_req_id,
                task_profile_id=profile.profile_id,
                organization_id=request.organization_id,
                optimization_goal=request.optimization_goal.value,
                status="analyzed",
                created_at=profile.created_at,
            )
            db_request.set_metadata(request.model_dump(mode="json"))
            session.add(db_request)
            session.commit()

        return profile

    def validate_policy_limits(
        self,
        profile: TaskProfile,
        max_org_budget_usd: float = 100.0,
        max_org_latency_ms: float = 300000.0,
    ) -> Tuple[bool, List[str]]:
        violations = []

        if profile.constraints.max_budget_usd is not None:
            if profile.constraints.max_budget_usd > max_org_budget_usd:
                violations.append(
                    f"Requested budget limit ${profile.constraints.max_budget_usd:.2f} exceeds org policy limit ${max_org_budget_usd:.2f}"
                )

        if profile.constraints.max_latency_ms is not None:
            if profile.constraints.max_latency_ms > max_org_latency_ms:
                violations.append(
                    f"Requested latency limit {profile.constraints.max_latency_ms}ms exceeds org policy limit {max_org_latency_ms}ms"
                )

        if profile.risk.overall_level == "critical" and profile.constraints.security_isolation_level == "none":
            violations.append("Critical risk tasks cannot request disabled security isolation")

        return len(violations) == 0, violations