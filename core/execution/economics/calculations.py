"""
CostCalculator — derived economics metrics.

Formulas (spec §8):
    cost_per_successful_task = total_execution_cost / successful_tasks
    cost_savings = 1 - (C_amplified / C_baseline)   # only when quality-comparable

Never claim savings without comparable quality.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.execution.economics.contracts import CostBreakdown
from core.execution.economics.ledger import CostLedger


class CostComparisonResult(BaseModel):
    """Fair cost comparison between two (or more) execution paths."""

    baseline_label: str
    candidate_label: str
    baseline_cost_usd: float
    candidate_cost_usd: float
    absolute_difference_usd: float
    # savings_ratio = 1 - candidate/baseline ; positive means candidate cheaper
    savings_ratio: float | None = None
    savings_percent: float | None = None
    quality_comparable: bool = False
    baseline_quality_score: float | None = None
    candidate_quality_score: float | None = None
    quality_threshold: float | None = None
    valid: bool = False
    findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CostCalculator:
    """Pure calculations over ledger breakdowns."""

    def __init__(self, ledger: CostLedger) -> None:
        self._ledger = ledger

    # -- unit economics -----------------------------------------------------

    def cost_per_attempt(
        self,
        *,
        total_cost_usd: float,
        attempts: int,
    ) -> float | None:
        if attempts <= 0:
            return None
        return total_cost_usd / attempts

    def cost_per_successful_task(
        self,
        *,
        total_cost_usd: float,
        successful_tasks: int,
    ) -> float | None:
        """
        Returns None when there are zero successful tasks — never divide
        by zero or invent a number.
        """
        if successful_tasks <= 0:
            return None
        return total_cost_usd / successful_tasks

    # -- path totals --------------------------------------------------------

    def execution_total(self, execution_id: str) -> CostBreakdown:
        return self._ledger.breakdown(execution_id=execution_id)

    def experiment_total(self, experiment_id: str) -> CostBreakdown:
        return self._ledger.breakdown(experiment_id=experiment_id)

    def run_total(self, run_id: str) -> CostBreakdown:
        return self._ledger.breakdown(run_id=run_id)

    def category_share(
        self, breakdown: CostBreakdown,
    ) -> dict[str, float]:
        """Fraction of known cost per category. Empty if known total is 0."""
        if breakdown.total_known_usd <= 0:
            return {}
        return {
            k: v.known_usd / breakdown.total_known_usd
            for k, v in breakdown.by_category.items()
        }

    # -- comparison ---------------------------------------------------------

    def compare_paths(
        self,
        *,
        baseline_cost_usd: float,
        candidate_cost_usd: float,
        baseline_label: str = "baseline",
        candidate_label: str = "candidate",
        baseline_quality_score: float | None = None,
        candidate_quality_score: float | None = None,
        quality_threshold: float | None = None,
        require_quality_comparable: bool = True,
    ) -> CostComparisonResult:
        """
        Compute cost savings between two paths.

        Savings are only marked ``valid=True`` when:
        1. Both costs are finite and baseline_cost > 0
        2. If require_quality_comparable: both quality scores present AND
           candidate quality >= threshold (or >= baseline if no threshold)
        """
        findings: list[str] = []
        limitations: list[str] = []

        abs_diff = candidate_cost_usd - baseline_cost_usd
        result = CostComparisonResult(
            baseline_label=baseline_label,
            candidate_label=candidate_label,
            baseline_cost_usd=baseline_cost_usd,
            candidate_cost_usd=candidate_cost_usd,
            absolute_difference_usd=abs_diff,
            baseline_quality_score=baseline_quality_score,
            candidate_quality_score=candidate_quality_score,
            quality_threshold=quality_threshold,
        )

        if baseline_cost_usd < 0 or candidate_cost_usd < 0:
            limitations.append("Negative costs are invalid.")
            return result

        if baseline_cost_usd == 0:
            limitations.append(
                "Baseline cost is zero; savings ratio is undefined."
            )
            return result

        savings_ratio = 1.0 - (candidate_cost_usd / baseline_cost_usd)
        result.savings_ratio = savings_ratio
        result.savings_percent = savings_ratio * 100.0

        # Quality gate
        quality_ok = True
        if require_quality_comparable:
            if baseline_quality_score is None or candidate_quality_score is None:
                quality_ok = False
                limitations.append(
                    "Quality scores missing; cannot claim comparable-quality savings."
                )
            else:
                threshold = (
                    quality_threshold
                    if quality_threshold is not None
                    else baseline_quality_score
                )
                if candidate_quality_score + 1e-12 < threshold:
                    quality_ok = False
                    findings.append(
                        f"Candidate quality {candidate_quality_score:.4f} is below "
                        f"required threshold {threshold:.4f}; savings not valid."
                    )
                else:
                    findings.append(
                        f"Quality comparable: candidate {candidate_quality_score:.4f} "
                        f">= threshold {threshold:.4f}."
                    )

        result.quality_comparable = quality_ok if require_quality_comparable else True
        result.valid = result.quality_comparable and result.savings_ratio is not None

        if result.valid:
            if savings_ratio > 0:
                findings.append(
                    f"{candidate_label} is {result.savings_percent:.2f}% cheaper "
                    f"than {baseline_label} at comparable quality."
                )
            elif savings_ratio < 0:
                findings.append(
                    f"{candidate_label} is {abs(result.savings_percent):.2f}% more "
                    f"expensive than {baseline_label} at comparable quality."
                )
            else:
                findings.append("Costs are equal at comparable quality.")
        else:
            limitations.append(
                "Savings figure must not be presented as a valid claim."
            )

        result.findings = findings
        result.limitations = limitations
        return result