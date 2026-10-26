# Path: core/execution/comparison/__init__.py
"""
C10.10 — Comparison & Results Engine.

Converts per-run evaluation, cost, latency and reliability evidence into
fair multi-configuration comparison results. Never forces a universal winner.
"""

from core.execution.comparison.contracts import (
    ComparisonOutcomeKind,
    ConfigurationRunEvidence,
    DimensionComparison,
    ComparisonResult,
    ComparisonRequest,
)
from core.execution.comparison.metrics import ComparisonMetricsCalculator
from core.execution.comparison.engine import ComparisonEngine
from core.execution.comparison.reports import ComparisonReportBuilder
from core.execution.comparison.service import ComparisonService

__all__ = [
    "ComparisonOutcomeKind",
    "ConfigurationRunEvidence",
    "DimensionComparison",
    "ComparisonResult",
    "ComparisonRequest",
    "ComparisonMetricsCalculator",
    "ComparisonEngine",
    "ComparisonReportBuilder",
    "ComparisonService",
]