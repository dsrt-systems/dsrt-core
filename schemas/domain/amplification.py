"""
DSRT C10 Amplification Contracts (C10 §3, D9).

Amplification is a sequence of STAGES applied to a model's execution
to improve quality. C10.4 ships 5 core strategies; the remaining 7
are addable through the StrategyRegistration contract without
modifying the engine.

Core strategies (D9):
  1. PLANNING          — explicit plan before answering
  2. CONTEXT_RETRIEVAL — hybrid memory/document retrieval
  3. TOOL_GROUNDED     — require tool-grounded answers for factual claims
  4. VERIFICATION      — post-hoc verification pass (C6 bridge)
  5. REPAIR            — fix detected issues from verification

Future strategies (added later via registry, not core modification):
  SELF_CONSISTENCY, DEBATE, CHAIN_OF_THOUGHT, REFLECTION,
  CONSTITUTIONAL, MULTI_AGENT, BEST_OF_N.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema, TimestampedSchema


class AmplificationStrategy(str, Enum):
    """The 5 core strategies shipped in C10.4."""
    PLANNING = "PLANNING"
    CONTEXT_RETRIEVAL = "CONTEXT_RETRIEVAL"
    TOOL_GROUNDED = "TOOL_GROUNDED"
    VERIFICATION = "VERIFICATION"
    REPAIR = "REPAIR"


class StageStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class AmplificationStage(TimestampedSchema):
    """One stage inside an amplification pipeline."""
    id: str
    execution_trace_id: str
    stage_index: int

    strategy: str  # Enum value, kept as string to support future strategies

    status: StageStatus

    # Inputs / outputs recorded as references
    inputs_ref: dict[str, Any] | None = None
    outputs_ref: dict[str, Any] | None = None

    # Metrics
    model_calls_made: int = 0
    tool_calls_made: int = 0
    tokens_consumed: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0

    # Did this stage actually improve the output?
    improvement_detected: bool | None = None
    improvement_rationale: str | None = None

    error_code: str | None = None
    error_message: str | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None


class StrategyRegistration(DSRTSchema):
    """Contract used to register a new amplification strategy (D9).

    Discovered by the AmplificationRuntime at startup. Adding a new
    strategy means dropping a file that exports a StrategyRegistration
    plus the strategy class. Engine code is untouched.
    """
    strategy_name: str                   # Unique strategy identifier
    display_name: str
    description: str
    version: str = "1.0.0"

    requires_tools: bool = False
    requires_retrieval: bool = False
    requires_verification: bool = False

    # Order hints for default pipelines (lower runs earlier)
    default_order_hint: int = 100

    # Enabled by default?
    enabled_by_default: bool = True


class AmplificationPlan(DSRTSchema):
    """The ordered plan of stages to execute."""
    strategies: list[str] = Field(default_factory=list)
    strategy_configs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    allow_partial_failure: bool = False
    max_total_stages: int = 10