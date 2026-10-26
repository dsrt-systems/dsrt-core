"""
Unit tests for C11.2 Performance Intelligence Registry
Verifies evidence collection, Bayesian estimations, profile generation,
failure mode categorizations, configuration tracking, and database ORM persistence.
"""

import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from core.storage.database import Base
from core.storage.models.optimization_c11 import (
    PerformanceEvidenceModel,
    PerformanceProfileModel,
    ConfigurationProfileModel,
)
from schemas.domain.performance_intelligence import (
    PerformanceEvidence,
    ConfigurationProfile,
    PerformanceQuery,
    FailureCategory,
)
from core.optimization.performance_registry import (
    PerformanceIntelligenceRegistry,
    PerformanceEvidenceCollector,
    PerformanceEstimator,
    ModelProfiler,
    FailureAnalyzer,
)


# Root Cause Fix: Compile PostgreSQL JSONB columns as TEXT when executing against SQLite in tests
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"dsrt": None})

    tables = [
        PerformanceEvidenceModel.__table__,
        PerformanceProfileModel.__table__,
        ConfigurationProfileModel.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)

    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def registry():
    return PerformanceIntelligenceRegistry()


class TestPerformanceEstimator:
    def test_estimate_empty_evidence(self):
        estimator = PerformanceEstimator()
        metrics = estimator.estimate_metrics([])
        assert metrics.sample_count == 0
        assert metrics.reliability_rate == 0.85
        assert metrics.quality_mean == 0.70

    def test_estimate_bayesian_reliability(self):
        estimator = PerformanceEstimator()
        evidence_list = [
            PerformanceEvidence(
                evidence_id=f"e_{i}",
                model_id="gpt-4o",
                organization_id="org1",
                quality_score=0.9,
                reliability_score=1.0 if i < 8 else 0.0,
                latency_ms=100.0 * i,
                cost_usd=0.01,
            )
            for i in range(10)
        ]
        metrics = estimator.estimate_metrics(evidence_list)
        assert metrics.sample_count == 10
        # 8 successes + 2 prior alpha / (10 + 3 prior alpha+beta) = 10/13 ~ 0.7692
        assert 0.70 <= metrics.reliability_rate <= 0.80
        assert metrics.latency_p50_ms > 0
        assert metrics.latency_p90_ms >= metrics.latency_p50_ms


class TestFailureAnalyzer:
    def test_categorize_context_overflow(self):
        analyzer = FailureAnalyzer()
        cat = analyzer.categorize_error("ContextWindowExceeded", "Maximum prompt tokens limit overflowed")
        assert cat == FailureCategory.CONTEXT_OVERFLOW

    def test_categorize_format_violation(self):
        analyzer = FailureAnalyzer()
        cat = analyzer.categorize_error("JSONDecodeError", "Failed to parse expected JSON schema")
        assert cat == FailureCategory.FORMAT_VIOLATION

    def test_analyze_failures_breakdown(self):
        analyzer = FailureAnalyzer()
        evidence = [
            PerformanceEvidence(
                evidence_id="e1",
                model_id="m1",
                organization_id="o1",
                reliability_score=0.0,
                error_type="Timeout",
                error_message="Request timed out after 30s",
            ),
            PerformanceEvidence(
                evidence_id="e2",
                model_id="m1",
                organization_id="o1",
                reliability_score=1.0,
            ),
        ]
        res = analyzer.analyze_failures("m1", evidence)
        assert res.total_executions == 2
        assert res.total_failures == 1
        assert res.overall_failure_rate == 0.5
        assert res.primary_vulnerability == FailureCategory.TIMEOUT
        assert len(res.breakdown) == 1


class TestPerformanceRegistry:
    def test_ingest_and_query_profile(self, registry, db_session):
        # Ingest multiple consistent high-quality samples to build profile confidence
        for _ in range(5):
            evidence = PerformanceEvidence(
                evidence_id=str(uuid.uuid4()),
                model_id="claude-3-5-sonnet",
                organization_id="org_test",
                domain="software_engineering",
                intent="code_generation",
                complexity_level="high",
                quality_score=0.95,
                reliability_score=1.0,
                latency_ms=1200.0,
                input_tokens=500,
                output_tokens=200,
                cost_usd=0.005,
            )
            registry.ingest_evidence(evidence, session=db_session)

        query = PerformanceQuery(
            model_id="claude-3-5-sonnet",
            domain="software_engineering",
            intent="code_generation",
            complexity_level="high",
            min_samples=1,
        )

        profile = registry.get_profile(query, organization_id="org_test", session=db_session)
        assert profile.model_id == "claude-3-5-sonnet"
        assert profile.metrics.sample_count == 5
        # (5 * 0.95 + 0.70 * 3) / (5 + 3) = (4.75 + 2.1) / 8 = 6.85 / 8 = 0.85625 >= 0.85
        assert profile.metrics.quality_mean >= 0.85

    def test_register_configuration(self, registry, db_session):
        config = ConfigurationProfile(
            config_id="cfg_123",
            organization_id="org_test",
            model_id="gpt-4o",
            hyperparameters={"temperature": 0.2, "top_p": 0.95},
            system_prompt_hash="abc123hash",
            performance_summary={"quality": 0.92},
        )

        saved = registry.register_configuration(config, session=db_session)
        assert saved.config_id == "cfg_123"

        stored = db_session.query(ConfigurationProfileModel).filter_by(id="cfg_123").first()
        assert stored is not None
        assert stored.system_prompt_hash == "abc123hash"