"""
Metric Computer (C8 §24-30, §37).

Aggregates metric results from multiple evaluators into a unified
set of evidence-linked metrics.

Key principles:
  - Evidence-first: every metric points to evidence (C8 §30)
  - No fabrication: provider-reported usage is distinguished from estimates (C8 §32)
  - Confidence includes sample size (C8 §37)
  - Deterministic metrics preferred (C8 §25)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schemas.domain.arena import MetricResult
from schemas.domain.enums import EvaluatorType, MetricType

from core.observability.logging import get_logger


logger = get_logger("dsrt.arena.metrics")


@dataclass
class MetricAggregation:
    """Aggregated metric across multiple evaluators."""
    metric_id: str
    metric_type: MetricType
    values: list[float] = field(default_factory=list)
    evaluator_types: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    sample_count: int = 0
    explanations: list[str] = field(default_factory=list)

    @property
    def mean_value(self) -> float | None:
        if not self.values:
            return None
        return sum(self.values) / len(self.values)

    @property
    def min_value(self) -> float | None:
        return min(self.values) if self.values else None

    @property
    def max_value(self) -> float | None:
        return max(self.values) if self.values else None

    @property
    def consensus(self) -> str:
        """Deterministic consensus across evaluators."""
        if not self.values:
            return "NO_DATA"
        if all(v >= 0.8 for v in self.values):
            return "STRONG_PASS"
        if all(v >= 0.5 for v in self.values):
            return "PASS"
        if any(v < 0.3 for v in self.values):
            return "FAIL"
        return "MIXED"


class MetricComputer:
    """Computes and aggregates metrics from evaluator outputs (C8 §24-30).

    Usage:
        computer = MetricComputer()
        computer.add_evaluator_results("deterministic_v1", metrics_from_det)
        computer.add_evaluator_results("trajectory_v1", metrics_from_traj)
        aggregated = computer.compute()
        # aggregated = {metric_id: MetricAggregation}
    """

    def __init__(self) -> None:
        self._evaluator_results: dict[str, list[MetricResult]] = {}

    def add_evaluator_results(
        self,
        evaluator_id: str,
        metrics: list[MetricResult],
    ) -> None:
        """Add metric results from an evaluator.

        Args:
            evaluator_id: Unique evaluator identifier.
            metrics: List of MetricResult from the evaluator.
        """
        if evaluator_id not in self._evaluator_results:
            self._evaluator_results[evaluator_id] = []
        self._evaluator_results[evaluator_id].extend(metrics)

        logger.debug(
            "evaluator_metrics_added",
            evaluator=evaluator_id,
            metric_count=len(metrics),
        )

    def compute(self) -> dict[str, MetricAggregation]:
        """Aggregate all evaluator metrics into unified results (C8 §29-30).

        Returns:
            Dict mapping metric_id → MetricAggregation.
        """
        aggregations: dict[str, MetricAggregation] = {}

        for evaluator_id, metrics in self._evaluator_results.items():
            for m in metrics:
                mid = m.metric_id

                if mid not in aggregations:
                    aggregations[mid] = MetricAggregation(
                        metric_id=mid,
                        metric_type=m.metric_type,
                    )

                agg = aggregations[mid]

                # Collect numeric values
                if m.value_numeric is not None:
                    agg.values.append(m.value_numeric)

                # Track evaluator types
                eval_type = (
                    m.evaluator_type.value
                    if hasattr(m.evaluator_type, "value")
                    else str(m.evaluator_type)
                )
                if eval_type not in agg.evaluator_types:
                    agg.evaluator_types.append(eval_type)

                # Collect evidence
                for ref in m.evidence_refs:
                    if ref not in agg.evidence_refs:
                        agg.evidence_refs.append(ref)

                # Collect explanations
                if m.explanation:
                    agg.explanations.append(
                        f"[{evaluator_id}] {m.explanation}"
                    )

                agg.sample_count += m.sample_count

        logger.info(
            "metrics_computed",
            total_metrics=len(aggregations),
            evaluators=len(self._evaluator_results),
        )

        return aggregations

    def to_metric_results(
        self,
        aggregations: dict[str, MetricAggregation] | None = None,
    ) -> list[MetricResult]:
        """Convert aggregations back to MetricResult list for storage.

        Each aggregation produces a single MetricResult with the
        mean value and combined evidence.
        """
        if aggregations is None:
            aggregations = self.compute()

        results: list[MetricResult] = []
        for mid, agg in aggregations.items():
            # Determine the dominant evaluator type
            dominant_type = EvaluatorType.DETERMINISTIC
            if agg.evaluator_types:
                try:
                    dominant_type = EvaluatorType(agg.evaluator_types[0])
                except ValueError:
                    pass

            # Compute confidence from sample count and agreement
            confidence = self._compute_confidence(agg)

            results.append(MetricResult(
                metric_id=mid,
                metric_type=agg.metric_type,
                metric_version="1.0",
                value_numeric=agg.mean_value,
                value_boolean=(agg.mean_value >= 0.5) if agg.mean_value is not None else None,
                evaluator_type=dominant_type,
                sample_count=agg.sample_count,
                confidence=confidence,
                evidence_refs=agg.evidence_refs,
                explanation=" | ".join(agg.explanations[:3]),
            ))

        return results

    @staticmethod
    def _compute_confidence(agg: MetricAggregation) -> float | None:
        """Compute confidence from sample size and value agreement (C8 §37).

        Higher sample count and tighter value spread → higher confidence.
        """
        if not agg.values:
            return None

        n = len(agg.values)
        if n == 1:
            return 0.5  # Low confidence from single sample

        # Compute variance
        mean = sum(agg.values) / n
        variance = sum((v - mean) ** 2 for v in agg.values) / n

        # Confidence = sample factor × agreement factor
        sample_factor = min(1.0, n / 5.0)  # Full confidence at 5+ samples
        agreement_factor = max(0.0, 1.0 - variance)  # Low variance = high agreement

        return round(min(1.0, sample_factor * agreement_factor), 3)

    def clear(self) -> None:
        """Reset all accumulated results."""
        self._evaluator_results.clear()