"""
Base Evaluator Contract (C8 §24, §57-58).

All evaluators implement this interface. Evaluators are isolated
from the agent process (C8 §57) — they receive only permitted
evidence, not the agent's internal reasoning.

Evaluator types (C8 §24):
  DETERMINISTIC — code-based checks (schema, checksum, tests)
  MODEL_BASED   — LLM judges (writing quality, coherence)
  RULE_BASED    — policy rule evaluation
  HUMAN         — human reviewer
  HYBRID        — combination of the above
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from schemas.domain.arena import MetricResult
from schemas.domain.enums import EvaluatorType


@dataclass
class EvaluationInput:
    """Input to an evaluator (C8 §58).

    Contains only permitted evidence — the evaluator does NOT
    receive the agent's hidden chain-of-thought.
    """
    arena_run_id: str
    task_objective: str
    task_constraints: dict[str, Any] = field(default_factory=dict)
    success_conditions: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    world_state: dict[str, Any] = field(default_factory=dict)
    trajectory_summary: dict[str, Any] = field(default_factory=dict)
    verification_results: list[dict[str, Any]] = field(default_factory=list)
    resource_usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationOutput:
    """Output from an evaluator."""
    evaluator_id: str
    evaluator_type: EvaluatorType
    metrics: list[MetricResult] = field(default_factory=list)
    passed: bool = False
    summary: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class BaseEvaluator(ABC):
    """Abstract base class for all Arena evaluators (C8 §58).

    Evaluators MUST be independent from the agent (C8 §57).
    They receive only the EvaluationInput, which contains
    artifacts, world state, trajectory, and verification results —
    NOT the agent's internal reasoning or hidden state.
    """

    @property
    @abstractmethod
    def evaluator_id(self) -> str:
        """Unique identifier for this evaluator."""
        ...

    @property
    @abstractmethod
    def evaluator_type(self) -> EvaluatorType:
        """The type of evaluation this performs."""
        ...

    @property
    def version(self) -> str:
        """Evaluator version for reproducibility."""
        return "1.0"

    @abstractmethod
    async def evaluate(
        self,
        input_data: EvaluationInput,
    ) -> EvaluationOutput:
        """Evaluate an Arena run and produce metric results.

        Args:
            input_data: Permitted evidence about the run.

        Returns:
            EvaluationOutput with metrics and pass/fail.
        """
        ...

    def _metric(
        self,
        metric_id: str,
        metric_type: str,
        value: float | bool | str | None = None,
        evidence_refs: list[str] | None = None,
        explanation: str = "",
        confidence: float | None = None,
    ) -> MetricResult:
        """Helper to create a MetricResult."""
        from schemas.domain.enums import MetricType

        v_numeric = None
        v_boolean = None
        v_text = None

        if isinstance(value, bool):
            v_boolean = value
            v_numeric = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            v_numeric = float(value)
        elif isinstance(value, str):
            v_text = value

        return MetricResult(
            metric_id=metric_id,
            metric_type=MetricType(metric_type) if metric_type in [e.value for e in MetricType] else MetricType.TASK_SUCCESS,
            metric_version=self.version,
            value_numeric=v_numeric,
            value_boolean=v_boolean,
            value_text=v_text,
            evaluator_type=self.evaluator_type,
            evidence_refs=evidence_refs or [],
            confidence=confidence,
            explanation=explanation,
        )