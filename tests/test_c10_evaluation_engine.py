"""
C10.7 — Evaluation Engine tests.

Covers:
1. Deterministic method — match, schema, constraints, tools, failures
2. Evidence method — artifacts, sources, qualitative-only overall
3. Rubric method — ordinal labels, no silent numeric mapping
4. MetricNormalizer — confidence preference, qualitative guard
5. EvaluationEngine — composition, overall-score policy, C8 suite hook
6. Critical rule — never manufacture scores for qualitative work
"""

from __future__ import annotations

import pytest

from core.execution.evaluation.contracts import (
    ConfidenceLevel,
    EvaluationCategory,
    EvaluationInput,
    NormalizedMetric,
    ScoreKind,
)
from core.execution.evaluation.methods import (
    DeterministicEvaluator,
    EvidenceEvaluator,
    EvaluationMethodResult,
    RubricDefinition,
    RubricCriterion,
    RubricEvaluator,
)
from core.execution.evaluation.normalizer import MetricNormalizer
from core.execution.evaluation.service import (
    EvaluationEngine,
    EvaluationRequest,
)
from core.execution.evaluation.adapters import (
    NullBenchmarkRegistryAdapter,
    SuiteDescriptor,
    EvaluatorDescriptor,
)


# =====================================================================
# Helpers
# =====================================================================

def _basic_input(**overrides) -> EvaluationInput:
    data = dict(
        execution_id="exec-1",
        workspace_id="ws-1",
        task_id="task-1",
        output_text="Quantum computing uses qubits to process information.",
        task_prompt="Explain quantum computing.",
        execution_status="COMPLETED",
        protocol_type="DIRECT",
    )
    data.update(overrides)
    return EvaluationInput(**data)


# =====================================================================
# 1. Deterministic evaluator
# =====================================================================

class TestDeterministicEvaluator:
    @pytest.mark.asyncio
    async def test_successful_execution_basics(self):
        ev = DeterministicEvaluator()
        result = await ev.evaluate(_basic_input())
        assert result.method == "DETERMINISTIC"
        ids = {m.metric_id: m for m in result.metrics}
        assert ids["reliability.execution_succeeded"].boolean_value is True
        assert ids["task_success.completed"].boolean_value is True
        assert ids["reliability.error_count"].value == 0.0

    @pytest.mark.asyncio
    async def test_failed_execution(self):
        ev = DeterministicEvaluator()
        result = await ev.evaluate(
            _basic_input(execution_status="FAILED", output_text=None, errors=[{"type": "Timeout"}])
        )
        ids = {m.metric_id: m for m in result.metrics}
        assert ids["reliability.execution_succeeded"].boolean_value is False
        assert ids["task_success.completed"].boolean_value is False
        assert ids["reliability.error_count"].value == 1.0
        assert any(f.severity == "error" for f in result.findings)

    @pytest.mark.asyncio
    async def test_exact_and_normalized_match(self):
        ev = DeterministicEvaluator()
        result = await ev.evaluate(
            _basic_input(
                output_text="Hello World",
                expected_output="hello world",
            )
        )
        ids = {m.metric_id: m for m in result.metrics}
        assert ids["correctness.exact_match"].boolean_value is False
        assert ids["correctness.normalized_match"].boolean_value is True

    @pytest.mark.asyncio
    async def test_schema_validation_pass(self):
        ev = DeterministicEvaluator()
        result = await ev.evaluate(
            _basic_input(
                output_structured={"answer": "42", "confidence": 0.9},
                expected_schema={
                    "required": ["answer", "confidence"],
                    "properties": {
                        "answer": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                },
            )
        )
        ids = {m.metric_id: m for m in result.metrics}
        assert ids["correctness.schema_valid"].boolean_value is True

    @pytest.mark.asyncio
    async def test_schema_validation_fail_missing_field(self):
        ev = DeterministicEvaluator()
        result = await ev.evaluate(
            _basic_input(
                output_structured={"answer": "42"},
                expected_schema={"required": ["answer", "confidence"], "properties": {}},
            )
        )
        ids = {m.metric_id: m for m in result.metrics}
        assert ids["correctness.schema_valid"].boolean_value is False

    @pytest.mark.asyncio
    async def test_constraint_satisfaction(self):
        ev = DeterministicEvaluator()
        result = await ev.evaluate(
            _basic_input(
                output_text="This answer uses qubits and avoids jargon.",
                constraints=["qubits", "must include diagram"],
            )
        )
        ids = {m.metric_id: m for m in result.metrics}
        # 1 of 2 constraints present
        assert ids["constraints.satisfaction_ratio"].value == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_success_criteria_regex(self):
        ev = DeterministicEvaluator()
        result = await ev.evaluate(
            _basic_input(
                output_text="The final answer is 42.",
                success_criteria=[r"/final answer is \d+/", "missing thing"],
            )
        )
        ids = {m.metric_id: m for m in result.metrics}
        assert ids["completeness.criteria_coverage"].value == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_tool_results(self):
        ev = DeterministicEvaluator()
        result = await ev.evaluate(
            _basic_input(
                tool_results=[
                    {"tool": "shell", "success": True},
                    {"tool": "browser", "status": "success"},
                    {"tool": "file", "success": False},
                ]
            )
        )
        ids = {m.metric_id: m for m in result.metrics}
        assert ids["tool_execution.success_ratio"].value == pytest.approx(2 / 3)

    @pytest.mark.asyncio
    async def test_missing_expected_output_records_limitation(self):
        ev = DeterministicEvaluator()
        result = await ev.evaluate(_basic_input())
        assert any(
            lim.category == EvaluationCategory.CORRECTNESS
            for lim in result.limitations
        )


# =====================================================================
# 2. Evidence evaluator
# =====================================================================

class TestEvidenceEvaluator:
    @pytest.mark.asyncio
    async def test_source_markers_detected(self):
        ev = EvidenceEvaluator()
        result = await ev.evaluate(
            _basic_input(
                output_text="See https://example.com/a and reference [1] for details."
            )
        )
        ids = {m.metric_id: m for m in result.metrics}
        assert ids["evidence.source_marker_count"].value == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_qualitative_overall_has_no_numeric_value(self):
        ev = EvidenceEvaluator()
        result = await ev.evaluate(
            _basic_input(artifact_refs=["art-1"], tool_results=[{"success": True}])
        )
        overall = next(
            m for m in result.metrics
            if m.metric_id == "evidence.overall_assessment"
        )
        assert overall.score_kind == ScoreKind.QUALITATIVE
        assert overall.value is None
        assert overall.qualitative_value is not None

    @pytest.mark.asyncio
    async def test_no_tools_records_limitation(self):
        ev = EvidenceEvaluator()
        result = await ev.evaluate(_basic_input(tool_results=[]))
        assert any(
            lim.category == EvaluationCategory.EVIDENCE_QUALITY
            for lim in result.limitations
        )

    @pytest.mark.asyncio
    async def test_verification_linkage(self):
        ev = EvidenceEvaluator()
        result = await ev.evaluate(
            _basic_input(
                verification_results=[
                    {"passed": True, "evidence_ref": "ev-1"},
                    {"passed": True},
                ]
            )
        )
        ids = {m.metric_id: m for m in result.metrics}
        assert ids["evidence.verification_linkage_ratio"].value == pytest.approx(0.5)


# =====================================================================
# 3. Rubric evaluator
# =====================================================================

class TestRubricEvaluator:
    @pytest.mark.asyncio
    async def test_default_rubric_produces_ordinals_not_numbers(self):
        ev = RubricEvaluator()
        result = await ev.evaluate(_basic_input())
        ordinals = [
            m for m in result.metrics
            if m.metric_id.startswith("rubric.")
        ]
        assert len(ordinals) >= 4
        for m in ordinals:
            assert m.ordinal_value is not None
            # Default rubric must NOT silently invent numbers
            assert m.value is None
            assert m.score_kind in (ScoreKind.ORDINAL, ScoreKind.QUALITATIVE)

    @pytest.mark.asyncio
    async def test_numeric_mapping_only_when_enabled(self):
        rubric = RubricDefinition(
            name="mapped",
            allow_numeric_mapping=True,
            ordinal_scores={"poor": 0.0, "fair": 0.33, "good": 0.66, "excellent": 1.0},
            criteria=[
                RubricCriterion(
                    criterion_id="rubric.task_success",
                    category=EvaluationCategory.TASK_SUCCESS,
                    name="Task Success",
                ),
            ],
        )
        ev = RubricEvaluator(rubric=rubric)
        result = await ev.evaluate(_basic_input())
        m = result.metrics[0]
        assert m.value is not None
        assert m.score_kind == ScoreKind.NUMERIC_BOUNDED
        assert "allow_numeric_mapping=True" in m.notes

    @pytest.mark.asyncio
    async def test_empty_output_records_limitation(self):
        ev = RubricEvaluator()
        result = await ev.evaluate(
            _basic_input(output_text=None, output_structured=None)
        )
        assert result.metrics == []
        assert len(result.limitations) >= 1

    @pytest.mark.asyncio
    async def test_safety_metric_is_qualitative_not_scored(self):
        ev = RubricEvaluator()
        result = await ev.evaluate(_basic_input())
        safety = next(
            m for m in result.metrics
            if m.metric_id == "safety.policy_review_status"
        )
        assert safety.score_kind == ScoreKind.QUALITATIVE
        assert safety.value is None
        assert safety.qualitative_value == "not_reviewed"


# =====================================================================
# 4. MetricNormalizer
# =====================================================================

class TestMetricNormalizer:
    def test_prefers_higher_confidence(self):
        low = NormalizedMetric(
            metric_id="x",
            name="X",
            category=EvaluationCategory.CORRECTNESS,
            score_kind=ScoreKind.NUMERIC_BOUNDED,
            value=0.5,
            confidence=ConfidenceLevel.LOW,
            method="RUBRIC",
        )
        high = NormalizedMetric(
            metric_id="x",
            name="X",
            category=EvaluationCategory.CORRECTNESS,
            score_kind=ScoreKind.NUMERIC_BOUNDED,
            value=0.9,
            confidence=ConfidenceLevel.HIGH,
            method="DETERMINISTIC",
        )
        r1 = EvaluationMethodResult(
            method="RUBRIC",
            evaluator=RubricEvaluator.EVALUATOR,
            metrics=[low],
        )
        r2 = EvaluationMethodResult(
            method="DETERMINISTIC",
            evaluator=DeterministicEvaluator.EVALUATOR,
            metrics=[high],
        )
        metrics, _, _ = MetricNormalizer().normalize([r1, r2])
        assert len(metrics) == 1
        assert metrics[0].value == 0.9
        assert metrics[0].confidence == ConfidenceLevel.HIGH

    def test_strips_numeric_value_from_qualitative(self):
        bad = NormalizedMetric(
            metric_id="q",
            name="Q",
            category=EvaluationCategory.EVIDENCE_QUALITY,
            score_kind=ScoreKind.QUALITATIVE,
            value=0.75,  # illegal — should be stripped
            qualitative_value="mixed evidence",
            confidence=ConfidenceLevel.MEDIUM,
            method="EVIDENCE",
        )
        r = EvaluationMethodResult(
            method="EVIDENCE",
            evaluator=EvidenceEvaluator.EVALUATOR,
            metrics=[bad],
        )
        metrics, _, _ = MetricNormalizer().normalize([r])
        assert metrics[0].value is None
        assert metrics[0].qualitative_value == "mixed evidence"

    def test_merges_findings_and_limitations(self):
        from core.execution.evaluation.contracts import (
            EvaluationFinding,
            EvaluationLimitation,
        )
        r1 = EvaluationMethodResult(
            method="DETERMINISTIC",
            evaluator=DeterministicEvaluator.EVALUATOR,
            findings=[
                EvaluationFinding(
                    category=EvaluationCategory.RELIABILITY,
                    summary="ok",
                )
            ],
            limitations=[
                EvaluationLimitation(reason="no expected output")
            ],
        )
        r2 = EvaluationMethodResult(
            method="EVIDENCE",
            evaluator=EvidenceEvaluator.EVALUATOR,
            findings=[
                EvaluationFinding(
                    category=EvaluationCategory.EVIDENCE_QUALITY,
                    summary="sources found",
                )
            ],
        )
        _, findings, limitations = MetricNormalizer().normalize([r1, r2])
        assert len(findings) == 2
        assert len(limitations) == 1


# =====================================================================
# 5. EvaluationEngine
# =====================================================================

class TestEvaluationEngine:
    @pytest.mark.asyncio
    async def test_full_evaluation_all_methods(self):
        engine = EvaluationEngine()
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(
                    expected_output="Quantum computing uses qubits to process information.",
                    constraints=["qubits"],
                    success_criteria=["qubits"],
                    artifact_refs=["art-1"],
                    tool_results=[{"success": True}],
                )
            )
        )
        assert set(result.methods_run) == {"DETERMINISTIC", "EVIDENCE", "RUBRIC"}
        assert len(result.evaluators) == 3
        assert len(result.metrics) > 0
        assert result.execution_id == "exec-1"
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_overall_score_when_deterministic_basis_exists(self):
        engine = EvaluationEngine()
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(
                    expected_output="Quantum computing uses qubits to process information.",
                ),
                methods=["DETERMINISTIC"],
            )
        )
        # High-confidence deterministic bounded metrics exist → overall allowed
        assert result.overall_score is not None
        assert 0.0 <= result.overall_score <= 1.0
        assert result.overall_score_kind == ScoreKind.NUMERIC_BOUNDED

    @pytest.mark.asyncio
    async def test_no_overall_score_for_rubric_only(self):
        """Critical rule: rubric-only must not manufacture an overall float."""
        engine = EvaluationEngine()
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(),
                methods=["RUBRIC"],
            )
        )
        assert result.overall_score is None
        assert result.overall_qualitative is not None
        assert result.overall_confidence in (
            ConfidenceLevel.LOW,
            ConfidenceLevel.UNKNOWN,
        )

    @pytest.mark.asyncio
    async def test_failed_run_overall_zero(self):
        engine = EvaluationEngine()
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(
                    execution_status="FAILED",
                    output_text=None,
                    errors=[{"type": "ProviderError"}],
                ),
                methods=["DETERMINISTIC"],
            )
        )
        assert result.overall_score == 0.0

    @pytest.mark.asyncio
    async def test_method_subset(self):
        engine = EvaluationEngine()
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(),
                methods=["EVIDENCE"],
            )
        )
        assert result.methods_run == ["EVIDENCE"]
        assert all(m.method == "EVIDENCE" for m in result.metrics if m.method)

    @pytest.mark.asyncio
    async def test_human_review_flag(self):
        engine = EvaluationEngine()
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(),
                methods=["RUBRIC"],
                human_review_required=True,
            )
        )
        assert result.human_review_required is True
        assert result.human_review_status == "pending"

    @pytest.mark.asyncio
    async def test_c8_suite_resolved_when_available(self):
        class FakeRegistry:
            async def get_suite(self, suite_id: str) -> SuiteDescriptor | None:
                return SuiteDescriptor(
                    suite_id=suite_id,
                    name="Test Suite",
                    evaluator_ids=["c8.eval.1"],
                    version="2.0.0",
                )

            async def get_evaluator(self, evaluator_id: str):
                return None

            async def list_evaluators_for_suite(self, suite_id: str):
                return []

        engine = EvaluationEngine(benchmark_registry=FakeRegistry())
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(evaluation_suite_id="suite-1"),
                methods=["DETERMINISTIC"],
            )
        )
        assert result.suite is not None
        assert result.suite.suite_id == "suite-1"
        assert result.suite.version == "2.0.0"

    @pytest.mark.asyncio
    async def test_c8_suite_absent_does_not_fail(self):
        engine = EvaluationEngine(
            benchmark_registry=NullBenchmarkRegistryAdapter()
        )
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(evaluation_suite_id="missing-suite"),
                methods=["DETERMINISTIC"],
            )
        )
        assert result.suite is None
        assert "DETERMINISTIC" in result.methods_run

    @pytest.mark.asyncio
    async def test_numeric_and_qualitative_split_helpers(self):
        engine = EvaluationEngine()
        result = await engine.evaluate(
            EvaluationRequest(input=_basic_input())
        )
        # Both kinds should be present with default methods
        assert isinstance(result.numeric_metrics(), list)
        assert isinstance(result.qualitative_metrics(), list)
        # qualitative overall evidence assessment should appear
        qual_ids = {m.metric_id for m in result.qualitative_metrics()}
        assert "evidence.overall_assessment" in qual_ids


# =====================================================================
# 6. Critical rule enforcement
# =====================================================================

class TestCriticalScoreRule:
    @pytest.mark.asyncio
    async def test_engine_never_scores_pure_qualitative_task(self):
        """
        A creative/open-ended task with no expected output, no schema,
        no criteria, no tools — must not receive a fabricated overall float
        from rubric heuristics alone.
        """
        engine = EvaluationEngine()
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(
                    output_text="A meditative reflection on the color blue.",
                    expected_output=None,
                    expected_schema=None,
                    constraints=[],
                    success_criteria=[],
                    tool_results=[],
                    verification_results=[],
                ),
                methods=["RUBRIC", "EVIDENCE"],
            )
        )
        assert result.overall_score is None
        assert result.overall_qualitative is not None
        # Every qualitative metric must have value=None
        for m in result.metrics:
            if m.score_kind == ScoreKind.QUALITATIVE:
                assert m.value is None, (
                    f"Qualitative metric {m.metric_id} illegally carries value={m.value}"
                )

    @pytest.mark.asyncio
    async def test_limitations_always_present_when_data_missing(self):
        engine = EvaluationEngine()
        result = await engine.evaluate(
            EvaluationRequest(
                input=_basic_input(
                    constraints=[],
                    success_criteria=[],
                    tool_results=[],
                    expected_output=None,
                )
            )
        )
        assert len(result.limitations) >= 1