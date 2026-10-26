"""
C11 Adaptive Intelligence & Economic Optimization — REST API.
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.storage.database import get_db_session
from schemas.domain.governance import OptimizationPolicy, OptimizationRequest
from schemas.domain.observability import (
    DecisionChainExplanation,
    ExecutionActuals,
    ReconciliationReport,
    SystemMetricsSummary,
)

router = APIRouter(prefix="/api/v1/optimization", tags=["optimization"])


def _sync_session(db: Any) -> Any:
    """Return the underlying sync Session when present (AsyncSession.sync_session)."""
    return getattr(db, "sync_session", db)


async def _safe_commit(db: Any) -> None:
    """Commit whether *db* is a sync Session or an AsyncSession."""
    # Prefer committing the sync session used by MasterOptimizationController.
    sync_db = _sync_session(db)
    commit = getattr(sync_db, "commit", None)
    if callable(commit):
        result = commit()
        if inspect.isawaitable(result):
            await result
        return

    commit = getattr(db, "commit", None)
    if callable(commit):
        result = commit()
        if inspect.isawaitable(result):
            await result


async def _safe_execute(db: Any, statement: Any) -> Any:
    """Execute a statement on either a sync Session or an AsyncSession."""
    execute = getattr(db, "execute", None)
    if not callable(execute):
        raise RuntimeError("Database session has no execute()")
    result = execute(statement)
    if inspect.isawaitable(result):
        result = await result
    return result


@router.post("/optimize")
async def optimize_request(
    request: OptimizationRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Trigger full end-to-end adaptive economic optimization."""
    from core.optimization.controller.master_controller import MasterOptimizationController

    sync_db = _sync_session(db)
    controller = MasterOptimizationController(db_session=sync_db)
    plan = controller.optimize(request)
    await _safe_commit(db)
    return plan.model_dump(mode="json")


@router.get("/decisions/{request_id}")
async def get_decision_explanation(
    request_id: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Retrieve decision chain explanation audit trail for a request."""
    from core.optimization.explainability.explainer import DecisionExplainer

    sync_db = _sync_session(db)
    explainer = DecisionExplainer(sync_db)
    explanation = explainer.explain_request(request_id, tenant_id)
    if not explanation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No decision audit trail found for request_id '{request_id}'",
        )
    return explanation.model_dump(mode="json")


@router.post("/reconcile")
async def reconcile_execution(
    actuals: ExecutionActuals,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Reconcile predicted plan metrics with actual execution telemetry."""
    from core.optimization.reconciliation.reconciler import PerformanceReconciler

    sync_db = _sync_session(db)
    reconciler = PerformanceReconciler(sync_db)
    report = reconciler.reconcile(actuals)
    await _safe_commit(db)
    return report.model_dump(mode="json")


@router.get("/policies/{tenant_id}")
async def get_active_policy(
    tenant_id: str,
    user_id: str | None = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Get active optimization policy for tenant/user."""
    from core.optimization.policy.enforcer import PolicyEnforcer

    sync_db = _sync_session(db)
    enforcer = PolicyEnforcer(db_session=sync_db)
    policy = enforcer.get_active_policy(tenant_id, user_id)
    if policy is None:
        policy = enforcer.create_default_policy(organization_id=tenant_id, user_id=user_id)
        await _safe_commit(db)
    return policy.model_dump(mode="json")


@router.get("/metrics")
async def get_system_metrics(
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Retrieve real system-wide optimization metrics from the database."""

    total_plans = 0
    mae_cost = 0.0
    mae_latency = 0.0
    total_fallbacks = 0
    total_savings = 0.0

    # Query without schema prefix first for SQLite test compatibility
    for table_name in ["optimization_snapshots", "dsrt.optimization_snapshots"]:
        try:
            res = await _safe_execute(db, text(f"SELECT COUNT(*) FROM {table_name}"))
            cnt = int(res.scalar() or 0)
            if cnt > 0:
                total_plans = cnt
                break
        except Exception:
            continue

    for table_name in ["reconciliation_reports", "dsrt.reconciliation_reports"]:
        try:
            result_recons = await _safe_execute(
                db,
                text(
                    f"SELECT "
                    f"  AVG(ABS(actual_cost_usd - predicted_cost_usd)) AS mae_cost, "
                    f"  AVG(ABS(actual_latency_ms - predicted_latency_ms)) AS mae_latency "
                    f"FROM {table_name}"
                ),
            )
            recon_row = result_recons.fetchone()
            mae_cost = float(recon_row[0]) if recon_row and recon_row[0] is not None else 0.0
            mae_latency = (
                float(recon_row[1]) if recon_row and recon_row[1] is not None else 0.0
            )
            break
        except Exception:
            continue

    for table_name in ["fallback_states", "dsrt.fallback_states"]:
        try:
            result_fallbacks = await _safe_execute(
                db,
                text(
                    f"SELECT failure_count FROM {table_name} "
                    f"WHERE state_id = 'c11-global-fallback-state' LIMIT 1"
                ),
            )
            fb_row = result_fallbacks.fetchone()
            total_fallbacks = int(fb_row[0]) if fb_row and fb_row[0] is not None else 0
            break
        except Exception:
            continue

    for table_name in ["reconciliation_reports", "dsrt.reconciliation_reports"]:
        try:
            result_savings = await _safe_execute(
                db,
                text(
                    f"SELECT COALESCE(SUM(predicted_cost_usd - actual_cost_usd), 0) "
                    f"FROM {table_name} "
                    f"WHERE actual_cost_usd < predicted_cost_usd"
                ),
            )
            total_savings = float(result_savings.scalar() or 0.0)
            break
        except Exception:
            continue

    return SystemMetricsSummary(
        total_optimizations=total_plans,
        total_cost_saved_usd=round(total_savings, 4),
        avg_latency_reduction_pct=0.0,
        fallback_events_count=total_fallbacks,
        policy_violations_count=0,
        prediction_mae_cost=round(mae_cost, 4),
        prediction_mae_latency=round(mae_latency, 2),
    ).model_dump(mode="json")