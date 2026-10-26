"""
Arena ↔ C6 Verification Integration (C8 §66).

Feeds C6 verification results into Arena evaluation as
deterministic metrics. This is the bridge between "was the
work verified?" (C6) and "how well did the agent perform?" (C8).

Architecture:
    C6 VerificationEngine completes verification
        ↓
    ArenaVerificationHook.ingest_verification()
        ↓
    Verification results → MetricResults
        ↓
    MetricComputer aggregates
        ↓
    PerformanceProfile updated
"""

from __future__ import annotations

from typing import Any

from schemas.domain.arena import MetricResult
from schemas.domain.enums import EvaluatorType, MetricType, VerificationStatus

from core.observability.logging import get_logger


logger = get_logger("dsrt.arena.integration.verification")


class ArenaVerificationHook:
    """Converts C6 verification results into C8 Arena metrics.

    Usage:
        hook = ArenaVerificationHook()
        metrics = hook.ingest_verification(
            arena_run_id="arn_1",
            verification_run_id="vrn_1",
            verification_status="PASSED",
            checks=[
                {"check_type": "SCHEMA_VALID", "status": "PASSED"},
                {"check_type": "COMPLETENESS", "status": "FAILED"},
            ],
        )
    """

    def ingest_verification(
        self,
        *,
        arena_run_id: str,
        verification_run_id: str,
        verification_status: str,
        checks: list[dict[str, Any]],
        dimensions: dict[str, float] | None = None,
    ) -> list[MetricResult]:
        """Convert C6 verification results to C8 metrics.

        Maps verification check results to Arena metric types:
          - C6 SCHEMA_VALID → C8 correctness
          - C6 COMPLETENESS → C8 completeness
          - C6 CLAIM_SUPPORTED → C8 evidence_quality
          - C6 CONSTRAINT_SATISFIED → C8 constraint_adherence
          - C6 ARTIFACT_INTEGRITY → C8 correctness
          - C6 STATE_CONSISTENT → C8 reliability

        Args:
            arena_run_id: The Arena run being evaluated.
            verification_run_id: The C6 verification run ID.
            verification_status: Overall verification status.
            checks: List of individual check results from C6.
            dimensions: Optional pre-computed dimensions from C6.

        Returns:
            List of MetricResult for the Arena MetricComputer.
        """
        metrics: list[MetricResult] = []

        # 1. Overall verification status → task_success metric
        task_success = verification_status in (
            VerificationStatus.PASSED.value,
            VerificationStatus.PASSED_WITH_WARNINGS.value,
        )
        metrics.append(MetricResult(
            metric_id="task_success",
            metric_type=MetricType.TASK_SUCCESS,
            value_boolean=task_success,
            value_numeric=1.0 if task_success else 0.0,
            evaluator_type=EvaluatorType.DETERMINISTIC,
            evidence_refs=[verification_run_id],
            explanation=f"C6 verification: {verification_status}",
        ))

        # 2. Map individual checks to Arena metrics
        check_to_metric = {
            "SCHEMA_VALID": MetricType.CORRECTNESS,
            "ARTIFACT_INTEGRITY": MetricType.CORRECTNESS,
            "COMPLETENESS": MetricType.COMPLETENESS,
            "CLAIM_SUPPORTED": MetricType.EVIDENCE_QUALITY,
            "CITATION_VALID": MetricType.EVIDENCE_QUALITY,
            "CONSTRAINT_SATISFIED": MetricType.CONSTRAINT_ADHERENCE,
            "STATE_CONSISTENT": MetricType.RELIABILITY,
            "TOOL_RESULT_VALID": MetricType.TOOL_EFFICIENCY,
        }

        for check in checks:
            check_type = check.get("check_type", "")
            check_status = check.get("status", "")
            metric_type = check_to_metric.get(check_type)

            if not metric_type:
                continue

            passed = check_status in (
                VerificationStatus.PASSED.value,
                VerificationStatus.PASSED_WITH_WARNINGS.value,
            )

            metrics.append(MetricResult(
                metric_id=f"verification_{check_type.lower()}",
                metric_type=metric_type,
                value_boolean=passed,
                value_numeric=1.0 if passed else 0.0,
                evaluator_type=EvaluatorType.DETERMINISTIC,
                evidence_refs=[verification_run_id],
                explanation=f"C6 check {check_type}: {check_status}",
            ))

        # 3. Include C6 dimensions if available
        if dimensions:
            for dim_name, dim_value in dimensions.items():
                metric_type = self._dim_to_metric_type(dim_name)
                if metric_type:
                    metrics.append(MetricResult(
                        metric_id=f"c6_{dim_name}",
                        metric_type=metric_type,
                        value_numeric=dim_value,
                        evaluator_type=EvaluatorType.DETERMINISTIC,
                        evidence_refs=[verification_run_id],
                        explanation=f"C6 verification dimension: {dim_name}",
                    ))

        logger.info(
            "verification_ingested",
            arena_run_id=arena_run_id,
            verification_run_id=verification_run_id,
            metrics_generated=len(metrics),
            task_success=task_success,
        )

        return metrics

    @staticmethod
    def _dim_to_metric_type(dim: str) -> MetricType | None:
        """Map C6 dimension names to C8 MetricType."""
        mapping = {
            "correctness": MetricType.CORRECTNESS,
            "completeness": MetricType.COMPLETENESS,
            "evidence_quality": MetricType.EVIDENCE_QUALITY,
            "integrity": MetricType.CORRECTNESS,
            "constraint_compliance": MetricType.CONSTRAINT_ADHERENCE,
            "consistency": MetricType.RELIABILITY,
        }
        return mapping.get(dim)