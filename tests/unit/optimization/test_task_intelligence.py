"""
Unit tests for C11.1 Task Intelligence Analyzer
Verifies classification, complexity scoring, risk profiling, constraint extraction,
dependency graph parsing, validation, and database ORM persistence.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.storage.database import Base
from core.storage.models.optimization_c11 import TaskProfileModel, OptimizationRequestModel
from schemas.domain.task_intelligence import (
    TaskDomain,
    TaskIntent,
    TaskComplexityLevel,
    RiskLevel,
    OptimizationGoal,
    TaskIntelligenceRequest,
)
from core.optimization.task_intelligence import (
    TaskIntelligenceAnalyzer,
    TaskClassifier,
    ConstraintExtractor,
    DependencyAnalyzer,
)


@pytest.fixture
def db_session():
    """
    Create an isolated in-memory SQLite session with schema translation for testing.

    Root Cause Fix:
    Base.metadata specifies schema='dsrt'. SQLite in-memory does not have a schema 'dsrt'.
    Using execution_options(schema_translate_map={"dsrt": None}) instructs SQLAlchemy to strip
    the 'dsrt.' schema prefix for SQLite test execution without altering production ORM mappings.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"dsrt": None})

    tables = [
        TaskProfileModel.__table__,
        OptimizationRequestModel.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)

    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def analyzer():
    return TaskIntelligenceAnalyzer()


class TestTaskClassifier:
    def test_classify_software_engineering_code_gen(self):
        classifier = TaskClassifier()
        text = "Write a python function to refactor async database queries"
        payload = {"code": "def query(): pass"}
        res = classifier.classify_domain_and_intent(text, payload)
        assert res.primary_domain == TaskDomain.SOFTWARE_ENGINEERING
        assert res.primary_intent in (TaskIntent.CODE_GENERATION, TaskIntent.REFACTORING)

    def test_classify_data_analysis(self):
        classifier = TaskClassifier()
        text = "Compute statistics, mean and variance of pandas dataframe dataset"
        payload = {}
        res = classifier.classify_domain_and_intent(text, payload)
        assert res.primary_domain == TaskDomain.DATA_ANALYSIS
        assert res.primary_intent == TaskIntent.STATISTICAL_ANALYSIS

    def test_classify_devops(self):
        classifier = TaskClassifier()
        text = "Deploy docker container to kubernetes cluster with helm chart pipeline"
        payload = {}
        res = classifier.classify_domain_and_intent(text, payload)
        assert res.primary_domain == TaskDomain.DEVOPS

    def test_classify_multi_domain(self):
        classifier = TaskClassifier()
        text = (
            "Write a python function and class to refactor async code, "
            "compute pandas dataframe csv statistics correlation regression metrics, "
            "and deploy docker kubernetes helm terraform ci/cd pipeline to aws"
        )
        payload = {}
        res = classifier.classify_domain_and_intent(text, payload)
        assert res.primary_domain == TaskDomain.MULTI_DOMAIN
        assert len(res.secondary_domains) >= 2

    def test_complexity_trivial(self):
        classifier = TaskClassifier()
        text = "Hello world"
        payload = {}
        comp = classifier.compute_complexity(text, payload)
        assert comp.level == TaskComplexityLevel.TRIVIAL
        assert comp.score < 0.2

    def test_complexity_high(self):
        classifier = TaskClassifier()
        text = "Because we need to derive the hypothesis and evaluate edge cases and tradeoffs " * 20
        text += " ```python\nclass Big:\n  pass\n``` " * 5
        payload = {"steps": ["a", "b", "c", "d", "e"]}
        comp = classifier.compute_complexity(text, payload)
        assert comp.score >= 0.5
        assert comp.level in (
            TaskComplexityLevel.MEDIUM,
            TaskComplexityLevel.HIGH,
            TaskComplexityLevel.VERY_HIGH,
        )

    def test_evaluate_risk_low(self):
        classifier = TaskClassifier()
        text = "Summarize this public article about baking bread"
        risk = classifier.evaluate_risk(text, {})
        assert risk.overall_level == RiskLevel.LOW
        assert risk.score < 0.2
        assert len(risk.high_risk_flags) == 0

    def test_evaluate_risk_critical(self):
        classifier = TaskClassifier()
        text = (
            "Execute drop table on DB, private_key auth secret with "
            "stripe credit card payment GDPR compliance"
        )
        risk = classifier.evaluate_risk(text, {})
        assert risk.overall_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        assert len(risk.high_risk_flags) >= 2
        assert risk.reversibility < 1.0


class TestConstraintExtractor:
    def test_extract_hard_constraints(self):
        extractor = ConstraintExtractor()
        provided = {
            "max_budget_usd": 5.0,
            "max_latency_ms": 2000,
            "min_quality_score": 0.85,
            "allowed_models": ["gpt-4o", "claude-3-5-sonnet"],
        }
        res = extractor.extract_constraints(provided, {})
        assert res.max_budget_usd == 5.0
        assert res.max_latency_ms == 2000
        assert res.min_quality_score == 0.85
        assert res.allowed_models == ["gpt-4o", "claude-3-5-sonnet"]
        assert len(res.hard_constraints) == 4

    def test_extract_soft_constraints(self):
        extractor = ConstraintExtractor()
        provided = {"target_latency_ms": 1000}
        res = extractor.extract_constraints(provided, {})
        assert len(res.soft_constraints) == 1
        assert res.soft_constraints[0].key == "target_latency_ms"


class TestDependencyAnalyzer:
    def test_single_node_fallback(self):
        analyzer = DependencyAnalyzer()
        graph = analyzer.analyze_dependencies({})
        assert len(graph.nodes) == 1
        assert graph.nodes[0].node_id == "step_1"
        assert graph.has_cycles is False

    def test_dag_topological_sort(self):
        analyzer = DependencyAnalyzer()
        payload = {
            "steps": [
                {"id": "fetch", "name": "Fetch Data"},
                {"id": "process", "name": "Process Data", "depends_on": ["fetch"]},
                {"id": "store", "name": "Store Data", "depends_on": ["process"]},
            ]
        }
        graph = analyzer.analyze_dependencies(payload)
        assert graph.has_cycles is False
        assert graph.execution_order == ["fetch", "process", "store"]

    def test_cycle_detection(self):
        analyzer = DependencyAnalyzer()
        payload = {
            "steps": [
                {"id": "A", "depends_on": ["B"]},
                {"id": "B", "depends_on": ["A"]},
            ]
        }
        graph = analyzer.analyze_dependencies(payload)
        assert graph.has_cycles is True
        assert len(graph.execution_order) == 2


class TestTaskIntelligenceAnalyzer:
    def test_analyze_request_end_to_end(self, analyzer):
        req = TaskIntelligenceRequest(
            task_id="task_123",
            organization_id="org_abc",
            task_description="Refactor Python script for async database connection with budget limit",
            payload={"max_budget_usd": 2.50},
            optimization_goal=OptimizationGoal.MINIMIZE_COST,
        )
        profile = analyzer.analyze(req)
        assert profile.task_id == "task_123"
        assert profile.organization_id == "org_abc"
        assert profile.classification.primary_domain == TaskDomain.SOFTWARE_ENGINEERING
        assert profile.constraints.max_budget_usd == 2.50
        assert profile.metadata["optimization_goal"] == "minimize_cost"

    def test_analyze_persists_to_db(self, analyzer, db_session):
        req = TaskIntelligenceRequest(
            task_id="task_persist_1",
            organization_id="org_persist",
            task_description="Build a REST API endpoint",
            optimization_goal=OptimizationGoal.BALANCED,
        )
        profile = analyzer.analyze(req, session=db_session)

        stored_profile = (
            db_session.query(TaskProfileModel).filter_by(id=profile.profile_id).first()
        )
        assert stored_profile is not None
        assert stored_profile.task_id == "task_persist_1"
        assert stored_profile.primary_domain == TaskDomain.SOFTWARE_ENGINEERING.value

        stored_opt_req = (
            db_session.query(OptimizationRequestModel)
            .filter_by(task_profile_id=profile.profile_id)
            .first()
        )
        assert stored_opt_req is not None
        assert stored_opt_req.optimization_goal == "balanced"

    def test_validate_policy_limits_valid(self, analyzer):
        req = TaskIntelligenceRequest(
            task_id="task_val",
            organization_id="org_val",
            task_description="Analyze dataset",
            provided_constraints={"max_budget_usd": 10.0, "max_latency_ms": 5000},
        )
        profile = analyzer.analyze(req)
        is_valid, violations = analyzer.validate_policy_limits(
            profile, max_org_budget_usd=50.0, max_org_latency_ms=10000
        )
        assert is_valid is True
        assert len(violations) == 0

    def test_validate_policy_limits_exceeded(self, analyzer):
        req = TaskIntelligenceRequest(
            task_id="task_val_fail",
            organization_id="org_val",
            task_description="Analyze dataset",
            provided_constraints={"max_budget_usd": 500.0},
        )
        profile = analyzer.analyze(req)
        is_valid, violations = analyzer.validate_policy_limits(
            profile, max_org_budget_usd=50.0
        )
        assert is_valid is False
        assert len(violations) == 1
        assert "exceeds org policy limit" in violations[0]

    def test_missing_required_fields_raises_error(self, analyzer):
        with pytest.raises(ValueError, match="task_id and organization_id are required"):
            req = TaskIntelligenceRequest(
                task_id="",
                organization_id="org",
                task_description="Sample",
            )
            analyzer.analyze(req)

        with pytest.raises(ValueError, match="task_description or payload must be provided"):
            req = TaskIntelligenceRequest(
                task_id="t1",
                organization_id="org",
                task_description="",
                payload={},
            )
            analyzer.analyze(req)