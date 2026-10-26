# Path: tests/test_c10_comparison_integration.py
"""
C10.10 — Comparison Engine & Unified Integration tests.
"""

from __future__ import annotations

import pytest

from core.execution.comparison.contracts import (
    ComparisonOutcomeKind,
    ComparisonRequest,
    ConfigurationRunEvidence,
)
from core.execution.comparison.engine import ComparisonEngine
from core.execution.comparison.service import ComparisonService
from core.execution.integration.contracts import ExecutionRequest
from core.execution.integration.unified_engine import UnifiedExecutionEngine


def _run(
    cid: str,
    label: str,
    *,
    protocol: str = "direct",
    score: float | None = 0.9,
    cost: float | None = 0.10,
    succeeded: bool = True,
    failed: bool = False,
    latency: int | None = 1000,
    availability: str = "ACTUAL",
    repairs: int = 0,
) -> ConfigurationRunEvidence:
    return ConfigurationRunEvidence(
        configuration_id=cid,
        configuration_label=label,
        protocol=protocol,
        overall_score=score,
        task_success=succeeded and not failed,
        succeeded=succeeded and not failed,
        failed=failed,
        total_cost_usd=cost,
        cost_availability=availability,
        latency_ms=latency,
        reliability_score=0.0 if failed else 1.0,
        repair_count=repairs,
        run_status="FAILED" if failed else "COMPLETED",
    )


def test_candidate_better_quality_lower_cost():
    engine = ComparisonEngine()
    result = engine.compare(
        ComparisonRequest(
            experiment_id="exp_1",
            workspace_id="ws_1",
            baseline_configuration_id="baseline",
            runs=[
                _run("baseline", "Direct", score=0.70, cost=0.20, protocol="direct"),
                _run("candidate", "Amplified", score=0.92, cost=0.08, protocol="amplified"),
            ],
        )
    )
    assert result.outcome_kind == ComparisonOutcomeKind.CANDIDATE_BETTER_QUALITY_LOWER_COST
    assert result.cost_savings_claimable is True
    assert result.cost_savings_vs_baseline is not None
    assert result.cost_savings_vs_baseline > 0
    assert result.highest_quality_configuration_id == "candidate"
    assert result.cost_efficient_configuration_id == "candidate"


def test_savings_not_claimable_when_quality_worse():
    engine = ComparisonEngine()
    result = engine.compare(
        ComparisonRequest(
            experiment_id="exp_2",
            workspace_id="ws_1",
            baseline_configuration_id="baseline",
            quality_comparable_threshold=0.05,
            runs=[
                _run("baseline", "Direct", score=0.95, cost=0.50),
                _run("candidate", "Amplified", score=0.40, cost=0.05),
            ],
        )
    )
    assert result.cost_savings_claimable is False
    assert result.outcome_kind in {
        ComparisonOutcomeKind.BASELINE_BETTER_QUALITY,
        ComparisonOutcomeKind.MIXED,
        ComparisonOutcomeKind.INCONCLUSIVE,
    }


def test_all_failed_outcome():
    engine = ComparisonEngine()
    result = engine.compare(
        ComparisonRequest(
            experiment_id="exp_3",
            workspace_id="ws_1",
            runs=[
                _run("a", "A", score=0.0, succeeded=False, failed=True, cost=0.1),
                _run("b", "B", score=0.0, succeeded=False, failed=True, cost=0.2),
            ],
        )
    )
    assert result.outcome_kind == ComparisonOutcomeKind.ALL_FAILED
    assert result.successful_configuration_ids == []


def test_invalid_protocol():
    engine = ComparisonEngine()
    result = engine.compare(
        ComparisonRequest(
            experiment_id="exp_4",
            workspace_id="ws_1",
            protocol_valid=False,
            protocol_invalid_reasons=["snapshot_mismatch"],
            runs=[
                _run("a", "A"),
                _run("b", "B"),
            ],
        )
    )
    assert result.outcome_kind == ComparisonOutcomeKind.INVALID
    assert "snapshot_mismatch" in result.limitations


def test_insufficient_configurations():
    engine = ComparisonEngine()
    result = engine.compare(
        ComparisonRequest(
            experiment_id="exp_5",
            workspace_id="ws_1",
            runs=[_run("only", "Only")],
        )
    )
    assert result.outcome_kind == ComparisonOutcomeKind.INVALID


def test_baseline_cheaper_comparable_quality():
    engine = ComparisonEngine()
    result = engine.compare(
        ComparisonRequest(
            experiment_id="exp_6",
            workspace_id="ws_1",
            baseline_configuration_id="baseline",
            quality_comparable_threshold=0.05,
            runs=[
                _run("baseline", "Direct", score=0.88, cost=0.05),
                _run("candidate", "Amplified", score=0.90, cost=0.25),
            ],
        )
    )
    assert result.outcome_kind in {
        ComparisonOutcomeKind.BASELINE_CHEAPER_COMPARABLE_QUALITY,
        ComparisonOutcomeKind.CANDIDATE_BETTER_QUALITY_HIGHER_COST,
        ComparisonOutcomeKind.MIXED,
    }
    # Amplified slightly higher quality but much higher cost → savings vs baseline not claimable as amplified win
    if result.cost_efficient_configuration_id == "baseline":
        assert "baseline" in result.successful_configuration_ids


def test_multi_configuration_ranking():
    engine = ComparisonEngine()
    result = engine.compare(
        ComparisonRequest(
            experiment_id="exp_7",
            workspace_id="ws_1",
            baseline_configuration_id="c1",
            runs=[
                _run("c1", "Direct", score=0.6, cost=0.1, latency=800),
                _run("c2", "Harness", score=0.75, cost=0.15, latency=1200, protocol="direct"),
                _run("c3", "Amplified", score=0.95, cost=0.12, latency=2000, protocol="amplified"),
            ],
        )
    )
    assert len(result.configurations) == 3
    assert result.quality_comparison.best_configuration_id == "c3"
    assert result.latency_comparison.best_configuration_id == "c1"
    assert result.highest_quality_configuration_id == "c3"


def test_no_universal_winner_in_report():
    service = ComparisonService()
    result = service.compare_runs(
        experiment_id="exp_8",
        workspace_id="ws_1",
        baseline_configuration_id="b",
        runs=[
            _run("b", "B", score=0.8, cost=0.1),
            _run("c", "C", score=0.85, cost=0.09),
        ],
    )
    report = service.report_dict(result)
    assert report["recommendations"]["universal_winner"] is None
    md = service.report_markdown(result)
    assert "universal winner" in md.lower() or "No universal winner" in md


def test_qualitative_scores_none_inconclusive_quality_dimension():
    engine = ComparisonEngine()
    result = engine.compare(
        ComparisonRequest(
            experiment_id="exp_9",
            workspace_id="ws_1",
            runs=[
                _run("a", "A", score=None, cost=0.1, succeeded=True),
                _run("b", "B", score=None, cost=0.2, succeeded=True),
            ],
        )
    )
    assert result.quality_comparison.comparable is False
    # Savings should not be claimable without comparable numeric quality when required
    assert result.cost_savings_claimable is False or result.cost_savings_vs_baseline is not None


@pytest.mark.asyncio
async def test_unified_engine_direct_builtin():
    engine = UnifiedExecutionEngine()
    req = ExecutionRequest(
        workspace_id="ws_u",
        task_id="task_1",
        protocol="direct",
        model_selection={"provider": "test", "model_id": "m1"},
    )
    eid = await engine.create(req)
    validation = await engine.validate(eid)
    assert validation.valid is True
    result = await engine.execute(eid)
    assert result.status == "COMPLETED"
    assert result.output is not None
    assert result.protocol == "direct"


@pytest.mark.asyncio
async def test_unified_engine_paired_produces_comparison():
    engine = UnifiedExecutionEngine()
    req = ExecutionRequest(
        workspace_id="ws_u",
        task_id="task_2",
        protocol="paired",
        configurations=[
            {
                "id": "baseline",
                "label": "Direct",
                "protocol": "direct",
                "overall_score": 0.7,
                "total_cost_usd": 0.2,
                "cost_availability": "ACTUAL",
                "succeeded": True,
                "latency_ms": 900,
            },
            {
                "id": "candidate",
                "label": "Amplified",
                "protocol": "amplified",
                "overall_score": 0.95,
                "total_cost_usd": 0.1,
                "cost_availability": "ACTUAL",
                "succeeded": True,
                "latency_ms": 1500,
            },
        ],
    )
    eid = await engine.create(req)
    result = await engine.execute(eid)
    assert result.status == "COMPLETED"
    assert result.comparison is not None
    assert result.comparison["outcome"]["kind"] == ComparisonOutcomeKind.CANDIDATE_BETTER_QUALITY_LOWER_COST.value
    assert result.comparison["recommendations"]["universal_winner"] is None
    assert result.comparison["economics"]["cost_savings_claimable"] is True


@pytest.mark.asyncio
async def test_unified_engine_paired_rejects_single_configuration():
    engine = UnifiedExecutionEngine()
    req = ExecutionRequest(
        workspace_id="ws_u",
        task_id="task_3",
        protocol="paired",
        configurations=[{"id": "only", "label": "Only"}],
    )
    eid = await engine.create(req)
    validation = await engine.validate(eid)
    assert validation.valid is False
    assert any("at least 2" in e for e in validation.errors)


@pytest.mark.asyncio
async def test_unified_engine_cancel():
    engine = UnifiedExecutionEngine()
    req = ExecutionRequest(workspace_id="ws_u", task_id="task_4", protocol="direct")
    eid = await engine.create(req)
    await engine.cancel(eid)
    status = await engine.get_status(eid)
    assert status["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_unknown_protocol_fails_validation():
    engine = UnifiedExecutionEngine()
    req = ExecutionRequest(workspace_id="ws_u", task_id="task_5", protocol="space_magic")
    eid = await engine.create(req)
    validation = await engine.validate(eid)
    assert validation.valid is False