"""
C10.7 — Evaluation Engine.

Unified evaluation interface for Direct and Amplified execution outputs.
Consumes C8 evaluator infrastructure; does not replace it.
"""

from core.execution.evaluation.contracts import (
    EvaluationCategory,
    EvaluationInput,
    EvaluationFinding,
    EvaluationLimitation,
    MetricDefinition,
    NormalizedMetric,
    EvaluatorRef,
)
from core.execution.evaluation.methods import (
    DeterministicEvaluator,
    EvidenceEvaluator,
    RubricEvaluator,
    EvaluationMethodResult,
)
from core.execution.evaluation.normalizer import MetricNormalizer
from core.execution.evaluation.service import (
    EvaluationEngine,
    EvaluationRequest,
    EvaluationServiceResult,
)
from core.execution.evaluation.adapters import (
    BenchmarkRegistryAdapter,
    NullBenchmarkRegistryAdapter,
)

__all__ = [
    # contracts
    "EvaluationCategory",
    "EvaluationInput",
    "EvaluationFinding",
    "EvaluationLimitation",
    "MetricDefinition",
    "NormalizedMetric",
    "EvaluatorRef",
    # methods
    "DeterministicEvaluator",
    "EvidenceEvaluator",
    "RubricEvaluator",
    "EvaluationMethodResult",
    # normalizer
    "MetricNormalizer",
    # service
    "EvaluationEngine",
    "EvaluationRequest",
    "EvaluationServiceResult",
    # adapters
    "BenchmarkRegistryAdapter",
    "NullBenchmarkRegistryAdapter",
]