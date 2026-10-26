"""
C8 Benchmark Registry adapters.

C10 must not recreate the benchmark registry. These adapters define the
contract C10 uses to ask C8 for evaluators and suite definitions.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class EvaluatorDescriptor(BaseModel):
    """Lightweight description of a C8-registered evaluator."""

    evaluator_id: str
    evaluator_version: str
    name: str = ""
    methods: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    supports_numeric_scoring: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SuiteDescriptor(BaseModel):
    """Description of an evaluation suite from C8."""

    suite_id: str
    name: str = ""
    evaluator_ids: list[str] = Field(default_factory=list)
    benchmark_id: str | None = None
    version: str = "1.0.0"
    metadata: dict[str, Any] = Field(default_factory=dict)


class BenchmarkRegistryAdapter(Protocol):
    """
    Contract for resolving evaluators and suites from C8.

    Production implementation wraps the real C8 registry.
    """

    async def get_suite(self, suite_id: str) -> SuiteDescriptor | None:
        ...

    async def get_evaluator(
        self, evaluator_id: str,
    ) -> EvaluatorDescriptor | None:
        ...

    async def list_evaluators_for_suite(
        self, suite_id: str,
    ) -> list[EvaluatorDescriptor]:
        ...


class NullBenchmarkRegistryAdapter:
    """
    Default adapter used when C8 is not yet wired.

    Returns empty results so the Evaluation Engine can still run its
    built-in local methods (deterministic / evidence / rubric) without
    a hard dependency on C8 being present.
    """

    async def get_suite(self, suite_id: str) -> SuiteDescriptor | None:
        return None

    async def get_evaluator(
        self, evaluator_id: str,
    ) -> EvaluatorDescriptor | None:
        return None

    async def list_evaluators_for_suite(
        self, suite_id: str,
    ) -> list[EvaluatorDescriptor]:
        return []