# Path: core/execution/api/experiments.py
"""
Experiment HTTP API (/api/v1/experiments).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.execution.integration.contracts import ExecutionRequest
from core.execution.integration.unified_engine import UnifiedExecutionEngine


class CreateExperimentBody(BaseModel):
    workspace_id: str
    task_id: str
    configurations: List[Dict[str, Any]] = Field(default_factory=list)
    evaluation_suite_id: Optional[str] = None
    budget: Dict[str, Any] = Field(default_factory=dict)
    isolation_required: bool = True
    model_selection: Dict[str, Any] = Field(default_factory=dict)
    user_permissions: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


def build_experiments_router(engine: UnifiedExecutionEngine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])

    @router.post("")
    async def create_and_run_experiment(body: CreateExperimentBody) -> Dict[str, Any]:
        if len(body.configurations) < 2:
            raise HTTPException(
                status_code=400,
                detail="configurations must contain at least 2 entries",
            )
        req = ExecutionRequest(
            workspace_id=body.workspace_id,
            task_id=body.task_id,
            protocol="paired",
            model_selection=body.model_selection,
            budget=body.budget,
            configurations=body.configurations,
            evaluation_suite_id=body.evaluation_suite_id,
            isolation_required=body.isolation_required,
            user_permissions=body.user_permissions,
            metadata=body.metadata,
        )
        execution_id = await engine.create(req)
        validation = await engine.validate(execution_id)
        if not validation.valid:
            raise HTTPException(status_code=400, detail={"errors": validation.errors})
        result = await engine.execute(execution_id)
        return result.model_dump(mode="json")

    @router.get("/{experiment_id}")
    async def get_experiment(experiment_id: str) -> Dict[str, Any]:
        result = await engine.get_result(experiment_id)
        if result is None:
            raise HTTPException(status_code=404, detail="experiment not found")
        return result.model_dump(mode="json")

    @router.get("/{experiment_id}/comparison")
    async def get_comparison(experiment_id: str) -> Dict[str, Any]:
        result = await engine.get_result(experiment_id)
        if result is None:
            raise HTTPException(status_code=404, detail="experiment not found")
        if not result.comparison:
            raise HTTPException(status_code=404, detail="comparison not available")
        return result.comparison

    return router