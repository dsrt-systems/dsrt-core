# tests/test_c9_evidence.py
"""
C9.6 Evidence Engine — comprehensive tests.

Covers:
  - ArenaEvidenceAdapter (C8 → C9 bridge)
  - EvidenceFreshnessChecker (staleness detection)
  - EvidenceAggregator (uncertainty-aware aggregation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from core.routing.contracts import AggregatedEvidence, RoutingEvidence
from core.routing.enums import EvidenceConfidence, EvidenceSourceType
from core.routing.evidence.adapter import ArenaEvidenceAdapter
from core.routing.evidence.aggregator import EvidenceAggregator
from core.routing.evidence.freshness import (
    EvidenceFreshnessChecker,
    FreshnessResult,
)


# ── Helpers ────────────────────────────────────────────────────────────

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def _make_evidence(
    *,
    model_version: str = "m-v1",
    agent_version: str | None = "a-v1",
    world_version: str | None = "w-v1",
    benchmark_id: str = "bench-1",
    benchmark_version: str = "bv-1",
    sample_count: int = 10,
    metrics: dict | None = None,
    observed_at: datetime | None = None,
    source_type: EvidenceSourceType = EvidenceSourceType.ARENA_BENCHMARK,
) -> RoutingEvidence:
    return RoutingEvidence(
        source_type=source_type,
        benchmark_id=benchmark_id,
        benchmark_version=benchmark_version,
        agent_version=agent_version,
        model_version=model_version,
        world_version=world_version,
        sample_count=sample_count,
        metrics=metrics or {"quality": 0.8, "reliability": 0.9},
        observed_at=observed_at or _hours_ago(1),
    )


@dataclass
class FakeAggregation:
    """Mimics C8 MetricAggregation for adapter tests."""
    metric_id: str
    values: list[float] = field(default_factory=list)
    sample_count: int = 0
    consensus: str = "PASS"

    @property
    def mean_value(self) -> float | None:
        return sum(self.values) / len(self.values) if self.values else None


# ═══════════════════════════════════════════════════════════════════════
# ArenaEvidenceAdapter
# ═══════════════════════════════════════════════════════════════════════

class TestArenaEvidenceAdapter:

    def setup_method(self) -> None:
        self.adapter = ArenaEvidenceAdapter()

    def test_from_aggregations_basic(self) -> None:
        aggs = {
            "correctness": FakeAggregation(
                "correctness", [0.9, 0.85, 0.88], 3
            ),
        }
        ev = self.adapter.from_metric_aggregations(
            benchmark_id="b1",
            benchmark_version="1.0",
            model_version="m-v1",
            aggregations=aggs,
            observed_at=NOW,
        )
        assert ev.source_type == EvidenceSourceType.ARENA_BENCHMARK
        assert ev.benchmark_id == "b1"
        assert ev.model_version == "m-v1"
        assert ev.sample_count == 3
        assert abs(ev.metrics["correctness"] - 0.876666) < 0.01

    def test_from_aggregations_all_versions(self) -> None:
        aggs = {"q": FakeAggregation("q", [0.7], 5)}
        ev = self.adapter.from_metric_aggregations(
            benchmark_id="b1",
            benchmark_version="2.0",
            model_version="m-v2",
            agent_version="a-v3",
            world_version="w-v1",
            aggregations=aggs,
        )
        assert ev.agent_version == "a-v3"
        assert ev.world_version == "w-v1"
        assert ev.benchmark_version == "2.0"

    def test_from_aggregations_empty_metrics(self) -> None:
        ev = self.adapter.from_metric_aggregations(
            benchmark_id="b1",
            benchmark_version="1.0",
            model_version="m-v1",
            aggregations={},
            observed_at=NOW,
        )
        assert ev.metrics == {}
        assert ev.sample_count == 0

    def test_from_aggregations_multiple_metrics(self) -> None:
        aggs = {
            "quality": FakeAggregation("quality", [0.9], 10),
            "latency": FakeAggregation("latency", [120.0], 10),
            "cost": FakeAggregation("cost", [0.05], 10),
        }
        ev = self.adapter.from_metric_aggregations(
            benchmark_id="b1",
            benchmark_version="1.0",
            model_version="m-v1",
            aggregations=aggs,
        )
        assert "quality" in ev.metrics
        assert "latency" in ev.metrics
        assert "cost" in ev.metrics

    def test_from_aggregations_consensus_included(self) -> None:
        aggs = {
            "q": FakeAggregation("q", [0.9], 5, consensus="STRONG_PASS"),
        }
        ev = self.adapter.from_metric_aggregations(
            benchmark_id="b1",
            benchmark_version="1.0",
            model_version="m-v1",
            aggregations=aggs,
        )
        assert ev.metrics["q_consensus"] == "STRONG_PASS"

    def test_from_aggregations_dict_input(self) -> None:
        aggs = {
            "q": {"values": [0.8, 0.9], "sample_count": 2, "consensus": "PASS"},
        }
        ev = self.adapter.from_metric_aggregations(
            benchmark_id="b1",
            benchmark_version="1.0",
            model_version="m-v1",
            aggregations=aggs,
        )
        assert abs(ev.metrics["q"] - 0.85) < 0.001
        assert ev.sample_count == 2

    def test_from_aggregations_custom_source_type(self) -> None:
        ev = self.adapter.from_metric_aggregations(
            benchmark_id="b1",
            benchmark_version="1.0",
            model_version="m-v1",
            aggregations={},
            source_type=EvidenceSourceType.PRODUCTION_OBSERVATION,
        )
        assert ev.source_type == EvidenceSourceType.PRODUCTION_OBSERVATION

    def test_from_aggregations_empty_benchmark_raises(self) -> None:
        with pytest.raises(ValueError, match="benchmark_id"):
            self.adapter.from_metric_aggregations(
                benchmark_id="",
                benchmark_version="1.0",
                model_version="m-v1",
                aggregations={},
            )

    def test_from_aggregations_empty_model_raises(self) -> None:
        with pytest.raises(ValueError, match="model_version"):
            self.adapter.from_metric_aggregations(
                benchmark_id="b1",
                benchmark_version="1.0",
                model_version="",
                aggregations={},
            )

    def test_from_experiment_runs_basic(self) -> None:
        runs = [
            {
                "model_version": "m-v1",
                "agent_version": "a-v1",
                "status": "COMPLETED",
                "metrics": {"quality": 0.85},
                "sample_count": 5,
            },
        ]
        result = self.adapter.from_experiment_runs(
            benchmark_id="b1",
            benchmark_version="1.0",
            runs=runs,
            observed_at=NOW,
        )
        assert len(result) == 1
        assert result[0].metrics["quality"] == 0.85
        assert result[0].source_type == EvidenceSourceType.ARENA_EXPERIMENT

    def test_from_experiment_runs_skips_non_completed(self) -> None:
        runs = [
            {"model_version": "m-v1", "status": "FAILED", "metrics": {"q": 0.5}},
            {"model_version": "m-v1", "status": "RUNNING", "metrics": {"q": 0.5}},
            {"model_version": "m-v1", "status": "COMPLETED", "metrics": {"q": 0.9}},
        ]
        result = self.adapter.from_experiment_runs(
            benchmark_id="b1", benchmark_version="1.0", runs=runs,
        )
        assert len(result) == 1
        assert result[0].metrics["q"] == 0.9

    def test_from_experiment_runs_skips_no_metrics(self) -> None:
        runs = [
            {"model_version": "m-v1", "status": "COMPLETED", "metrics": {}},
            {"model_version": "m-v1", "status": "COMPLETED"},
        ]
        result = self.adapter.from_experiment_runs(
            benchmark_id="b1", benchmark_version="1.0", runs=runs,
        )
        assert len(result) == 0

    def test_from_experiment_runs_empty(self) -> None:
        result = self.adapter.from_experiment_runs(
            benchmark_id="b1", benchmark_version="1.0", runs=[],
        )
        assert result == []

    def test_from_experiment_runs_empty_benchmark_raises(self) -> None:
        with pytest.raises(ValueError, match="benchmark_id"):
            self.adapter.from_experiment_runs(
                benchmark_id="", benchmark_version="1.0", runs=[],
            )

    def test_from_aggregations_sample_count_max(self) -> None:
        aggs = {
            "a": FakeAggregation("a", [0.5], 10),
            "b": FakeAggregation("b", [0.6], 50),
        }
        ev = self.adapter.from_metric_aggregations(
            benchmark_id="b1",
            benchmark_version="1.0",
            model_version="m-v1",
            aggregations=aggs,
        )
        assert ev.sample_count == 50  # max across metrics


# ═══════════════════════════════════════════════════════════════════════
# EvidenceFreshnessChecker
# ═══════════════════════════════════════════════════════════════════════

class TestEvidenceFreshnessChecker:

    def setup_method(self) -> None:
        self.checker = EvidenceFreshnessChecker(max_age_hours=168.0)

    def test_fresh_evidence(self) -> None:
        ev = _make_evidence(observed_at=_hours_ago(1))
        r = self.checker.check(ev, now=NOW)
        assert r.is_fresh is True
        assert r.freshness_weight > 0.99
        assert r.staleness_reasons == []

    def test_stale_evidence_age(self) -> None:
        ev = _make_evidence(observed_at=_hours_ago(200))
        r = self.checker.check(ev, now=NOW)
        assert r.is_fresh is False
        assert r.freshness_weight == 0.0
        assert any("age" in s for s in r.staleness_reasons)

    def test_exactly_at_max_age(self) -> None:
        ev = _make_evidence(observed_at=_hours_ago(168))
        r = self.checker.check(ev, now=NOW)
        assert r.freshness_weight == 0.0

    def test_half_max_age(self) -> None:
        ev = _make_evidence(observed_at=_hours_ago(84))
        r = self.checker.check(ev, now=NOW)
        assert abs(r.freshness_weight - 0.5) < 0.01

    def test_version_match_all(self) -> None:
        ev = _make_evidence(
            model_version="m-v1",
            agent_version="a-v1",
            observed_at=_hours_ago(1),
        )
        r = self.checker.check(
            ev,
            current_model_version="m-v1",
            current_agent_version="a-v1",
            now=NOW,
        )
        assert r.version_matches == {"model": True, "agent": True}
        assert r.is_fresh is True

    def test_version_mismatch_model(self) -> None:
        ev = _make_evidence(model_version="m-v1", observed_at=_hours_ago(1))
        r = self.checker.check(
            ev, current_model_version="m-v2", now=NOW,
        )
        assert r.version_matches["model"] is False
        assert r.freshness_weight < 1.0
        assert any("model" in s for s in r.staleness_reasons)

    def test_version_mismatch_agent(self) -> None:
        ev = _make_evidence(agent_version="a-v1", observed_at=_hours_ago(1))
        r = self.checker.check(
            ev, current_agent_version="a-v2", now=NOW,
        )
        assert r.version_matches["agent"] is False

    def test_no_version_check_when_none(self) -> None:
        ev = _make_evidence(observed_at=_hours_ago(1))
        r = self.checker.check(ev, now=NOW)
        assert r.version_matches == {}
        assert r.is_fresh is True

    def test_combined_staleness(self) -> None:
        ev = _make_evidence(
            model_version="m-v1",
            observed_at=_hours_ago(200),  # exceeds 168h max
        )
        r = self.checker.check(
            ev, current_model_version="m-v2", now=NOW,
        )
        # age_weight = 0.0 (exceeded), version_weight = 0.5
        assert r.freshness_weight == 0.0
        assert len(r.staleness_reasons) >= 2
        assert any("age" in s for s in r.staleness_reasons)
        assert any("model" in s for s in r.staleness_reasons)
        
    def test_custom_max_age(self) -> None:
        checker = EvidenceFreshnessChecker(max_age_hours=24.0)
        ev = _make_evidence(observed_at=_hours_ago(12))
        r = checker.check(ev, now=NOW)
        assert abs(r.freshness_weight - 0.5) < 0.01

    def test_zero_age(self) -> None:
        ev = _make_evidence(observed_at=NOW)
        r = self.checker.check(ev, now=NOW)
        assert r.freshness_weight == 1.0
        assert r.age_hours == 0.0

    def test_invalid_max_age_raises(self) -> None:
        with pytest.raises(ValueError, match="max_age_hours"):
            EvidenceFreshnessChecker(max_age_hours=0)

    def test_invalid_penalty_raises(self) -> None:
        with pytest.raises(ValueError, match="version_mismatch_penalty"):
            EvidenceFreshnessChecker(version_mismatch_penalty=1.5)

    def test_naive_datetime_handled(self) -> None:
        ev = _make_evidence(
            observed_at=datetime(2025, 6, 15, 11, 0, 0)  # no tz
        )
        r = self.checker.check(ev, now=NOW)
        assert r.age_hours >= 0


# ═══════════════════════════════════════════════════════════════════════
# EvidenceAggregator
# ═══════════════════════════════════════════════════════════════════════

class TestEvidenceAggregator:

    def setup_method(self) -> None:
        self.checker = EvidenceFreshnessChecker(max_age_hours=168.0)
        self.agg = EvidenceAggregator(
            freshness_checker=self.checker,
            min_samples_high=50,
            min_samples_medium=10,
            min_samples_low=3,
        )

    def test_aggregate_empty(self) -> None:
        result = self.agg.aggregate("cand-1", [], now=NOW)
        assert result.candidate_key == "cand-1"
        assert result.total_sample_count == 0
        assert result.confidence == EvidenceConfidence.INSUFFICIENT
        assert result.has_sufficient_evidence is False

    def test_aggregate_single(self) -> None:
        ev = _make_evidence(
            sample_count=100,
            metrics={"quality": 0.9},
            observed_at=_hours_ago(1),
        )
        result = self.agg.aggregate("cand-1", [ev], now=NOW)
        assert result.total_sample_count > 0
        assert "quality" in result.aggregated_metrics
        assert abs(result.aggregated_metrics["quality"] - 0.9) < 0.01

    def test_aggregate_multiple(self) -> None:
        ev1 = _make_evidence(
            sample_count=50,
            metrics={"quality": 0.8},
            observed_at=_hours_ago(1),
        )
        ev2 = _make_evidence(
            sample_count=50,
            metrics={"quality": 0.9},
            observed_at=_hours_ago(2),
        )
        result = self.agg.aggregate("cand-1", [ev1, ev2], now=NOW)
        # Both fresh, so weighted mean ≈ 0.85
        assert 0.83 < result.aggregated_metrics["quality"] < 0.87

    def test_aggregate_total_sample_count(self) -> None:
        ev = _make_evidence(
            sample_count=20,
            observed_at=_hours_ago(1),
        )
        result = self.agg.aggregate("cand-1", [ev], now=NOW)
        # freshness ≈ 1.0, so total ≈ 20
        assert result.total_sample_count == 20

    def test_aggregate_stale_discounted(self) -> None:
        ev = _make_evidence(
            sample_count=100,
            metrics={"quality": 0.9},
            observed_at=_hours_ago(160),  # almost fully stale
        )
        result = self.agg.aggregate("cand-1", [ev], now=NOW)
        # freshness ≈ 1 - 160/168 ≈ 0.048
        # weighted samples ≈ 100 * 0.048 ≈ 5
        assert result.total_sample_count < 10

    def test_confidence_high(self) -> None:
        ev = _make_evidence(
            sample_count=100,
            observed_at=_hours_ago(1),
        )
        result = self.agg.aggregate("cand-1", [ev], now=NOW)
        assert result.confidence == EvidenceConfidence.HIGH

    def test_confidence_medium(self) -> None:
        ev = _make_evidence(
            sample_count=20,
            observed_at=_hours_ago(1),
        )
        result = self.agg.aggregate("cand-1", [ev], now=NOW)
        assert result.confidence == EvidenceConfidence.MEDIUM

    def test_confidence_low(self) -> None:
        ev = _make_evidence(
            sample_count=5,
            observed_at=_hours_ago(1),
        )
        result = self.agg.aggregate("cand-1", [ev], now=NOW)
        assert result.confidence == EvidenceConfidence.LOW

    def test_confidence_insufficient(self) -> None:
        ev = _make_evidence(
            sample_count=1,
            observed_at=_hours_ago(1),
        )
        result = self.agg.aggregate("cand-1", [ev], now=NOW)
        assert result.confidence == EvidenceConfidence.INSUFFICIENT

    def test_has_sufficient_evidence(self) -> None:
        ev = _make_evidence(sample_count=100, observed_at=_hours_ago(1))
        result = self.agg.aggregate("cand-1", [ev], now=NOW)
        assert result.has_sufficient_evidence is True

    def test_no_sufficient_evidence(self) -> None:
        result = self.agg.aggregate("cand-1", [], now=NOW)
        assert result.has_sufficient_evidence is False

    def test_freshness_weight_average(self) -> None:
        ev1 = _make_evidence(
            sample_count=10, observed_at=_hours_ago(1),
        )
        ev2 = _make_evidence(
            sample_count=10, observed_at=_hours_ago(84),
        )
        result = self.agg.aggregate("cand-1", [ev1, ev2], now=NOW)
        # ev1 fw ≈ 0.994, ev2 fw ≈ 0.5 → avg ≈ 0.747
        assert 0.6 < result.freshness_weight < 0.85

    def test_version_filtering_reduces_confidence(self) -> None:
        ev = _make_evidence(
            model_version="m-v1",
            sample_count=100,
            observed_at=_hours_ago(1),
        )
        result = self.agg.aggregate(
            "cand-1",
            [ev],
            current_versions={"model": "m-v2"},
            now=NOW,
        )
        # version mismatch → freshness_weight ≈ 0.5
        # effective samples ≈ 50 → still MEDIUM
        assert result.confidence in (
            EvidenceConfidence.MEDIUM,
            EvidenceConfidence.LOW,
        )

    def test_preserves_sources(self) -> None:
        ev1 = _make_evidence(sample_count=5, observed_at=_hours_ago(1))
        ev2 = _make_evidence(sample_count=5, observed_at=_hours_ago(2))
        result = self.agg.aggregate("cand-1", [ev1, ev2], now=NOW)
        assert len(result.sources) == 2

    def test_deterministic(self) -> None:
        ev = _make_evidence(
            sample_count=50,
            metrics={"q": 0.85},
            observed_at=_hours_ago(10),
        )
        r1 = self.agg.aggregate("cand-1", [ev], now=NOW)
        r2 = self.agg.aggregate("cand-1", [ev], now=NOW)
        assert r1.aggregated_metrics == r2.aggregated_metrics
        assert r1.total_sample_count == r2.total_sample_count
        assert r1.confidence == r2.confidence

    def test_empty_candidate_key_raises(self) -> None:
        with pytest.raises(ValueError, match="candidate_key"):
            self.agg.aggregate("", [_make_evidence()], now=NOW)

    def test_non_numeric_metrics_ignored(self) -> None:
        ev = _make_evidence(
            sample_count=10,
            metrics={"quality": 0.8, "notes": "looks good"},
            observed_at=_hours_ago(1),
        )
        result = self.agg.aggregate("cand-1", [ev], now=NOW)
        assert "quality" in result.aggregated_metrics
        assert "notes" not in result.aggregated_metrics

    def test_mixed_freshness_sources(self) -> None:
        fresh = _make_evidence(
            sample_count=10,
            metrics={"q": 0.9},
            observed_at=_hours_ago(1),
        )
        stale = _make_evidence(
            sample_count=10,
            metrics={"q": 0.5},
            observed_at=_hours_ago(160),
        )
        result = self.agg.aggregate("cand-1", [fresh, stale], now=NOW)
        # Fresh evidence should dominate
        assert result.aggregated_metrics["q"] > 0.7