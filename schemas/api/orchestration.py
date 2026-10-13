"""
Orchestration API Schemas (C5 §58).

Request/response schemas for the Orchestration REST API.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import (
    DelegationStatus,
    NodeStatus,
    OrchestrationStatus,
    PlanStatus,
)
from schemas.domain.orchestration import (
    PlanConstraints,
    PlanNode,
    PlanDependency,
    StatePatch,
)


# =============================================================================
# Plan API
# =============================================================================


class CreatePlanRequest(DSRTSchema):
    """POST /api/v1/tasks/{task_id}/plans"""
    objective: str = Field(..., min_length=1)
    constraints: PlanConstraints = Field(default_factory=PlanConstraints)
    nodes: list[PlanNode] = Field(default_factory=list)
    dependencies: list[PlanDependency] = Field(default_factory=list)
    preferred_agents: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanResponse(DSRTSchema):
    """Plan detail response."""
    id: str
    task_id: str
    current_version: int
    status: PlanStatus
    objective: str
    created_at: str
    updated_at: str


class PlanVersionResponse(DSRTSchema):
    """Plan version detail with full graph."""
    id: str
    plan_id: str
    version: int
    graph_hash: str
    reason: str
    nodes: list[PlanNode]
    dependencies: list[PlanDependency]
    constraints: PlanConstraints
    created_at: str


class PlanValidationResponse(DSRTSchema):
    """POST /api/v1/plans/{plan_id}/validate"""
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# =============================================================================
# Execution API
# =============================================================================


class ExecutePlanRequest(DSRTSchema):
    """POST /api/v1/plans/{plan_id}/execute"""
    plan_version_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestrationExecutionResponse(DSRTSchema):
    """Orchestration execution detail."""
    id: str
    task_id: str
    plan_id: str
    plan_version_id: str
    status: OrchestrationStatus
    active_nodes: list[str]
    completed_nodes: list[str]
    failed_nodes: list[str]
    started_at: str | None
    completed_at: str | None


class NodeExecutionResponse(DSRTSchema):
    """Node execution detail."""
    id: str
    orchestration_execution_id: str
    plan_node_key: str
    attempt: int
    status: NodeStatus
    agent_slug: str | None
    started_at: str | None
    completed_at: str | None
    error_code: str | None


class GraphResponse(DSRTSchema):
    """GET /api/v1/executions/{id}/graph"""
    plan_version_id: str
    nodes: list[dict[str, Any]]
    dependencies: list[dict[str, Any]]
    node_statuses: dict[str, str]


# =============================================================================
# State API
# =============================================================================


class ApplyStatePatchRequest(DSRTSchema):
    """POST /api/v1/executions/{id}/state/patches"""
    patches: list[StatePatch] = Field(..., min_length=1)


class SharedStateResponse(DSRTSchema):
    """GET /api/v1/executions/{id}/state"""
    version: int
    data: dict[str, Any]


# =============================================================================
# Delegation API
# =============================================================================


class DelegateRequest(DSRTSchema):
    """POST /api/v1/executions/{id}/delegate"""
    capability: str = Field(..., min_length=1)
    objective: str = Field(..., min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)


class DelegationResponse(DSRTSchema):
    """Delegation detail."""
    id: str
    requested_capability: str
    selected_agent_slug: str | None
    status: DelegationStatus
    depth: int


# =============================================================================
# Replan API
# =============================================================================


class ReplanRequest(DSRTSchema):
    """POST /api/v1/executions/{id}/replan"""
    reason: str = Field(..., min_length=1)
    affected_nodes: list[str] = Field(default_factory=list)
    new_nodes: list[PlanNode] = Field(default_factory=list)
    new_dependencies: list[PlanDependency] = Field(default_factory=list)


# =============================================================================
# Checkpoint API
# =============================================================================


class CheckpointResponse(DSRTSchema):
    """Checkpoint detail."""
    id: str
    orchestration_execution_id: str
    plan_version_id: str
    node_states: dict[str, str]
    created_at: str


class RestoreCheckpointRequest(DSRTSchema):
    """POST /api/v1/executions/{id}/restore"""
    checkpoint_id: str