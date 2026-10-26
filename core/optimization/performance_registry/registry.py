"""
Phase C11.2: Performance Intelligence Registry Main Service

Orchestrates evidence ingestion, model profiling, estimation, configuration tracking,
and profile persistence.
"""

from typing import List, Optional
from sqlalchemy.orm import Session

from schemas.domain.performance_intelligence import (
    PerformanceEvidence,
    PerformanceMetrics,
    PerformanceProfile,
    ConfigurationProfile,
    FailureAnalysisResult,
    PerformanceQuery,
)
from core.optimization.performance_registry.evidence import PerformanceEvidenceCollector
from core.optimization.performance_registry.estimator import PerformanceEstimator
from core.optimization.performance_registry.profiler import ModelProfiler
from core.optimization.performance_registry.failure_analyzer import FailureAnalyzer
from core.storage.models.optimization_c11 import PerformanceProfileModel, ConfigurationProfileModel


class PerformanceIntelligenceRegistry:
    """Main facade for performance intelligence tracking and profile retrieval."""

    def __init__(
        self,
        db: Optional[Session] = None,
        collector: Optional[PerformanceEvidenceCollector] = None,
        estimator: Optional[PerformanceEstimator] = None,
        profiler: Optional[ModelProfiler] = None,
        failure_analyzer: Optional[FailureAnalyzer] = None,
    ):
        self.db = db
        self.collector = collector or PerformanceEvidenceCollector()
        self.estimator = estimator or PerformanceEstimator()
        self.failure_analyzer = failure_analyzer or FailureAnalyzer()
        self.profiler = profiler or ModelProfiler(
            estimator=self.estimator,
            failure_analyzer=self.failure_analyzer,
        )

    def record_evidence(
        self,
        evidence: PerformanceEvidence,
        session: Optional[Session] = None,
    ) -> PerformanceEvidence:
        """Convenience alias for ingest_evidence (used by C8 ingester)."""
        return self.ingest_evidence(evidence, session=session)

    def ingest_evidence(
        self,
        evidence: PerformanceEvidence,
        session: Optional[Session] = None,
    ) -> PerformanceEvidence:
        sess = session or self.db
        saved = self.collector.record_evidence(evidence, session=sess)

        if sess is not None:
            evidence_list = self.collector.fetch_evidence(
                model_id=evidence.model_id,
                organization_id=evidence.organization_id,
                domain=evidence.domain,
                intent=evidence.intent,
                complexity_level=evidence.complexity_level,
                session=sess,
            )
            self.profiler.build_profile(
                model_id=evidence.model_id,
                organization_id=evidence.organization_id,
                evidence_list=evidence_list,
                domain=evidence.domain,
                intent=evidence.intent,
                complexity_level=evidence.complexity_level,
                session=sess,
            )

        return saved

    def get_model_profile(
        self,
        model_id: str,
        domain: str = "all",
        organization_id: str = "default-org",
    ) -> Optional[PerformanceProfile]:
        """Convenience method for workers: quick profile lookup by model and domain."""
        query = PerformanceQuery(
            model_id=model_id,
            domain=domain,
            intent="all",
            complexity_level="all",
            min_samples=1,
        )
        try:
            return self.get_profile(
                query=query,
                organization_id=organization_id,
                session=self.db,
            )
        except Exception:
            return None

    def get_profile(
        self,
        query: PerformanceQuery,
        organization_id: str,
        session: Optional[Session] = None,
    ) -> PerformanceProfile:
        sess = session or self.db
        if sess is not None:
            domain = query.domain or "all"
            intent = query.intent or "all"
            complexity = query.complexity_level or "all"

            db_profile = sess.query(PerformanceProfileModel).filter(
                PerformanceProfileModel.model_id == query.model_id,
                PerformanceProfileModel.organization_id == organization_id,
                PerformanceProfileModel.domain == domain,
                PerformanceProfileModel.intent == intent,
                PerformanceProfileModel.complexity_level == complexity,
            ).first()

            if db_profile and db_profile.sample_count >= query.min_samples:
                data = db_profile.get_profile_data()
                if data:
                    return PerformanceProfile(**data)

            evidence_list = self.collector.fetch_evidence(
                model_id=query.model_id,
                organization_id=organization_id,
                domain=query.domain,
                intent=query.intent,
                complexity_level=query.complexity_level,
                session=sess,
            )
            return self.profiler.build_profile(
                model_id=query.model_id,
                organization_id=organization_id,
                evidence_list=evidence_list,
                domain=domain,
                intent=intent,
                complexity_level=complexity,
                session=sess,
            )

        empty_evidence: List[PerformanceEvidence] = []
        return self.profiler.build_profile(
            model_id=query.model_id,
            organization_id=organization_id,
            evidence_list=empty_evidence,
            domain=query.domain or "all",
            intent=query.intent or "all",
            complexity_level=query.complexity_level or "all",
        )

    def register_configuration(
        self,
        config: ConfigurationProfile,
        session: Optional[Session] = None,
    ) -> ConfigurationProfile:
        return self.profiler.register_configuration_profile(config, session=session)

    def analyze_failures(
        self,
        model_id: str,
        organization_id: str,
        session: Optional[Session] = None,
    ) -> FailureAnalysisResult:
        sess = session or self.db
        evidence_list = self.collector.fetch_evidence(
            model_id=model_id,
            organization_id=organization_id,
            session=sess,
        )
        return self.failure_analyzer.analyze_failures(model_id, evidence_list)
