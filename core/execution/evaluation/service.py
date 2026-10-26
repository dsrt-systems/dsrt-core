"""
EvaluationEngine — Top-level evaluation service.

Orchestrates method selection, C8 suite resolution, method execution,
normalization, and result assembly.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from core.execution.evaluation.adapters import (
    BenchmarkRegistryAdapter,
    NullBenchmarkRegistryAdapter,
    SuiteDescriptor,
)
from core.execution.evaluation.contracts import (
    ConfidenceLevel,
    EvaluationFinding,
    EvaluationInput,
    EvaluationLimitation,
    EvaluatorRef,
    NormalizedMetric,
    ScoreKind,
)
from core.execution.evaluation.methods import (
    DeterministicEvaluator,
    EvidenceEvaluator,
    EvaluationMethodResult,
    RubricDefinition,
    RubricEvaluator,
)
from core.execution.evaluation.normalizer import MetricNormalizer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / result
# ---------------------------------------------------------------------------

class EvaluationRequest(BaseModel):
    """Incoming request to evaluate one execution."""

    input: EvaluationInput
    methods: list[str] = Field(
        default_factory=lambda: ["DETERMINISTIC", "EVIDENCE", "RUBRIC"]
    )
    rubric: RubricDefinition | None = None
    include_c8_suite: bool = True
    human_review_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationServiceResult(BaseModel):
    """
    Final evaluation package.

    If no reliable overall numeric score exists, ``overall_score`` is
    None and ``overall_qualitative`` carries the summary instead.
    """

    evaluation_id: str
    execution_id: str
    workspace_id: str
    task_id: str

    # Evaluators that contributed
    evaluators: list[EvaluatorRef] = Field(default_factory=list)
    methods_run: list[str] = Field(default_factory=list)

    # Core output
    metrics: list[NormalizedMetric] = Field(default_factory=list)
    findings: list[EvaluationFinding] = Field(default_factory=list)
    limitations: list[EvaluationLimitation] = Field(default_factory=list)

    # Overall — numeric ONLY when justified
    overall_score: float | None = None
    overall_score_kind: ScoreKind | None = None
    overall_confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    overall_qualitative: str | None = None

    # Human review
    human_review_required: bool = False
    human_review_status: str = "not_requested"  # not_requested | pending | completed
    human_review_notes: str | None = None

    # C8 binding
    evaluation_suite_id: str | None = None
    suite: SuiteDescriptor | None = None

    # Provenance
    protocol_type: str = ""
    model_fingerprint_hash: str | None = None
    duration_ms: int = 0
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    def numeric_metrics(self) -> list[NormalizedMetric]:
        return [m for m in self.metrics if m.is_numeric]

    def qualitative_metrics(self) -> list[NormalizedMetric]:
        return [
            m for m in self.metrics
            if m.score_kind == ScoreKind.QUALITATIVE
            or (m.qualitative_value and m.value is None)
        ]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class EvaluationEngine:
    """
    Unified evaluation entry point for Direct and Amplified runs.
    """

    def __init__(
        self,
        *,
        benchmark_registry: BenchmarkRegistryAdapter | None = None,
        deterministic: DeterministicEvaluator | None = None,
        evidence: EvidenceEvaluator | None = None,
        normalizer: MetricNormalizer | None = None,
    ) -> None:
        self._registry = benchmark_registry or NullBenchmarkRegistryAdapter()
        self._deterministic = deterministic or DeterministicEvaluator()
        self._evidence = evidence or EvidenceEvaluator()
        self._normalizer = normalizer or MetricNormalizer()

    async def evaluate(
        self, request: EvaluationRequest,
    ) -> EvaluationServiceResult:
        start = time.perf_counter_ns()
        inp = request.input
        evaluation_id = inp.evaluation_id or str(uuid4())

        # Resolve optional C8 suite
        suite: SuiteDescriptor | None = None
        if request.include_c8_suite and inp.evaluation_suite_id:
            try:
                suite = await self._registry.get_suite(inp.evaluation_suite_id)
            except Exception as exc:
                logger.warning(
                    "Failed to resolve C8 suite '%s': %s",
                    inp.evaluation_suite_id, exc,
                )

        # Run requested methods
        method_results: list[EvaluationMethodResult] = []
        methods_run: list[str] = []
        evaluators: list[EvaluatorRef] = []

        requested = {m.upper() for m in request.methods}

        if "DETERMINISTIC" in requested:
            result = await self._deterministic.evaluate(inp)
            method_results.append(result)
            methods_run.append("DETERMINISTIC")
            evaluators.append(result.evaluator)

        if "EVIDENCE" in requested:
            result = await self._evidence.evaluate(inp)
            method_results.append(result)
            methods_run.append("EVIDENCE")
            evaluators.append(result.evaluator)

        if "RUBRIC" in requested:
            rubric_eval = RubricEvaluator(rubric=request.rubric)
            result = await rubric_eval.evaluate(inp)
            method_results.append(result)
            methods_run.append("RUBRIC")
            evaluators.append(result.evaluator)

        # Normalize
        metrics, findings, limitations = self._normalizer.normalize(method_results)

        # Overall score — only if justified
        overall_score, overall_kind, overall_conf, overall_qual = (
            self._compute_overall(metrics, findings, limitations, inp)
        )

        # Human review
        human_status = "not_requested"
        if request.human_review_required:
            human_status = "pending"

        if (
            overall_score is None
            and overall_conf in (ConfidenceLevel.LOW, ConfidenceLevel.UNKNOWN)
            and request.human_review_required is False
        ):
            limitations.append(
                EvaluationLimitation(
                    reason=(
                        "Overall assessment is non-numeric with low/unknown "
                        "confidence."
                    ),
                    impact=(
                        "Consider human review before using this evaluation "
                        "for high-stakes decisions."
                    ),
                )
            )

        elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)

        return EvaluationServiceResult(
            evaluation_id=evaluation_id,
            execution_id=inp.execution_id,
            workspace_id=inp.workspace_id,
            task_id=inp.task_id,
            evaluators=evaluators,
            methods_run=methods_run,
            metrics=metrics,
            findings=findings,
            limitations=limitations,
            overall_score=overall_score,
            overall_score_kind=overall_kind,
            overall_confidence=overall_conf,
            overall_qualitative=overall_qual,
            human_review_required=request.human_review_required,
            human_review_status=human_status,
            evaluation_suite_id=inp.evaluation_suite_id,
            suite=suite,
            protocol_type=inp.protocol_type,
            model_fingerprint_hash=inp.model_fingerprint_hash,
            duration_ms=elapsed_ms,
            metadata=dict(request.metadata),
        )

    # -- overall score policy ----------------------------------------------

    def _compute_overall(
        self,
        metrics: list[NormalizedMetric],
        findings: list[EvaluationFinding],
        limitations: list[EvaluationLimitation],
        inp: EvaluationInput,
    ) -> tuple[float | None, ScoreKind | None, ConfidenceLevel, str | None]:
        """
        Produce an overall score ONLY when a reliable basis exists.

        Basis of reliability:
        - At least one high-confidence NUMERIC_BOUNDED or BOOLEAN metric from
          DETERMINISTIC method covering task success or correctness, AND
        - No critical findings that invalidate the run.

        Otherwise return (None, None, confidence, qualitative_summary).
        """
        critical = [
            f for f in findings if f.severity in ("critical", "error")
        ]

        candidates = [
            m for m in metrics
            if m.score_kind in (ScoreKind.NUMERIC_BOUNDED, ScoreKind.BOOLEAN)
            and m.value is not None
            and m.confidence == ConfidenceLevel.HIGH
            and m.method == "DETERMINISTIC"
            and m.category.value in (
                "TASK_SUCCESS",
                "CORRECTNESS",
                "COMPLETENESS",
                "RELIABILITY",
            )
        ]

        qualitative = self._build_qualitative_summary(metrics, findings, limitations)

        if not candidates:
            return None, None, ConfidenceLevel.LOW, qualitative

        if critical:
            rel = next(
                (m for m in candidates if m.metric_id == "reliability.execution_succeeded"),
                None,
            )
            if rel is not None and rel.value == 0.0:
                return 0.0, ScoreKind.NUMERIC_BOUNDED, ConfidenceLevel.HIGH, qualitative
            return None, None, ConfidenceLevel.LOW, qualitative

        # Weighted mean of candidate bounded/boolean metrics
        values = [m.value for m in candidates if m.value is not None]
        if not values:
            return None, None, ConfidenceLevel.LOW, qualitative

        overall = sum(values) / len(values)
        return overall, ScoreKind.NUMERIC_BOUNDED, ConfidenceLevel.HIGH, qualitative

    @staticmethod
    def _build_qualitative_summary(
        metrics: list[NormalizedMetric],
        findings: list[EvaluationFinding],
        limitations: list[EvaluationLimitation],
    ) -> str:
        parts: list[str] = []
        bool_pass = [
            m for m in metrics
            if m.score_kind == ScoreKind.BOOLEAN and m.boolean_value is True
        ]
        bool_fail = [
            m for m in metrics
            if m.score_kind == ScoreKind.BOOLEAN and m.boolean_value is False
        ]
        if bool_pass:
            parts.append(f"{len(bool_pass)} checks passed")
        if bool_fail:
            parts.append(f"{len(bool_fail)} checks failed")
        errors = [f for f in findings if f.severity in ("error", "critical")]
        if errors:
            parts.append(f"{len(errors)} error-level finding(s)")
        if limitations:
            parts.append(f"{len(limitations)} limitation(s) recorded")
        qual = [
            m.qualitative_value for m in metrics
            if m.score_kind == ScoreKind.QUALITATIVE and m.qualitative_value
        ]
        if qual:
            parts.append(qual[0])
        if not parts:
            return "Evaluation completed with no aggregate numeric score."
        return "; ".join(parts) + "."