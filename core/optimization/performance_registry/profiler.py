"""
Phase C11.2: Model & Configuration Profiler

Constructs multidimensional performance profiles per (model_id, domain, intent, complexity_level) context.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from schemas.domain.performance_intelligence import (
    PerformanceEvidence,
    PerformanceProfile,
    ConfigurationProfile,
)
from core.optimization.performance_registry.estimator import PerformanceEstimator
from core.optimization.performance_registry.failure_analyzer import FailureAnalyzer
from core.storage.models.optimization_c11 import PerformanceProfileModel, ConfigurationProfileModel


class ModelProfiler:
    """Generates and persists performance and configuration profiles."""

    def __init__(
        self,
        estimator: Optional[PerformanceEstimator] = None,
        failure_analyzer: Optional[FailureAnalyzer] = None,
    ):
        self.estimator = estimator or PerformanceEstimator()
        self.failure_analyzer = failure_analyzer or FailureAnalyzer()

    def build_profile(
        self,
        model_id: str,
        organization_id: str,
        evidence_list: List[PerformanceEvidence],
        domain: str = "all",
        intent: str = "all",
        complexity_level: str = "all",
        session: Optional[Session] = None,
    ) -> PerformanceProfile:
        metrics = self.estimator.estimate_metrics(evidence_list)
        failure_analysis = self.failure_analyzer.analyze_failures(model_id, evidence_list)

        profile_id = str(uuid.uuid4())
        profile = PerformanceProfile(
            profile_id=profile_id,
            model_id=model_id,
            organization_id=organization_id,
            domain=domain,
            intent=intent,
            complexity_level=complexity_level,
            metrics=metrics,
            failure_analysis=failure_analysis,
            updated_at=datetime.now(timezone.utc),
        )

        if session is not None:
            existing = session.query(PerformanceProfileModel).filter(
                PerformanceProfileModel.model_id == model_id,
                PerformanceProfileModel.organization_id == organization_id,
                PerformanceProfileModel.domain == domain,
                PerformanceProfileModel.intent == intent,
                PerformanceProfileModel.complexity_level == complexity_level,
            ).first()

            if existing:
                existing.sample_count = metrics.sample_count
                existing.quality_mean = metrics.quality_mean
                existing.reliability_rate = metrics.reliability_rate
                existing.latency_p50 = metrics.latency_p50_ms
                existing.latency_p90 = metrics.latency_p90_ms
                existing.cost_mean = metrics.cost_mean_usd
                existing.set_profile_data(profile.model_dump(mode="json"))
                existing.updated_at = profile.updated_at
            else:
                db_model = PerformanceProfileModel(
                    id=profile.profile_id,
                    model_id=profile.model_id,
                    organization_id=profile.organization_id,
                    domain=profile.domain,
                    intent=profile.intent,
                    complexity_level=profile.complexity_level,
                    sample_count=metrics.sample_count,
                    quality_mean=metrics.quality_mean,
                    reliability_rate=metrics.reliability_rate,
                    latency_p50=metrics.latency_p50_ms,
                    latency_p90=metrics.latency_p90_ms,
                    cost_mean=metrics.cost_mean_usd,
                    updated_at=profile.updated_at,
                )
                db_model.set_profile_data(profile.model_dump(mode="json"))
                session.add(db_model)

            session.commit()

        return profile

    def register_configuration_profile(
        self,
        config: ConfigurationProfile,
        session: Optional[Session] = None,
    ) -> ConfigurationProfile:
        if session is not None:
            existing = session.query(ConfigurationProfileModel).filter(
                ConfigurationProfileModel.id == config.config_id,
                ConfigurationProfileModel.organization_id == config.organization_id,
            ).first()

            if existing:
                existing.model_id = config.model_id
                existing.system_prompt_hash = config.system_prompt_hash
                existing.set_config_data(config.model_dump(mode="json"))
                existing.set_summary_data(config.performance_summary)
                existing.updated_at = datetime.now(timezone.utc)
            else:
                db_model = ConfigurationProfileModel(
                    id=config.config_id,
                    organization_id=config.organization_id,
                    model_id=config.model_id,
                    system_prompt_hash=config.system_prompt_hash,
                    created_at=config.created_at,
                    updated_at=datetime.now(timezone.utc),
                )
                db_model.set_config_data(config.model_dump(mode="json"))
                db_model.set_summary_data(config.performance_summary)
                session.add(db_model)

            session.commit()

        return config