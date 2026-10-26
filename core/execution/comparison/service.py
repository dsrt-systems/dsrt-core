# Path: core/execution/comparison/service.py
"""
ComparisonService — facade used by experiment finalization and APIs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.execution.comparison.contracts import (
    ComparisonRequest,
    ComparisonResult,
    ConfigurationRunEvidence,
)
from core.execution.comparison.engine import ComparisonEngine
from core.execution.comparison.reports import ComparisonReportBuilder


class ComparisonService:
    """Application service for producing and formatting comparisons."""

    def __init__(
        self,
        engine: Optional[ComparisonEngine] = None,
        reports: Optional[ComparisonReportBuilder] = None,
    ):
        self.engine = engine or ComparisonEngine()
        self.reports = reports or ComparisonReportBuilder()
        self._history: Dict[str, ComparisonResult] = {}

    def compare(self, request: ComparisonRequest) -> ComparisonResult:
        result = self.engine.compare(request)
        self._history[result.comparison_id] = result
        return result

    def compare_runs(
        self,
        *,
        experiment_id: str,
        workspace_id: str,
        runs: List[ConfigurationRunEvidence],
        baseline_configuration_id: Optional[str] = None,
        protocol_valid: bool = True,
        protocol_invalid_reasons: Optional[List[str]] = None,
        evaluator_version: str = "c10.10.0",
        quality_comparable_threshold: float = 0.05,
        quality_success_threshold: float = 0.7,
    ) -> ComparisonResult:
        req = ComparisonRequest(
            experiment_id=experiment_id,
            workspace_id=workspace_id,
            runs=runs,
            baseline_configuration_id=baseline_configuration_id,
            protocol_valid=protocol_valid,
            protocol_invalid_reasons=protocol_invalid_reasons or [],
            evaluator_version=evaluator_version,
            quality_comparable_threshold=quality_comparable_threshold,
            quality_success_threshold=quality_success_threshold,
        )
        return self.compare(req)

    def get(self, comparison_id: str) -> Optional[ComparisonResult]:
        return self._history.get(comparison_id)

    def report_dict(self, result: ComparisonResult) -> Dict[str, Any]:
        return self.reports.build(result)

    def report_markdown(self, result: ComparisonResult) -> str:
        return self.reports.build_markdown(result)