"""Domain schemas for Phase C10 Execution Engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.domain.enums import (
    C10ExecutionStatus,
    ExecutionMode,
    ExecutionProtocol,
    StepKind,
    StepStatus,
)


class ExecutionConfigurationBase(BaseModel):
    organization_id: str
    protocol: ExecutionProtocol = ExecutionProtocol.DIRECT
    mode: ExecutionMode = ExecutionMode.WORK
    model_identifier: str
    model_provider: str = "openai"
    system_prompt: Optional[str] = None
    parameters_json: Dict[str, Any] = Field(default_factory=dict)
    amplification_strategies: List[Any] = Field(default_factory=list)
    comparison_mode: Optional[Any] = None
    budget_limit_usd: Optional[float] = None
    timeout_seconds: int = 300


class ExecutionConfigurationCreate(ExecutionConfigurationBase):
    pass


class ExecutionConfiguration(ExecutionConfigurationBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ExecutionStep(BaseModel):
    """Domain step view.

    Accepts both domain names and live ORM column names so repository
    round-trips and protocol code stay consistent.
    """

    id: str
    trace_id: str
    step_number: int
    kind: StepKind
    status: StepStatus
    name: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    tokens_used: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def map_orm_fields(cls, data: Any) -> Any:
        if data is None:
            return data

        def _safe_str(v: Any) -> Optional[str]:
            return v if isinstance(v, str) else None

        def _safe_dict(v: Any) -> Dict[str, Any]:
            return v if isinstance(v, dict) else {}

        getter = None
        if hasattr(data, "__dict__") and not isinstance(data, dict):
            def getter(key: str, default: Any = None) -> Any:
                return getattr(data, key, default)
        elif isinstance(data, dict):
            raw = dict(data)

            def getter(key: str, default: Any = None) -> Any:
                return raw.get(key, default)
        else:
            return data

        input_data = _safe_dict(getter("input_data")) or _safe_dict(getter("inputs_ref"))
        output_data = getter("output_data") if getter("output_data") is not None else getter("outputs_ref")
        output_dict = _safe_dict(output_data) if isinstance(output_data, dict) else None

        mapped = {
            "id": getter("id"),
            "trace_id": getter("trace_id") if isinstance(getter("trace_id"), str) else getter("execution_trace_id"),
            "step_number": getter("step_number") if isinstance(getter("step_number"), int) else getter("step_index", 0),
            "kind": getter("kind"),
            "status": getter("status"),
            "name": getter("name"),
            "input_data": input_data,
            "output_data": output_dict,
            "error_message": _safe_str(getter("error_message")),
            "duration_ms": float(getter("duration_ms") or 0) if isinstance(getter("duration_ms"), (int, float)) else 0.0,
            "cost_usd": float(getter("cost_usd") or 0.0) if isinstance(getter("cost_usd"), (int, float)) else 0.0,
            "tokens_used": int(
                getter("tokens_used")
                if isinstance(getter("tokens_used"), int)
                else (getter("input_tokens") if isinstance(getter("input_tokens"), int) else 0)
                + (getter("output_tokens") if isinstance(getter("output_tokens"), int) else 0)
            ),
            "started_at": getter("started_at"),
            "completed_at": getter("completed_at"),
        }
        return mapped


class ExecutionTraceCreate(BaseModel):
    organization_id: str
    protocol: ExecutionProtocol
    mode: ExecutionMode
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class ExecutionTrace(BaseModel):
    """Domain trace view with ORM field mapping."""

    id: str
    organization_id: str
    configuration_id: str
    status: C10ExecutionStatus
    protocol: ExecutionProtocol
    mode: ExecutionMode
    pricing_snapshot_id: Optional[str] = None
    total_cost: float = 0.0
    total_tokens: int = 0
    duration_ms: float = 0.0
    total_steps: int = 0
    claims_count: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    admitted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def map_orm_fields(cls, data: Any) -> Any:
        if data is None:
            return data

        def _safe_str(v: Any) -> Optional[str]:
            return v if isinstance(v, str) else None

        def _safe_dict(v: Any) -> Dict[str, Any]:
            return v if isinstance(v, dict) else {}

        if hasattr(data, "__dict__") and not isinstance(data, dict):
            def getter(key: str, default: Any = None) -> Any:
                return getattr(data, key, default)
        elif isinstance(data, dict):
            def getter(key: str, default: Any = None) -> Any:
                return data.get(key, default)
        else:
            return data

        meta = _safe_dict(getter("error_metadata")) or _safe_dict(getter("metadata_json"))
        nested_meta = _safe_dict(meta.get("metadata_json"))

        pricing = _safe_str(getter("pricing_snapshot_id")) or _safe_str(meta.get("pricing_snapshot_id"))

        total_in = int(getter("total_input_tokens")) if isinstance(getter("total_input_tokens"), int) else 0
        total_out = int(getter("total_output_tokens")) if isinstance(getter("total_output_tokens"), int) else 0
        total_tokens = getter("total_tokens")
        if not isinstance(total_tokens, int):
            total_tokens = total_in + total_out

        total_cost = getter("total_cost")
        if not isinstance(total_cost, (int, float)):
            total_cost = getter("total_cost_usd") if isinstance(getter("total_cost_usd"), (int, float)) else 0.0

        duration_ms = getter("duration_ms")
        if not isinstance(duration_ms, (int, float)):
            duration_ms = getter("total_duration_ms") if isinstance(getter("total_duration_ms"), (int, float)) else 0.0

        total_steps = getter("total_steps")
        if not isinstance(total_steps, int):
            total_steps = getter("step_count") if isinstance(getter("step_count"), int) else 0

        claims_count = getter("claims_count")
        if not isinstance(claims_count, int):
            claims_count = meta.get("claims_count") if isinstance(meta.get("claims_count"), int) else 0

        return {
            "id": getter("id"),
            "organization_id": getter("organization_id"),
            "configuration_id": getter("configuration_id"),
            "status": getter("status"),
            "protocol": getter("protocol"),
            "mode": getter("mode"),
            "pricing_snapshot_id": pricing,
            "total_cost": float(total_cost),
            "total_tokens": int(total_tokens),
            "duration_ms": float(duration_ms),
            "total_steps": int(total_steps),
            "claims_count": int(claims_count),
            "error_code": _safe_str(getter("error_code")),
            "error_message": _safe_str(getter("error_message")),
            "metadata_json": nested_meta or {
                k: v for k, v in meta.items()
                if k not in ("metadata_json", "pricing_snapshot_id", "claims_count")
            },
            "created_at": getter("created_at"),
            "updated_at": getter("updated_at"),
            "admitted_at": getter("admitted_at"),
            "started_at": getter("started_at"),
            "completed_at": getter("completed_at"),
        }