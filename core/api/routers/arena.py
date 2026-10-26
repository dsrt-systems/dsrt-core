"""
Arena REST API (C8 §55).

Endpoints for benchmark management, experiment execution,
Arena runs, trajectories, metrics, regressions, and capabilities.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.api.dependencies.database import get_session
from core.api.dependencies.security import require_active_organization
from core.arena.metrics.profiles import PerformanceProfileBuilder
from core.arena.registry.benchmark_registry import BenchmarkRegistry
from core.arena.registry.task_registry import TaskRegistry
from core.arena.runs.experiment_manager import ExperimentManager
from core.arena.runs.run_manager import ArenaRunManager
from core.arena.trajectories.store import TrajectoryStore
from core.security.context import SecurityContext
from core.storage.models.arena import (
    ArenaRunORM,
    BenchmarkORM,
    ExperimentORM,
)
from core.storage.models.arena_evaluation import (
    MetricResultORM,
    PerformanceProfileORM,
    TrajectoryORM,
)
from schemas.api.arena import (
    ArenaRunResponse,
    BenchmarkResponse,
    CapabilityProfileResponse,
    CreateBenchmarkRequest,
    CreateExperimentRequest,
    MetricResponse,
    RegressionResponse,
    TrajectoryResponse,
)


router = APIRouter(prefix="/api/v1", tags=["arena"])


# ------------------------------------------------------------------
# Benchmarks (C8 §55)
# ------------------------------------------------------------------


@router.post("/benchmarks", status_code=201)
async def create_benchmark(
    body: CreateBenchmarkRequest,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new benchmark."""
    registry = BenchmarkRegistry(session)
    orm = await registry.register(
        benchmark_id=body.id,
        version=body.version,
        name=body.name,
        description=body.description,
        benchmark_type=body.benchmark_type,
        task_suite_id=body.task_suite_id,
        world_slug=body.world_slug,
        metrics=body.metrics,
        organization_id=ctx.active_organization_id,
    )
    return {"id": orm.id, "version": orm.version, "status": "created"}


@router.get("/benchmarks")
async def list_benchmarks(
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all benchmarks."""
    registry = BenchmarkRegistry(session)
    benchmarks = await registry.list_benchmarks(
        organization_id=ctx.active_organization_id,
    )
    return {
        "benchmarks": [
            {
                "id": b.id,
                "version": b.version,
                "name": b.name,
                "benchmark_type": b.benchmark_type.value,
                "metrics": b.metrics,
            }
            for b in benchmarks
        ],
        "total": len(benchmarks),
    }


@router.get("/benchmarks/{benchmark_id}")
async def get_benchmark(
    benchmark_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a benchmark by ID."""
    registry = BenchmarkRegistry(session)
    try:
        b = await registry.get(benchmark_id)
        return b.model_dump()
    except Exception:
        return {"error": f"Benchmark '{benchmark_id}' not found."}


# ------------------------------------------------------------------
# Experiments (C8 §55)
# ------------------------------------------------------------------


@router.post("/experiments", status_code=201)
async def create_experiment(
    body: CreateExperimentRequest,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new experiment."""
    mgr = ExperimentManager(session)
    exp = await mgr.create_experiment(
        benchmark_id=body.benchmark_id,
        benchmark_version="1.0.0",
        name=body.name,
        configurations=body.configurations,
        repetitions=body.repetitions,
        organization_id=ctx.active_organization_id,
    )
    return {"id": exp.id, "status": exp.status, "configurations": len(body.configurations)}


@router.get("/experiments/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get experiment details with run summary."""
    mgr = ExperimentManager(session)
    exp = await mgr.get_experiment(experiment_id)
    if not exp:
        return {"error": "Experiment not found."}
    summary = await mgr.get_experiment_summary(experiment_id)
    return {
        "id": exp.id,
        "benchmark_id": exp.benchmark_id,
        "status": exp.status,
        "repetitions": exp.repetitions,
        "summary": summary,
    }


# ------------------------------------------------------------------
# Arena Runs (C8 §55)
# ------------------------------------------------------------------


@router.get("/arena/runs/{run_id}")
async def get_arena_run(
    run_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get Arena run details."""
    mgr = ArenaRunManager(session)
    try:
        run = await mgr.get_run(run_id)
        return {
            "id": run.id,
            "benchmark_id": run.benchmark_id,
            "experiment_id": run.experiment_id,
            "agent_slug": run.agent_slug,
            "agent_version": run.agent_version,
            "model_slug": run.model_slug,
            "world_slug": run.world_slug,
            "status": run.status,
            "configuration_hash": run.configuration_hash,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
    except Exception:
        return {"error": f"Arena run '{run_id}' not found."}


@router.get("/arena/runs/{run_id}/trajectory")
async def get_run_trajectory(
    run_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the trajectory for an Arena run."""
    store = TrajectoryStore(session)
    summary = await store.get_trajectory_summary(run_id)
    if not summary:
        return {"error": "No trajectory found for this run."}
    return summary


@router.get("/arena/runs/{run_id}/metrics")
async def get_run_metrics(
    run_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get metrics for an Arena run."""
    stmt = (
        select(MetricResultORM)
        .where(MetricResultORM.arena_run_id == run_id)
    )
    result = await session.execute(stmt)
    metrics = list(result.scalars().all())

    # Get performance profile dimensions
    profile_stmt = select(PerformanceProfileORM).where(
        PerformanceProfileORM.arena_run_id == run_id,
    )
    profile_result = await session.execute(profile_stmt)
    profile = profile_result.scalar_one_or_none()

    return {
        "arena_run_id": run_id,
        "metrics": [
            {
                "metric_id": m.metric_id,
                "metric_type": m.metric_type,
                "value_numeric": m.value_numeric,
                "value_boolean": m.value_boolean,
                "evaluator_type": m.evaluator_type,
                "confidence": m.confidence,
            }
            for m in metrics
        ],
        "dimensions": profile.dimensions if profile else {},
        "total": len(metrics),
    }


# ------------------------------------------------------------------
# Regressions & Capabilities (C8 §55)
# ------------------------------------------------------------------


@router.get("/arena/regressions")
async def get_regressions(
    benchmark_id: str,
    baseline_version: str,
    candidate_version: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get regression comparison between two versions."""
    from core.arena.regressions.detector import RegressionDetector
    from core.storage.models.arena_evaluation import RegressionORM

    stmt = (
        select(RegressionORM)
        .where(
            RegressionORM.benchmark_id == benchmark_id,
            RegressionORM.baseline_version == baseline_version,
            RegressionORM.candidate_version == candidate_version,
        )
    )
    result = await session.execute(stmt)
    regressions = list(result.scalars().all())

    return {
        "benchmark_id": benchmark_id,
        "baseline_version": baseline_version,
        "candidate_version": candidate_version,
        "results": [
            {
                "metric_type": r.metric_type,
                "baseline_value": r.baseline_value,
                "candidate_value": r.candidate_value,
                "delta": r.delta,
                "status": r.status,
            }
            for r in regressions
        ],
        "total": len(regressions),
    }


@router.get("/arena/capabilities")
async def get_capabilities(
    agent_slug: str,
    agent_version: str | None = None,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get capability profile for an agent."""
    from core.arena.regressions.profiler import CapabilityProfiler

    profiler = CapabilityProfiler(session)
    profile = await profiler.build_agent_profile(agent_slug, agent_version)
    return profile.to_dict()