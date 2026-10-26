"""
Phase C11.4: Amplification Strategy Optimizer Component

Recommends amplification strategies (Direct, Majority Vote, Self-Consistency,
Reflection Refinement, Step-By-Step Verification) matching economic constraints.
"""

from schemas.domain.agent_strategy import (
    AmplificationStrategyType,
    StrategyConfig,
)
from schemas.domain.task_intelligence import (
    TaskProfile,
    TaskComplexityLevel,
    TaskIntent,
    OptimizationGoal,
)


class AmplificationOptimizer:
    """Optimizes amplification parameters based on goal, domain, and risk."""

    def optimize_strategy(
        self,
        profile: TaskProfile,
        goal: OptimizationGoal,
    ) -> StrategyConfig:
        comp_level = profile.complexity.level
        intent = profile.classification.primary_intent
        max_budget = profile.constraints.max_budget_usd or 0.10

        # Cost Minimization / Low Budget Force Direct Mode
        if goal == OptimizationGoal.MINIMIZE_COST or max_budget < 0.002:
            return StrategyConfig(
                strategy_type=AmplificationStrategyType.DIRECT,
                sample_count=1,
                temperature=0.1,
            )

        # Step-by-Step Verification for Reasoning, Code Gen, and Math
        if intent in (TaskIntent.CODE_GENERATION, TaskIntent.REASONING_INFERENCE, TaskIntent.STATISTICAL_ANALYSIS) and comp_level in (TaskComplexityLevel.HIGH, TaskComplexityLevel.VERY_HIGH, TaskComplexityLevel.EXTREME):
            return StrategyConfig(
                strategy_type=AmplificationStrategyType.STEP_BY_STEP_VERIFICATION,
                sample_count=1,
                max_refinement_rounds=2,
                temperature=0.1,
            )

        # Reflection Refinement for Refactoring, Bug Fixing, and Content
        if intent in (TaskIntent.REFACTORING, TaskIntent.BUG_FIXING, TaskIntent.ARCHITECTURE_DESIGN):
            return StrategyConfig(
                strategy_type=AmplificationStrategyType.REFLECTION_REFINEMENT,
                sample_count=1,
                max_refinement_rounds=2 if comp_level in (TaskComplexityLevel.HIGH, TaskComplexityLevel.VERY_HIGH, TaskComplexityLevel.EXTREME) else 1,
                temperature=0.2,
            )

        # Self-Consistency / Majority Vote for High Quality / High Reliability Target
        if goal in (OptimizationGoal.MAXIMIZE_QUALITY, OptimizationGoal.MAXIMIZE_RELIABILITY):
            samples = 3 if max_budget >= 0.01 else 2
            return StrategyConfig(
                strategy_type=AmplificationStrategyType.SELF_CONSISTENCY,
                sample_count=samples,
                consensus_threshold=0.66,
                temperature=0.5,
            )

        # Default Direct Execution
        return StrategyConfig(
            strategy_type=AmplificationStrategyType.DIRECT,
            sample_count=1,
            temperature=0.2,
        )

    def calculate_overhead_multiplier(self, strategy: StrategyConfig, num_agents: int) -> float:
        base_multiplier = float(num_agents)

        if strategy.strategy_type == AmplificationStrategyType.DIRECT:
            strat_mult = 1.0
        elif strategy.strategy_type in (AmplificationStrategyType.MAJORITY_VOTE, AmplificationStrategyType.SELF_CONSISTENCY):
            strat_mult = float(strategy.sample_count)
        elif strategy.strategy_type == AmplificationStrategyType.REFLECTION_REFINEMENT:
            strat_mult = 1.0 + (strategy.max_refinement_rounds * 1.2)
        elif strategy.strategy_type == AmplificationStrategyType.STEP_BY_STEP_VERIFICATION:
            strat_mult = 1.5 + (strategy.max_refinement_rounds * 1.0)
        else:
            strat_mult = 1.0

        return round(base_multiplier * strat_mult, 2)