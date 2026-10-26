"""
C11.5 — Economic Optimization Engine (top-level orchestrator).

Combines cost estimation, constraint checking, and objective scoring
to select the optimal execution configuration and produce a frozen
OptimizationPlanOutput.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from schemas.domain.economic_optimization import (
    BudgetExecutionLimits,
    CandidateFeasibility,
    ExecutionConfigCandidate,
    FeasibilityStatus,
    OptimizationConstraints,
    OptimizationPlanOutput,
    OptimizationPolicy,
    PlanStatus,
    PredictionRecord,
    ScoredCandidate,
)
from schemas.domain.task_intelligence import TaskProfile

from core.optimization.economics.constraints import ConstraintChecker
from core.optimization.economics.cost_estimator import CostEstimator
from core.optimization.economics.objective import ObjectiveScorer

logger = logging.getLogger(__name__)


class EconomicOptimizer:
    def __init__(
        self,
        cost_estimator: CostEstimator | None = None,
        constraint_checker: ConstraintChecker | None = None,
        objective_scorer: ObjectiveScorer | None = None,
    ) -> None:
        self._cost_estimator = cost_estimator or CostEstimator()
        self._constraint_checker = constraint_checker or ConstraintChecker()
        self._scorer = objective_scorer or ObjectiveScorer()

    def optimize(
        self,
        task_profile: TaskProfile,
        candidates: list[ExecutionConfigCandidate],
        constraints: OptimizationConstraints,
        policy: OptimizationPolicy = OptimizationPolicy.BALANCED,
        workspace_id: str = "",
        approval_required: bool = False,
    ) -> OptimizationPlanOutput:
        if not candidates:
            raise ValueError("At least one candidate configuration is required")

        optimization_id = str(uuid.uuid4())

        for cand in candidates:
            if cand.cost_breakdown.total <= 0:
                breakdown = self._cost_estimator.estimate(
                    task_profile=task_profile,
                    model_fingerprint=cand.model_fingerprint,
                    model_tier=cand.metadata.get("model_tier", "unknown"),
                    strategies=cand.strategies,
                    tools=cand.tools,
                    verification_level=cand.verification_level,
                    agent_id=cand.agent_id,
                )
                cand.cost_breakdown = breakdown

        feasibility_map: dict[str, CandidateFeasibility] = {}
        feasible_ids: list[str] = []
        for cand in candidates:
            feas = self._constraint_checker.check(cand, constraints)
            feasibility_map[cand.candidate_id] = feas
            if feas.status == FeasibilityStatus.FEASIBLE:
                feasible_ids.append(cand.candidate_id)

        scored_all: list[ScoredCandidate] = []
        for cand in candidates:
            scored = self._scorer.score(
                cand, feasibility_map[cand.candidate_id], policy
            )
            scored_all.append(scored)

        scored_all.sort(key=lambda s: s.objective_score, reverse=True)

        cand_lookup = {c.candidate_id: c for c in candidates}
        selected: ExecutionConfigCandidate | None = None
        decision_reasons: list[str] = []
        limitations: list[str] = []

        if feasible_ids:
            best = scored_all[0]
            selected = cand_lookup[best.candidate_id]
            decision_reasons.append(
                f"Selected {best.candidate_id} with objective score {best.objective_score:.4f} "
                f"under {policy.value} policy"
            )
            decision_reasons.append(
                f"Quality={best.quality_score:.3f} Reliability={best.reliability_score:.3f} "
                f"Cost={best.cost_score:.3f} Latency={best.latency_score:.3f}"
            )
            if best.evidence_penalty > 0:
                limitations.append(
                    f"Evidence penalty {best.evidence_penalty:.3f} applied due to limited evidence"
                )
        else:
            best_infeasible = min(scored_all, key=lambda s: len(s.feasibility.violations))
            selected = cand_lookup[best_infeasible.candidate_id]
            decision_reasons.append(
                "No feasible configuration found; returning least-infeasible candidate"
            )
            for v in best_infeasible.feasibility.violations:
                limitations.append(f"Constraint violation: {v}")

        budget_limits = self._compute_budget_limits(
            selected, constraints, task_profile
        )

        alternatives = [
            s for s in scored_all if s.candidate_id != selected.candidate_id
        ]

        plan_status = PlanStatus.PROPOSED if feasible_ids else PlanStatus.DRAFT

        plan = OptimizationPlanOutput(
            optimization_id=optimization_id,
            plan_version="1",
            task_profile_id=task_profile.task_id,
            workspace_id=workspace_id,
            selected_candidate=selected,
            alternatives=alternatives,
            estimated_quality=selected.estimated_quality,
            estimated_reliability=selected.estimated_reliability,
            estimated_cost=round(selected.cost_breakdown.total, 6),
            estimated_latency_ms=selected.estimated_latency_ms,
            authorized_budget=constraints.max_budget,
            budget_limits=budget_limits,
            optimization_policy=policy,
            constraints=constraints,
            decision_reasons=decision_reasons,
            limitations=limitations,
            approval_required=approval_required,
            status=plan_status,
        )
        logger.info(
            "Optimization plan %s: selected=%s cost=$%.4f status=%s",
            optimization_id,
            selected.candidate_id,
            selected.cost_breakdown.total,
            plan_status.value,
        )
        return plan

    def create_prediction_records(
        self,
        plan: OptimizationPlanOutput,
    ) -> list[PredictionRecord]:
        records: list[PredictionRecord] = []
        sel = plan.selected_candidate
        records.append(PredictionRecord(
            optimization_id=plan.optimization_id,
            candidate_id=sel.candidate_id,
            predicted_quality=sel.estimated_quality,
            predicted_reliability=sel.estimated_reliability,
            predicted_cost=round(sel.cost_breakdown.total, 6),
            predicted_latency_ms=sel.estimated_latency_ms,
            evidence_confidence=sel.evidence_confidence,
        ))

        for alt in plan.alternatives:
            cand_id = alt.candidate_id
            records.append(PredictionRecord(
                optimization_id=plan.optimization_id,
                candidate_id=cand_id,
                predicted_quality=alt.quality_score if alt.quality_score else None,
                predicted_reliability=alt.reliability_score if alt.reliability_score else None,
                predicted_cost=None,
                predicted_latency_ms=None,
                evidence_confidence=None,
            ))
        return records

    def _compute_budget_limits(
        self,
        selected: ExecutionConfigCandidate,
        constraints: OptimizationConstraints,
        task_profile: TaskProfile,
    ) -> BudgetExecutionLimits:
        total_cost = selected.cost_breakdown.total
        budget = constraints.max_budget

        if budget is not None:
            authorized = min(budget, total_cost * 2.0)
        else:
            authorized = total_cost * 2.0
        authorized = round(max(authorized, total_cost * 1.2), 6)

        complexity = 0.5
        cscore = None
        if hasattr(task_profile, "complexity") and task_profile.complexity is not None:
            cscore = task_profile.complexity
        elif hasattr(task_profile, "complexity_score") and task_profile.complexity_score is not None:
            cscore = task_profile.complexity_score

        if cscore is not None:
            if hasattr(cscore, "score"):
                complexity = float(cscore.score)
            elif hasattr(cscore, "composite"):
                complexity = float(cscore.composite)
            else:
                try:
                    complexity = float(cscore)
                except (ValueError, TypeError):
                    pass

        if complexity < 0.3:
            max_calls = 10
        elif complexity < 0.6:
            max_calls = 25
        else:
            max_calls = 50

        max_retries = constraints.max_retries if constraints.max_retries is not None else 3
        max_parallel = constraints.max_parallel_subtasks if constraints.max_parallel_subtasks is not None else 4
        max_env_runtime = (
            constraints.max_environment_runtime_ms
            if constraints.max_environment_runtime_ms is not None
            else 300_000
        )
        max_verif_cost = (
            constraints.max_verification_cost
            if constraints.max_verification_cost is not None
            else round(selected.cost_breakdown.verification_cost * 2.0, 6)
        )
        max_esc_cost = (
            constraints.max_escalation_cost
            if constraints.max_escalation_cost is not None
            else round(selected.cost_breakdown.recovery_cost * 1.5, 6)
        )

        return BudgetExecutionLimits(
            max_model_calls=max_calls,
            max_retries=max_retries,
            max_parallel_subtasks=max_parallel,
            max_environment_runtime_ms=max_env_runtime,
            max_verification_cost=max_verif_cost,
            max_escalation_cost=max_esc_cost,
            total_authorized_cost=authorized,
        )