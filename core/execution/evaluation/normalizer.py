"""
MetricNormalizer — Merges multi-method metrics into a coherent set.

Rules:
- Never invent a numeric value for a QUALITATIVE metric.
- When the same metric_id appears from multiple methods, prefer higher
  confidence, then prefer DETERMINISTIC > EVIDENCE > RUBRIC.
- Preserve all findings and limitations from every method.
"""

from __future__ import annotations

from typing import Iterable

from core.execution.evaluation.contracts import (
    ConfidenceLevel,
    EvaluationFinding,
    EvaluationLimitation,
    NormalizedMetric,
    ScoreKind,
)
from core.execution.evaluation.methods import EvaluationMethodResult


_CONFIDENCE_RANK = {
    ConfidenceLevel.HIGH: 3,
    ConfidenceLevel.MEDIUM: 2,
    ConfidenceLevel.LOW: 1,
    ConfidenceLevel.UNKNOWN: 0,
}

_METHOD_RANK = {
    "DETERMINISTIC": 3,
    "EVIDENCE": 2,
    "RUBRIC": 1,
}


class MetricNormalizer:
    """Collapse a list of method results into unified collections."""

    def normalize(
        self,
        method_results: Iterable[EvaluationMethodResult],
    ) -> tuple[
        list[NormalizedMetric],
        list[EvaluationFinding],
        list[EvaluationLimitation],
    ]:
        results = list(method_results)
        metrics = self._merge_metrics(results)
        findings: list[EvaluationFinding] = []
        limitations: list[EvaluationLimitation] = []
        for r in results:
            findings.extend(r.findings)
            limitations.extend(r.limitations)
        return metrics, findings, limitations

    def _merge_metrics(
        self,
        results: list[EvaluationMethodResult],
    ) -> list[NormalizedMetric]:
        best: dict[str, NormalizedMetric] = {}
        for result in results:
            for metric in result.metrics:
                # Guard: qualitative metrics must not carry a fabricated value
                if metric.score_kind == ScoreKind.QUALITATIVE and metric.value is not None:
                    metric = metric.model_copy(update={"value": None})

                existing = best.get(metric.metric_id)
                if existing is None or self._is_better(metric, existing):
                    best[metric.metric_id] = metric
        return list(best.values())

    def _is_better(
        self,
        candidate: NormalizedMetric,
        incumbent: NormalizedMetric,
    ) -> bool:
        c_conf = _CONFIDENCE_RANK.get(candidate.confidence, 0)
        i_conf = _CONFIDENCE_RANK.get(incumbent.confidence, 0)
        if c_conf != i_conf:
            return c_conf > i_conf
        c_method = _METHOD_RANK.get(candidate.method, 0)
        i_method = _METHOD_RANK.get(incumbent.method, 0)
        return c_method > i_method