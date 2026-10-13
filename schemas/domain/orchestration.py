"""
Orchestration Domain Schemas (C5 §4-9, §19-23, §37-39, §50-57).

Defines the complete orchestration data model: plans, graphs, nodes,
dependencies, executions, checkpoints, delegations, state patches,
replans, and policies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema
from schemas.domain.enums import (
    DependencyType,
    DelegationStatus,
    MergePolicy,
    NodeStatus,
    NodeType,
    OrchestrationStatus,
    PlanStatus,
    RecoveryAction,
    StatePatchOperation,
)
from schemas.domain.execution import ResourceLimits


# =============================================================================
# Plan & Graph
# =============================================================================


class PlanNode(DSRTSchema):
    """A single executable unit inside a plan (C5 §9)."""
    node_key: str = Field(..., min_length=1, max_length=120, description="Unique key within the plan")
    name: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    node_type: NodeType = NodeType.AGENT_TASK
    agent_slug: str | None = None
    agent_version: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, description="node_keys this node depends on")
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = None
    verification_policy: str | None = None
    resource_limits: dict[str, Any] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


class PlanDependency(DSRTSchema):
    """A directed edge in the task DAG (C5 §12)."""
    source_node_key: str
    target_node_key: str
    dependency_type: DependencyType = DependencyType.HARD
    condition: str | None = Field(default=None, description="Expression for CONDITION dependencies")


class PlanConstraints(DSRTSchema):
    """Resource and policy constraints for a plan (C5 §39)."""
    max_duration_seconds: int | None = None
    max_cost_usd: float | None = None
    max_nodes: int = Field(default=100, ge=1)
    max_parallel_nodes: int = Field(default=5, ge=1)
    max_depth: int = Field(default=20, ge=1)
    allow_delegation: bool = True
    allow_dynamic_replanning: bool = True
    require_approval_for: list[str] = Field(default_factory=list)


class Plan(TimestampedSchema):
    """An orchestration plan describing how an objective will be achieved (C5 §7)."""
    id: str
    task_id: str
    organization_id: str
    current_version: int = 1
    status: PlanStatus = PlanStatus.CREATED
    objective: str = ""


class PlanVersion(TimestampedSchema):
    """An immutable version of a plan (C5 §7, §64)."""
    id: str
    plan_id: str
    version: int
    planner_model: str | None = None
    planner_configuration: dict[str, Any] = Field(default_factory=dict)
    graph_hash: str = ""
    reason: str = ""
    nodes: list[PlanNode] = Field(default_factory=list)
    dependencies: list[PlanDependency] = Field(default_factory=list)
    constraints: PlanConstraints = Field(default_factory=PlanConstraints)


class PlanRequest(DSRTSchema):
    """Request to create a plan for a task (C5 §6)."""
    task_id: str
    objective: str = Field(..., min_length=1)
    constraints: PlanConstraints = Field(default_factory=PlanConstraints)
    preferred_agents: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Orchestration Execution
# =============================================================================


class OrchestrationExecution(TimestampedSchema):
    """A running instance of a plan (C5 §50)."""
    id: str
    task_id: str
    plan_id: str
    plan_version_id: str
    organization_id: str
    status: OrchestrationStatus = OrchestrationStatus.CREATED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    active_nodes: list[str] = Field(default_factory=list)
    completed_nodes: list[str] = Field(default_factory=list)
    failed_nodes: list[str] = Field(default_factory=list)
    checkpoint_id: str | None = None


class NodeExecution(TimestampedSchema):
    """A concrete runtime attempt of a plan node (C5 §54)."""
    id: str
    orchestration_execution_id: str
    plan_node_key: str
    plan_version_id: str
    attempt: int = 1
    status: NodeStatus = NodeStatus.PENDING
    agent_slug: str | None = None
    agent_version: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    input_reference: dict[str, Any] | None = None
    output_reference: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    resource_usage: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Checkpoint
# =============================================================================


class OrchestrationCheckpoint(TimestampedSchema):
    """A durable snapshot of orchestration state (C5 §28, §55)."""
    id: str
    orchestration_execution_id: str
    plan_version_id: str
    graph_state: dict[str, Any] = Field(default_factory=dict)
    task_state_reference: str | None = None
    context_snapshot_reference: str | None = None
    memory_snapshot_reference: str | None = None
    node_states: dict[str, str] = Field(default_factory=dict, description="node_key -> NodeStatus")
    resource_state: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Delegation
# =============================================================================


class Delegation(TimestampedSchema):
    """An agent-to-agent delegation record (C5 §16, §57)."""
    id: str
    parent_node_execution_id: str
    orchestration_execution_id: str
    requested_capability: str
    selected_agent_slug: str | None = None
    selected_agent_version: str | None = None
    status: DelegationStatus = DelegationStatus.REQUESTED
    input_reference: dict[str, Any] | None = None
    output_reference: dict[str, Any] | None = None
    depth: int = Field(default=1, ge=1, description="Delegation nesting depth")
    budget_allocated: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime | None = None


# =============================================================================
# Shared State
# =============================================================================


class StatePatch(DSRTImmutableSchema):
    """A versioned patch to the shared orchestration state (C5 §21)."""
    path: str = Field(..., description="JSON Pointer path, e.g. '/research/findings'")
    operation: StatePatchOperation
    value: Any = None
    source: str = Field(..., description="Agent slug or system component")
    reason: str = ""
    expected_version: int | None = Field(default=None, description="For optimistic concurrency")


class SharedState(TimestampedSchema):
    """The shared state object for an orchestration execution."""
    id: str
    orchestration_execution_id: str
    version: int = 1
    data: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Replan
# =============================================================================


class Replan(TimestampedSchema):
    """Record of a replanning event (C5 §33-36, §56)."""
    id: str
    orchestration_execution_id: str
    previous_plan_version_id: str
    new_plan_version_id: str
    trigger: str = Field(..., description="What caused the replan")
    reason: str = ""
    affected_nodes: list[str] = Field(default_factory=list)
    preserved_nodes: list[str] = Field(default_factory=list)


# =============================================================================
# Orchestration Policy
# =============================================================================


class OrchestrationPolicy(DSRTSchema):
    """Organization-level orchestration governance (C5 §39)."""
    max_depth: int = Field(default=20, ge=1)
    max_nodes: int = Field(default=100, ge=1)
    max_parallel_nodes: int = Field(default=10, ge=1)
    allow_delegation: bool = True
    allow_dynamic_replanning: bool = True
    require_approval_for: list[str] = Field(default_factory=list)
    max_budget_usd: float | None = None
    max_delegation_depth: int = Field(default=5, ge=1)
    max_children_per_node: int = Field(default=20, ge=1)


# =============================================================================
# Merge
# =============================================================================


class MergeResult(DSRTSchema):
    """Result of merging parallel node outputs (C5 §45-46)."""
    merge_policy: MergePolicy = MergePolicy.CONFLICT_PRESERVING
    merged_output: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    source_node_keys: list[str] = Field(default_factory=list)