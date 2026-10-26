# Path: core/execution/api/executions.py
"""
Execution HTTP API (/api/v1/executions).

Thin transport adapters over UnifiedExecutionEngine.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.execution.integration.contracts import ExecutionRequest
from core.execution.integration.unified_engine import UnifiedExecutionEngine


class CreateExecutionBody(BaseModel):
    workspace_id: str
    task_id: str
    protocol: str = "direct"
    model_selection: Dict[str, Any] = Field(default_factory=dict)
    agent_selection: Optional[Dict[str, Any]] = None
    execution_constraints: Dict[str, Any] = Field(default_factory=dict)
    budget: Dict[str, Any] = Field(default_factory=dict)
    context_reference: Optional[str] = None
    user_permissions: list[str] = Field(default_factory=list)
    configurations: Optional[list[Dict[str, Any]]] = None
    evaluation_suite_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


def build_executions_router(engine: UnifiedExecutionEngine) -> APIRouter:
    router = APIRouter(prefix="/api/v1/executions", tags=["executions"])

    @router.post("")
    async def create_execution(body: CreateExecutionBody) -> Dict[str, Any]:
        req = ExecutionRequest(**body.model_dump())
        execution_id = await engine.create(req)
        validation = await engine.validate(execution_id)
        if not validation.valid:
            raise HTTPException(status_code=400, detail={"errors": validation.errors})
        result = await engine.execute(execution_id)
        return result.model_dump(mode="json")

    @router.get("/{execution_id}")
    async def get_execution(execution_id: str) -> Dict[str, Any]:
        result = await engine.get_result(execution_id)
        if result is None:
            status = await engine.get_status(execution_id)
            return status
        return result.model_dump(mode="json")

    @router.get("/{execution_id}/status")
    async def get_status(execution_id: str) -> Dict[str, Any]:
        try:
            return await engine.get_status(execution_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="execution not found")

    @router.post("/{execution_id}/cancel")
    async def cancel_execution(execution_id: str) -> Dict[str, Any]:
        try:
            await engine.cancel(execution_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="execution not found")
        return {"execution_id": execution_id, "status": "CANCELLED"}

    return router