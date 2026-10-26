"""
Capability Profiler (C8 §47).

Builds multi-dimensional capability profiles for agents, models,
and worlds based on accumulated Arena run data.

Instead of a single leaderboard number (C8 §2, §47):
    Agent A
    ├── Research    ████████  0.91
    ├── Planning    ███████   0.82
    ├── Tool Use    █████████ 0.95
    ├── Recovery    █████     0.63
    └── Software    ███       0.35
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.observability.logging import get_logger
from core.storage.models.arena import ArenaRunORM
from core.storage.models.arena_evaluation import PerformanceProfileORM


logger = get_logger("dsrt.arena.profiler")


@dataclass
class CapabilityScore:
    """Score for a single capability dimension."""
    capability: str
    score: float
    sample_count: int
    confidence: float
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class CapabilityProfile:
    """Multi-dimensional capability profile (C8 §47)."""
    entity_type: str  # "agent", "model", "world"
    entity_slug: str
    entity_version: str
    capabilities: list[CapabilityScore] = field(default_factory=list)
    overall_runs: int = 0
    overall_success_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "entity_type": self.entity_type,
            "entity_slug": self.entity_slug,
            "entity_version": self.entity_version,
            "overall_runs": self.overall_runs,
            "overall_success_rate": self.overall_success_rate,
            "capabilities": {
                c.capability: {
                    "score": c.score,
                    "samples": c.sample_count,
                    "confidence": c.confidence,
                }
                for c in self.capabilities
            },
        }


class CapabilityProfiler:
    """Builds capability profiles from Arena data (C8 §47).

    Usage:
        profiler = CapabilityProfiler(session)
        profile = await profiler.build_agent_profile(
            "research_intelligence", "1.0.0",
        )
        # profile.capabilities = [
        #   CapabilityScore("research", 0.91, 42, 0.87),
        #   CapabilityScore("planning", 0.82, 38, 0.79),
        #   ...
        # ]
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build_agent_profile(
        self,
        agent_slug: str,
        agent_version: str | None = None,
    ) -> CapabilityProfile:
        """Build a capability profile for an agent (C8 §47)."""
        runs = await self._load_runs(
            agent_slug=agent_slug,
            agent_version=agent_version,
        )
        profiles = await self._load_profiles_for_runs(
            [r.id for r in runs],
        )

        return self._build_profile(
            entity_type="agent",
            entity_slug=agent_slug,
            entity_version=agent_version or "latest",
            runs=runs,
            profiles=profiles,
        )

    async def build_model_profile(
        self,
        model_slug: str,
        model_version: str | None = None,
    ) -> CapabilityProfile:
        """Build a capability profile for a model."""
        runs = await self._load_runs(
            model_slug=model_slug,
            model_version=model_version,
        )
        profiles = await self._load_profiles_for_runs(
            [r.id for r in runs],
        )

        return self._build_profile(
            entity_type="model",
            entity_slug=model_slug,
            entity_version=model_version or "latest",
            runs=runs,
            profiles=profiles,
        )

    def _build_profile(
        self,
        entity_type: str,
        entity_slug: str,
        entity_version: str,
        runs: list[ArenaRunORM],
        profiles: list[PerformanceProfileORM],
    ) -> CapabilityProfile:
        """Build a profile from runs and performance data."""
        total_runs = len(runs)
        completed_runs = sum(
            1 for r in runs if r.status == "COMPLETED"
        )
        success_rate = (
            completed_runs / total_runs if total_runs > 0 else 0.0
        )

        # Group profiles by benchmark to get per-capability scores
        benchmark_scores: dict[str, list[float]] = {}
        for p in profiles:
            # Use benchmark_id as a proxy for capability
            # In a full implementation, this would map to benchmark metadata
            dims = p.dimensions or {}
            for dim, score in dims.items():
                if dim not in benchmark_scores:
                    benchmark_scores[dim] = []
                benchmark_scores[dim].append(score)

        capabilities: list[CapabilityScore] = []
        for cap, scores in sorted(benchmark_scores.items()):
            mean_score = sum(scores) / len(scores) if scores else 0.0
            confidence = min(1.0, len(scores) / 5.0)

            capabilities.append(CapabilityScore(
                capability=cap,
                score=round(mean_score, 3),
                sample_count=len(scores),
                confidence=round(confidence, 2),
            ))

        return CapabilityProfile(
            entity_type=entity_type,
            entity_slug=entity_slug,
            entity_version=entity_version,
            capabilities=capabilities,
            overall_runs=total_runs,
            overall_success_rate=round(success_rate, 3),
        )

    async def _load_runs(
        self,
        agent_slug: str | None = None,
        agent_version: str | None = None,
        model_slug: str | None = None,
        model_version: str | None = None,
        limit: int = 500,
    ) -> list[ArenaRunORM]:
        """Load Arena runs matching the criteria."""
        stmt = select(ArenaRunORM)
        if agent_slug:
            stmt = stmt.where(ArenaRunORM.agent_slug == agent_slug)
        if agent_version:
            stmt = stmt.where(ArenaRunORM.agent_version == agent_version)
        if model_slug:
            stmt = stmt.where(ArenaRunORM.model_slug == model_slug)
        if model_version:
            stmt = stmt.where(ArenaRunORM.model_version == model_version)
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _load_profiles_for_runs(
        self, run_ids: list[str],
    ) -> list[PerformanceProfileORM]:
        """Load performance profiles for a set of run IDs."""
        if not run_ids:
            return []
        stmt = select(PerformanceProfileORM).where(
            PerformanceProfileORM.arena_run_id.in_(run_ids),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())