# Path: core/execution/integration/contracts.py
"""
Stable top-level execution contracts (protocol-agnostic).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExecutionRequest(BaseModel):
    """Top-level request independent of selected protocol."""

    workspace_id: str
    task_id: str
    protocol: str  # direct | amplified | paired
    model_selection: Dict[str, Any] = Field(default_factory=dict)
    agent_selection: Optional[Dict[str, Any]] = None
    execution_constraints: Dict[str, Any] = Field(default_factory=dict)
    budget: Dict[str, Any] = Field(default_factory=dict)
    context_reference: Optional[str] = None
    user_permissions: List[str] = Field(default_factory=list)
    # Paired / multi-config
    configurations: Optional[List[Dict[str, Any]]] = None
    evaluation_suite_id: Optional[str] = None
    isolation_required: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ValidationResult(BaseModel):
    valid: bool = True
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class PreparedExecution(BaseModel):
    execution_id: str
    workspace_id: str
    task_id: str
    protocol: str
    prepared_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    resolved_model: Optional[Dict[str, Any]] = None
    resolved_agent: Optional[Dict[str, Any]] = None
    snapshot_hash: Optional[str] = None
    resources: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProtocolExecutionResult(BaseModel):
    execution_id: str
    protocol: str
    status: str
    output: Optional[str] = None
    error: Optional[str] = None
    trace_id: Optional[str] = None
    evaluation: Optional[Dict[str, Any]] = None
    economics: Optional[Dict[str, Any]] = None
    artifacts: List[str] = Field(default_factory=list)
    run_evidence: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    execution_id: str
    workspace_id: str
    task_id: str
    protocol: str
    status: str
    output: Optional[str] = None
    error: Optional[str] = None
    trace_id: Optional[str] = None
    evaluation: Optional[Dict[str, Any]] = None
    economics: Optional[Dict[str, Any]] = None
    comparison: Optional[Dict[str, Any]] = None
    artifacts: List[str] = Field(default_factory=list)
    events_published: int = 0
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    completed_at: Optional[datetime.datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)