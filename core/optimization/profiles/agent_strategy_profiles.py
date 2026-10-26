"""
Agent & Strategy Performance Profiles for C11.9.

Extends C11.2 Performance Intelligence Registry with:
- AgentPerformanceProfile tracking (agent × model combinations)
- StrategyPerformanceProfile tracking (amplification value measurement)
- Tenant-scoped evidence aggregation
"""

from typing import List, Optional
from sqlalchemy.orm import Session

from schemas.domain.governance import (
    AgentPerformanceProfile,
    StrategyPerformanceProfile,
)
from core.storage.models.optimization_c11_governance import (
    AgentPerformanceProfileModel,
    StrategyPerformanceProfileModel,
)


class AgentPerformanceRegistry:
    """Manages agent × model performance evidence with tenant isolation."""

    def __init__(self, db_session: Optional[Session] = None):
        self.db_session = db_session

    def record_agent_execution(
        self,
        organization_id: str,
        agent_id: str,
        agent_version: str,
        model_id: str,
        task_domain: str,
        success: bool,
        quality_score: float,
        latency_ms: float,
        cost_usd: float,
    ) -> AgentPerformanceProfile:
        """Records an agent execution outcome and updates profile."""
        profile = self.get_or_create_profile(
            organization_id=organization_id,
            agent_id=agent_id,
            agent_version=agent_version,
            model_id=model_id,
            task_domain=task_domain,
        )

        # Running averages update
        n = profile.total_runs
        new_n = n + 1

        new_success_rate = (profile.success_rate * n + (1.0 if success else 0.0)) / new_n
        new_avg_quality = (profile.avg_quality * n + quality_score) / new_n
        new_avg_latency = (profile.avg_latency_ms * n + latency_ms) / new_n
        new_avg_cost = (profile.avg_cost_usd * n + cost_usd) / new_n

        # Confidence improves with sample size (Bayesian saturation)
        new_confidence = min(1.0, 0.5 + (new_n / 100.0) * 0.5)

        profile.total_runs = new_n
        profile.success_rate = round(new_success_rate, 4)
        profile.avg_quality = round(new_avg_quality, 4)
        profile.avg_latency_ms = round(new_avg_latency, 2)
        profile.avg_cost_usd = round(new_avg_cost, 6)
        profile.confidence_score = round(new_confidence, 4)

        if self.db_session is not None:
            self._persist_profile(profile)

        return profile

    def get_or_create_profile(
        self,
        organization_id: str,
        agent_id: str,
        agent_version: str,
        model_id: str,
        task_domain: str,
    ) -> AgentPerformanceProfile:
        """Retrieves or creates an agent × model profile with tenant scoping."""
        if self.db_session is not None:
            db_m = (
                self.db_session.query(AgentPerformanceProfileModel)
                .filter(
                    AgentPerformanceProfileModel.organization_id == organization_id,
                    AgentPerformanceProfileModel.agent_id == agent_id,
                    AgentPerformanceProfileModel.agent_version == agent_version,
                    AgentPerformanceProfileModel.model_id == model_id,
                    AgentPerformanceProfileModel.task_domain == task_domain,
                )
                .first()
            )
            if db_m:
                return self._model_to_schema(db_m)

        return AgentPerformanceProfile(
            organization_id=organization_id,
            agent_id=agent_id,
            agent_version=agent_version,
            model_id=model_id,
            task_domain=task_domain,
        )

    def query_profiles(
        self,
        organization_id: str,
        agent_id: Optional[str] = None,
        task_domain: Optional[str] = None,
    ) -> List[AgentPerformanceProfile]:
        """Queries agent profiles with tenant isolation."""
        if self.db_session is None:
            return []

        query = self.db_session.query(AgentPerformanceProfileModel).filter(
            AgentPerformanceProfileModel.organization_id == organization_id
        )
        if agent_id:
            query = query.filter(AgentPerformanceProfileModel.agent_id == agent_id)
        if task_domain:
            query = query.filter(AgentPerformanceProfileModel.task_domain == task_domain)

        return [self._model_to_schema(m) for m in query.all()]

    def _model_to_schema(self, m: AgentPerformanceProfileModel) -> AgentPerformanceProfile:
        return AgentPerformanceProfile(
            profile_id=m.profile_id,
            organization_id=m.organization_id,
            agent_id=m.agent_id,
            agent_version=m.agent_version,
            model_id=m.model_id,
            task_domain=m.task_domain,
            total_runs=m.total_runs,
            success_rate=m.success_rate,
            avg_quality=m.avg_quality,
            avg_latency_ms=m.avg_latency_ms,
            avg_cost_usd=m.avg_cost_usd,
            confidence_score=m.confidence_score,
            updated_at=m.updated_at,
        )

    def _persist_profile(self, profile: AgentPerformanceProfile) -> None:
        db_m = (
            self.db_session.query(AgentPerformanceProfileModel)
            .filter(AgentPerformanceProfileModel.profile_id == profile.profile_id)
            .first()
        )
        if db_m is None:
            db_m = AgentPerformanceProfileModel(
                profile_id=profile.profile_id,
                organization_id=profile.organization_id,
                agent_id=profile.agent_id,
                agent_version=profile.agent_version,
                model_id=profile.model_id,
                task_domain=profile.task_domain,
                total_runs=profile.total_runs,
                success_rate=profile.success_rate,
                avg_quality=profile.avg_quality,
                avg_latency_ms=profile.avg_latency_ms,
                avg_cost_usd=profile.avg_cost_usd,
                confidence_score=profile.confidence_score,
            )
            self.db_session.add(db_m)
        else:
            db_m.total_runs = profile.total_runs
            db_m.success_rate = profile.success_rate
            db_m.avg_quality = profile.avg_quality
            db_m.avg_latency_ms = profile.avg_latency_ms
            db_m.avg_cost_usd = profile.avg_cost_usd
            db_m.confidence_score = profile.confidence_score

        self.db_session.commit()


class StrategyPerformanceRegistry:
    """Measures incremental value of amplification strategies with tenant isolation."""

    def __init__(self, db_session: Optional[Session] = None):
        self.db_session = db_session

    def record_strategy_outcome(
        self,
        organization_id: str,
        strategy_id: str,
        strategy_version: str,
        task_domain: str,
        baseline_quality: float,
        strategy_quality: float,
        incremental_cost_usd: float,
        incremental_latency_ms: float,
    ) -> StrategyPerformanceProfile:
        """Records a strategy outcome and updates incremental value profile."""
        profile = self.get_or_create_profile(
            organization_id=organization_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            task_domain=task_domain,
        )

        n = profile.sample_count
        new_n = n + 1

        new_baseline = (profile.baseline_quality * n + baseline_quality) / new_n
        new_strategy = (profile.strategy_quality * n + strategy_quality) / new_n
        new_improvement = new_strategy - new_baseline
        new_inc_cost = (profile.incremental_cost_usd * n + incremental_cost_usd) / new_n
        new_inc_latency = (profile.incremental_latency_ms * n + incremental_latency_ms) / new_n

        # Value ratio: quality improvement per dollar
        new_value_ratio = (
            new_improvement / new_inc_cost if new_inc_cost > 0.0001 else 0.0
        )

        new_confidence = min(1.0, 0.5 + (new_n / 100.0) * 0.5)

        profile.sample_count = new_n
        profile.baseline_quality = round(new_baseline, 4)
        profile.strategy_quality = round(new_strategy, 4)
        profile.quality_improvement = round(new_improvement, 4)
        profile.incremental_cost_usd = round(new_inc_cost, 6)
        profile.incremental_latency_ms = round(new_inc_latency, 2)
        profile.value_ratio = round(new_value_ratio, 4)
        profile.confidence_score = round(new_confidence, 4)

        if self.db_session is not None:
            self._persist_profile(profile)

        return profile

    def get_or_create_profile(
        self,
        organization_id: str,
        strategy_id: str,
        strategy_version: str,
        task_domain: str,
    ) -> StrategyPerformanceProfile:
        """Retrieves or creates a strategy profile with tenant scoping."""
        if self.db_session is not None:
            db_m = (
                self.db_session.query(StrategyPerformanceProfileModel)
                .filter(
                    StrategyPerformanceProfileModel.organization_id == organization_id,
                    StrategyPerformanceProfileModel.strategy_id == strategy_id,
                    StrategyPerformanceProfileModel.strategy_version == strategy_version,
                    StrategyPerformanceProfileModel.task_domain == task_domain,
                )
                .first()
            )
            if db_m:
                return self._model_to_schema(db_m)

        return StrategyPerformanceProfile(
            organization_id=organization_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            task_domain=task_domain,
        )

    def query_profiles(
        self,
        organization_id: str,
        strategy_id: Optional[str] = None,
        task_domain: Optional[str] = None,
    ) -> List[StrategyPerformanceProfile]:
        """Queries strategy profiles with tenant isolation."""
        if self.db_session is None:
            return []

        query = self.db_session.query(StrategyPerformanceProfileModel).filter(
            StrategyPerformanceProfileModel.organization_id == organization_id
        )
        if strategy_id:
            query = query.filter(StrategyPerformanceProfileModel.strategy_id == strategy_id)
        if task_domain:
            query = query.filter(StrategyPerformanceProfileModel.task_domain == task_domain)

        return [self._model_to_schema(m) for m in query.all()]

    def _model_to_schema(self, m: StrategyPerformanceProfileModel) -> StrategyPerformanceProfile:
        return StrategyPerformanceProfile(
            profile_id=m.profile_id,
            organization_id=m.organization_id,
            strategy_id=m.strategy_id,
            strategy_version=m.strategy_version,
            task_domain=m.task_domain,
            baseline_quality=m.baseline_quality,
            strategy_quality=m.strategy_quality,
            quality_improvement=m.quality_improvement,
            incremental_cost_usd=m.incremental_cost_usd,
            incremental_latency_ms=m.incremental_latency_ms,
            value_ratio=m.value_ratio,
            sample_count=m.sample_count,
            confidence_score=m.confidence_score,
            updated_at=m.updated_at,
        )

    def _persist_profile(self, profile: StrategyPerformanceProfile) -> None:
        db_m = (
            self.db_session.query(StrategyPerformanceProfileModel)
            .filter(StrategyPerformanceProfileModel.profile_id == profile.profile_id)
            .first()
        )
        if db_m is None:
            db_m = StrategyPerformanceProfileModel(
                profile_id=profile.profile_id,
                organization_id=profile.organization_id,
                strategy_id=profile.strategy_id,
                strategy_version=profile.strategy_version,
                task_domain=profile.task_domain,
                baseline_quality=profile.baseline_quality,
                strategy_quality=profile.strategy_quality,
                quality_improvement=profile.quality_improvement,
                incremental_cost_usd=profile.incremental_cost_usd,
                incremental_latency_ms=profile.incremental_latency_ms,
                value_ratio=profile.value_ratio,
                sample_count=profile.sample_count,
                confidence_score=profile.confidence_score,
            )
            self.db_session.add(db_m)
        else:
            db_m.baseline_quality = profile.baseline_quality
            db_m.strategy_quality = profile.strategy_quality
            db_m.quality_improvement = profile.quality_improvement
            db_m.incremental_cost_usd = profile.incremental_cost_usd
            db_m.incremental_latency_ms = profile.incremental_latency_ms
            db_m.value_ratio = profile.value_ratio
            db_m.sample_count = profile.sample_count
            db_m.confidence_score = profile.confidence_score

        self.db_session.commit()