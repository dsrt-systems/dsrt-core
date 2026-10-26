"""
Main entry point for C11.7 Verification Optimizer.

Coordinates planning, cascade ordering, economic evaluation, and DB persistence.
"""

from typing import Optional
from sqlalchemy.orm import Session

from schemas.domain.verification_optimization import (
    VerificationOptimizationRequest,
    VerificationOptimizationPlan,
    VerificationPipelineConfig,
    VerificationStrategyType,
)
from core.optimization.verification.planner import VerificationPlanner
from core.optimization.verification.cascade import VerificationCascadeEngine
from core.optimization.verification.evaluator import VerificationEvaluator
from core.storage.models.optimization_c11 import VerificationPipelineModel


class VerificationOptimizer:
    """Service facade for generating, optimizing, and persisting verification plans."""

    def __init__(
        self,
        db_session: Optional[Session] = None,
        planner: Optional[VerificationPlanner] = None,
    ):
        self.db_session = db_session
        self.planner = planner or VerificationPlanner()

    def optimize_verification(
        self, request: VerificationOptimizationRequest
    ) -> VerificationOptimizationPlan:
        """
        Generates an optimized verification cascade plan tailored to task risk, complexity,
        and economic constraints.
        """
        # 1. Determine strategy type
        strategy_type = self.planner.select_strategy_type(
            complexity_score=request.complexity_score,
            risk_level=request.risk_level,
        )

        # 2. Extract baseline tiers and instantiate steps
        baseline_tiers = self.planner.get_tiers_for_strategy(strategy_type)
        candidate_steps = self.planner.create_candidate_steps(baseline_tiers)

        # Calculate baseline cost for exhaustive reference comparison
        exhaustive_steps = self.planner.create_candidate_steps(
            self.planner.get_tiers_for_strategy(VerificationStrategyType.EXHAUSTIVE)
        )
        baseline_exhaustive_cost = VerificationEvaluator.calculate_pipeline_cost(exhaustive_steps)

        # 3. Adapt steps to economic / latency constraints
        adapted_steps, pruned = self.planner.adapt_steps_to_constraints(candidate_steps, request)
        if pruned:
            strategy_type = VerificationStrategyType.ADAPTIVE

        # 4. Construct optimized fast-failing cascade sequence
        cascade_steps = VerificationCascadeEngine.optimize_cascade_sequence(adapted_steps)

        # 5. Evaluate metrics
        total_cost = VerificationEvaluator.calculate_pipeline_cost(cascade_steps)
        total_latency = VerificationEvaluator.calculate_pipeline_latency(cascade_steps)
        expected_confidence = VerificationEvaluator.calculate_expected_confidence(cascade_steps)
        savings_ratio = VerificationEvaluator.calculate_cost_savings(total_cost, baseline_exhaustive_cost)

        # 6. Assemble response objects
        pipeline_config = VerificationPipelineConfig(
            strategy_type=strategy_type,
            steps=cascade_steps,
            total_estimated_cost=total_cost,
            total_estimated_latency_sec=total_latency,
            early_exit_on_failure=True,
        )

        active_tiers = [s.tier for s in cascade_steps]

        plan = VerificationOptimizationPlan(
            task_id=request.task_id,
            selected_strategy=strategy_type,
            pipeline=pipeline_config,
            tier_allocation=active_tiers,
            expected_confidence=expected_confidence,
            estimated_cost=total_cost,
            estimated_latency_sec=total_latency,
            cost_savings_ratio=savings_ratio,
        )

        # 7. Persist to DB if session provided
        if self.db_session is not None:
            self._persist_plan(plan)

        return plan

    def _persist_plan(self, plan: VerificationOptimizationPlan) -> None:
        """Persists the generated pipeline plan to the database."""
        steps_dict = [step.model_dump() for step in plan.pipeline.steps]
        db_model = VerificationPipelineModel(
            pipeline_id=plan.pipeline.pipeline_id,
            task_id=plan.task_id,
            strategy_type=plan.selected_strategy.value,
            steps_json=steps_dict,
            total_cost=plan.estimated_cost,
            total_latency_sec=plan.estimated_latency_sec,
            expected_confidence=plan.expected_confidence,
            early_exit_on_failure=plan.pipeline.early_exit_on_failure,
        )
        self.db_session.add(db_model)
        self.db_session.commit()

    def get_pipeline(self, pipeline_id: str) -> Optional[VerificationPipelineModel]:
        """Retrieves a persisted pipeline by pipeline_id."""
        if self.db_session is None:
            return None
        return (
            self.db_session.query(VerificationPipelineModel)
            .filter(VerificationPipelineModel.pipeline_id == pipeline_id)
            .first()
        )