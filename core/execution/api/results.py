# Path: core/execution/api/results.py
"""
Results / evaluation / cost read APIs.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from core.execution.integration.unified_engine import UnifiedExecutionEngine


def build_results_router(engine: UnifiedExecutionEngine) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["results"])

    @router.get("/executions/{execution_id}/evaluation")
    async def get_evaluation(execution_id: str) -> Dict[str, Any]:
        result = await engine.get_result(execution_id)
        if result is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return result.evaluation or {}

    @router.get("/executions/{execution_id}/cost")
    async def get_cost(execution_id: str) -> Dict[str, Any]:
        result = await engine.get_result(execution_id)
        if result is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return result.economics or {}

    @router.get("/experiments/{experiment_id}/results")
    async def get_experiment_results(experiment_id: str) -> Dict[str, Any]:
        result = await engine.get_result(experiment_id)
        if result is None:
            raise HTTPException(status_code=404, detail="experiment not found")
        return {
            "execution_id": result.execution_id,
            "status": result.status,
            "evaluation": result.evaluation,
            "economics": result.economics,
            "comparison": result.comparison,
            "artifacts": result.artifacts,
        }

    return router