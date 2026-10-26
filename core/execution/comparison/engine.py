# Path: core/execution/comparison/engine.py
"""
Comparison Engine — fair, multi-configuration, evidence-backed.

Does not manufacture winners. Cost savings are claimable only when quality
is present and the candidate meets the success / comparability gates.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from core.execution.comparison.contracts import (
    ComparisonOutcomeKind,
    ComparisonRequest,
    ComparisonResult,
    ConfigurationRunEvidence,
)
from core.execution.comparison.metrics import ComparisonMetricsCalculator


class ComparisonEngine:
    """Core comparison logic over normalized run evidence."""

    def __init__(self, metrics: Optional[ComparisonMetricsCalculator] = None):
        self.metrics = metrics or ComparisonMetricsCalculator()

    def compare(self, request: ComparisonRequest) -> ComparisonResult:
        runs = list(request.runs or [])
        labels = {r.configuration_id: r.configuration_label for r in runs}
        config_ids = [r.configuration_id for r in runs]

        result = ComparisonResult(
            experiment_id=request.experiment_id,
            workspace_id=request.workspace_id,
            configurations=config_ids,
            configuration_labels=labels,
            baseline_configuration_id=request.baseline_configuration_id,
            evaluator_version=request.evaluator_version,
            protocol_valid=request.protocol_valid,
        )

        # --- Protocol validity gate ---
        if not request.protocol_valid:
            result.outcome_kind = ComparisonOutcomeKind.INVALID
            result.outcome_summary = "Comparison invalid: experiment protocol was not satisfied."
            result.limitations.extend(request.protocol_invalid_reasons or ["protocol_invalid"])
            result.findings.append("No ranking issued because the comparison protocol is invalid.")
            return result

        if len(runs) < 2:
            result.outcome_kind = ComparisonOutcomeKind.INVALID
            result.outcome_summary = "Comparison invalid: at least two configurations are required."
            result.limitations.append("insufficient_configurations")
            return result

        # --- Dimension comparisons ---
        result.quality_comparison = self.metrics.quality(runs)
        result.completion_comparison = self.metrics.completion(runs)
        result.correctness_comparison = self.metrics.correctness(runs)
        result.reliability_comparison = self.metrics.reliability(runs)
        result.cost_comparison = self.metrics.cost(runs)
        result.latency_comparison = self.metrics.latency(runs)
        result.verification_comparison = self.metrics.verification(runs)
        result.recovery_comparison = self.metrics.recovery(runs)

        result.highest_quality_configuration_id = result.quality_comparison.best_configuration_id
        result.lowest_latency_configuration_id = result.latency_comparison.best_configuration_id

        # --- Successful set ---
        successful = self._successful_runs(runs, request.quality_success_threshold)
        result.successful_configuration_ids = [r.configuration_id for r in successful]

        # Collect findings / limitations from runs
        for r in runs:
            for f in r.findings:
                result.findings.append(f"[{r.configuration_label}] {f}")
            for lim in r.limitations:
                result.limitations.append(f"[{r.configuration_label}] {lim}")

        for dim in (
            result.quality_comparison,
            result.cost_comparison,
            result.latency_comparison,
        ):
            result.limitations.extend(dim.notes)

        # --- Cost efficiency (quality-gated) ---
        result.cost_efficient_configuration_id = self._select_cost_efficient(
            runs, successful, request
        )
        self._apply_savings(result, runs, request, successful)

        # --- Outcome classification ---
        result.outcome_kind, result.outcome_summary = self._classify_outcome(
            runs, successful, result, request
        )
        result.findings.append(result.outcome_summary)
        return result

    def _successful_runs(
        self,
        runs: List[ConfigurationRunEvidence],
        quality_success_threshold: float,
    ) -> List[ConfigurationRunEvidence]:
        out: List[ConfigurationRunEvidence] = []
        for r in runs:
            if r.failed or r.cancelled:
                continue
            if r.succeeded or r.task_success is True:
                if r.overall_score is None or r.overall_score >= quality_success_threshold:
                    out.append(r)
                    continue
            # Deterministic success via score alone
            if (
                r.overall_score is not None
                and r.overall_score >= quality_success_threshold
                and not r.failed
            ):
                out.append(r)
        return out

    def _select_cost_efficient(
        self,
        runs: List[ConfigurationRunEvidence],
        successful: List[ConfigurationRunEvidence],
        request: ComparisonRequest,
    ) -> Optional[str]:
        pool = successful if request.require_quality_for_savings else [
            r for r in runs if r.total_cost_usd is not None
        ]
        pool = [r for r in pool if r.total_cost_usd is not None and r.cost_availability != "UNAVAILABLE"]
        if not pool:
            return None
        pool.sort(key=lambda r: float(r.total_cost_usd))  # type: ignore[arg-type]
        return pool[0].configuration_id

    def _quality_comparable(
        self,
        a: ConfigurationRunEvidence,
        b: ConfigurationRunEvidence,
        threshold: float,
    ) -> bool:
        if a.overall_score is None or b.overall_score is None:
            return False
        return abs(float(a.overall_score) - float(b.overall_score)) <= threshold

    def _apply_savings(
        self,
        result: ComparisonResult,
        runs: List[ConfigurationRunEvidence],
        request: ComparisonRequest,
        successful: List[ConfigurationRunEvidence],
    ) -> None:
        baseline_id = request.baseline_configuration_id
        if not baseline_id:
            # Default baseline = first configuration
            baseline_id = runs[0].configuration_id
            result.baseline_configuration_id = baseline_id
        else:
            result.baseline_configuration_id = baseline_id

        by_id: Dict[str, ConfigurationRunEvidence] = {r.configuration_id: r for r in runs}
        baseline = by_id.get(baseline_id)
        if baseline is None or baseline.total_cost_usd is None:
            result.cost_savings_claimable = False
            result.limitations.append("baseline_cost_unavailable")
            return

        # Candidate = cost-efficient successful non-baseline, else best quality non-baseline
        candidate_id = result.cost_efficient_configuration_id
        if candidate_id is None or candidate_id == baseline_id:
            non_base_success = [r for r in successful if r.configuration_id != baseline_id]
            if non_base_success and result.highest_quality_configuration_id:
                cand = by_id.get(result.highest_quality_configuration_id)
                if cand and cand.configuration_id != baseline_id:
                    candidate_id = cand.configuration_id
            elif non_base_success:
                candidate_id = non_base_success[0].configuration_id

        if not candidate_id or candidate_id == baseline_id:
            result.cost_savings_claimable = False
            return

        candidate = by_id.get(candidate_id)
        if candidate is None or candidate.total_cost_usd is None:
            result.cost_savings_claimable = False
            return

        if float(baseline.total_cost_usd) <= 0:
            result.cost_savings_claimable = False
            result.limitations.append("baseline_cost_non_positive")
            return

        savings = 1.0 - (float(candidate.total_cost_usd) / float(baseline.total_cost_usd))
        result.cost_savings_vs_baseline = round(savings, 6)

        claimable = True
        if request.require_quality_for_savings:
            cand_ok = candidate.configuration_id in result.successful_configuration_ids
            if not cand_ok:
                claimable = False
                result.limitations.append("savings_not_claimable_candidate_quality_insufficient")
            elif candidate.overall_score is not None and baseline.overall_score is not None:
                # Candidate must not be materially worse
                if float(candidate.overall_score) + 1e-9 < float(baseline.overall_score) - request.quality_comparable_threshold:
                    claimable = False
                    result.limitations.append("savings_not_claimable_candidate_quality_worse")
            elif candidate.overall_score is None or baseline.overall_score is None:
                # If either lacks numeric quality, only allow when both succeeded on task_success
                if not (
                    (candidate.succeeded or candidate.task_success is True)
                    and (baseline.succeeded or baseline.task_success is True)
                ):
                    claimable = False
                    result.limitations.append("savings_not_claimable_quality_not_comparable")

        if candidate.cost_availability == "UNAVAILABLE" or baseline.cost_availability == "UNAVAILABLE":
            claimable = False
            result.limitations.append("savings_not_claimable_cost_unavailable")

        result.cost_savings_claimable = claimable

    def _classify_outcome(
        self,
        runs: List[ConfigurationRunEvidence],
        successful: List[ConfigurationRunEvidence],
        result: ComparisonResult,
        request: ComparisonRequest,
    ) -> tuple:
        all_failed = all(r.failed or (not r.succeeded and r.task_success is not True) for r in runs)
        if all_failed and not successful:
            # Distinguish total failure vs partial experiment
            any_partial = any(
                r.run_status.upper() in {"PARTIALLY_COMPLETED", "PARTIAL"} for r in runs
            )
            if any_partial:
                return (
                    ComparisonOutcomeKind.PARTIAL,
                    "One or more runs only partially completed; no clean success set.",
                )
            return (
                ComparisonOutcomeKind.ALL_FAILED,
                "All compared configurations failed to complete the task successfully.",
            )

        if not successful:
            return (
                ComparisonOutcomeKind.INCONCLUSIVE,
                "No configuration met success criteria; comparison is inconclusive.",
            )

        baseline_id = result.baseline_configuration_id or runs[0].configuration_id
        by_id = {r.configuration_id: r for r in runs}
        baseline = by_id.get(baseline_id)

        # Prefer primary candidate = highest quality among successful non-baseline
        non_base_success = [r for r in successful if r.configuration_id != baseline_id]
        if not non_base_success:
            if baseline and baseline.configuration_id in result.successful_configuration_ids:
                return (
                    ComparisonOutcomeKind.BASELINE_BETTER_QUALITY,
                    "Only the baseline configuration met success criteria.",
                )
            return (
                ComparisonOutcomeKind.INCONCLUSIVE,
                "Successful runs do not yield a clear baseline/candidate contrast.",
            )

        candidate = non_base_success[0]
        if result.highest_quality_configuration_id:
            hq = by_id.get(result.highest_quality_configuration_id)
            if hq and hq.configuration_id != baseline_id and hq in non_base_success:
                candidate = hq
            elif hq and hq.configuration_id == baseline_id:
                # Baseline has highest quality among all
                # Check if candidate quality is comparable
                pass

        b_score = baseline.overall_score if baseline else None
        c_score = candidate.overall_score
        b_cost = baseline.total_cost_usd if baseline else None
        c_cost = candidate.total_cost_usd

        quality_better = False
        quality_worse = False
        quality_comparable = False

        if c_score is not None and b_score is not None:
            gap = float(c_score) - float(b_score)
            if gap > request.quality_comparable_threshold:
                quality_better = True
            elif gap < -request.quality_comparable_threshold:
                quality_worse = True
            else:
                quality_comparable = True
        else:
            # Fall back to success flags
            if candidate.configuration_id in result.successful_configuration_ids:
                if baseline and baseline.configuration_id not in result.successful_configuration_ids:
                    quality_better = True
                else:
                    quality_comparable = True

        cost_lower = (
            c_cost is not None and b_cost is not None and float(c_cost) < float(b_cost)
        )
        cost_higher = (
            c_cost is not None and b_cost is not None and float(c_cost) > float(b_cost)
        )

        if quality_better and cost_lower:
            return (
                ComparisonOutcomeKind.CANDIDATE_BETTER_QUALITY_LOWER_COST,
                (
                    f"Configuration '{candidate.configuration_label}' achieved better quality "
                    f"at lower cost than baseline '{baseline.configuration_label if baseline else baseline_id}'."
                ),
            )
        if quality_better and (cost_higher or c_cost is None):
            return (
                ComparisonOutcomeKind.CANDIDATE_BETTER_QUALITY_HIGHER_COST,
                (
                    f"Configuration '{candidate.configuration_label}' achieved better quality "
                    f"at higher or unknown cost versus baseline."
                ),
            )
        if quality_comparable and cost_lower:
            return (
                ComparisonOutcomeKind.BASELINE_CHEAPER_COMPARABLE_QUALITY
                if (b_cost is not None and c_cost is not None and float(b_cost) < float(c_cost))
                else ComparisonOutcomeKind.CANDIDATE_BETTER_QUALITY_LOWER_COST
                if cost_lower
                else ComparisonOutcomeKind.MIXED,
                (
                    f"Quality is comparable between '{candidate.configuration_label}' and baseline; "
                    f"cost differs."
                ),
            )
        if quality_comparable and cost_lower is False and b_cost is not None and c_cost is not None:
            if float(b_cost) <= float(c_cost):
                return (
                    ComparisonOutcomeKind.BASELINE_CHEAPER_COMPARABLE_QUALITY,
                    (
                        f"Baseline '{baseline.configuration_label if baseline else baseline_id}' "
                        f"is cheaper with comparable quality."
                    ),
                )

        if quality_worse:
            return (
                ComparisonOutcomeKind.BASELINE_BETTER_QUALITY,
                (
                    f"Baseline quality exceeds candidate '{candidate.configuration_label}'."
                ),
            )

        # Mixed / multi-config without clear binary story
        if len(successful) >= 2:
            return (
                ComparisonOutcomeKind.MIXED,
                "Multiple configurations succeeded with mixed quality/cost trade-offs; see dimension rankings.",
            )

        return (
            ComparisonOutcomeKind.INCONCLUSIVE,
            "Results do not support a definitive comparative outcome.",
        )