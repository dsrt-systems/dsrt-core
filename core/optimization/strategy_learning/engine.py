"""
Main entry point for C11.8 Strategy Learning Engine.

Coordinates reward computation, online multi-armed bandit policy updating,
regret calculation, and persistence.
"""

from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from schemas.domain.strategy_learning import (
    BanditAlgorithm,
    StrategyArmState,
    StrategyFeedbackRequest,
    PolicyUpdateResult,
    LearningEngineMetrics,
)
from core.optimization.strategy_learning.reward import RewardCalculator
from core.optimization.strategy_learning.bandit import MultiArmedBanditPolicy
from core.storage.models.optimization_c11 import (
    StrategyArmStateModel,
    LearningObservationModel,
)


class StrategyLearningEngine:
    """Service facade for adaptive strategy learning and policy optimisation."""

    def __init__(
        self,
        db_session: Optional[Session] = None,
        algorithm: BanditAlgorithm = BanditAlgorithm.THOMPSON_SAMPLING,
    ):
        self.db_session = db_session
        self.bandit_policy = MultiArmedBanditPolicy(algorithm=algorithm)
        self.in_memory_arms: Dict[str, StrategyArmState] = {}
        self.cumulative_regret: float = 0.0
        self.total_observations: int = 0

    def register_arm(self, arm_id: str, strategy_name: str) -> StrategyArmState:
        """Registers a new strategy arm in the learning engine state."""
        if arm_id not in self.in_memory_arms:
            arm = StrategyArmState(arm_id=arm_id, strategy_name=strategy_name)
            self.in_memory_arms[arm_id] = arm
            if self.db_session is not None:
                self._persist_arm_state(arm)
        return self.in_memory_arms[arm_id]

    def select_strategy(self) -> Optional[StrategyArmState]:
        """Selects the best strategy arm for execution under current policy."""
        self._sync_arms_from_db()
        return self.bandit_policy.select_best_arm(self.in_memory_arms)

    def process_feedback(
        self, feedback: StrategyFeedbackRequest
    ) -> PolicyUpdateResult:
        """
        Processes execution outcome feedback:
        1. Computes unified scalar reward signal.
        2. Retrieves or registers strategy arm.
        3. Updates multi-armed bandit state parameters.
        4. Calculates cumulative regret.
        5. Persists update result to storage.
        """
        self._sync_arms_from_db()

        # 1. Compute unified scalar reward
        reward_signal = RewardCalculator.compute_reward(feedback)

        # 2. Retrieve or auto-register arm
        if feedback.strategy_id not in self.in_memory_arms:
            self.register_arm(feedback.strategy_id, f"Strategy-{feedback.strategy_id}")

        arm = self.in_memory_arms[feedback.strategy_id]

        # Determine optimal arm mean before updating for regret calculation
        best_mean_before = max(
            (a.mean_reward for a in self.in_memory_arms.values()), default=0.5
        )

        # 3. Update arm state
        result = self.bandit_policy.update_arm_state(
            arm=arm,
            scalar_reward=reward_signal.scalar_reward,
            best_mean_across_all=best_mean_before,
        )

        # 4. Update cumulative regret metric
        inst_regret = max(0.0, best_mean_before - reward_signal.scalar_reward)
        self.cumulative_regret += inst_regret
        self.total_observations += 1

        # 5. Persist observation & updated arm state
        if self.db_session is not None:
            self._persist_observation(reward_signal)
            self._persist_arm_state(arm)

        return result

    def get_metrics(self) -> LearningEngineMetrics:
        """Returns aggregate learning engine metrics and active strategy arm states."""
        self._sync_arms_from_db()
        arms_list = list(self.in_memory_arms.values())

        best_arm_id = None
        if arms_list:
            best_arm = max(arms_list, key=lambda a: a.mean_reward)
            best_arm_id = best_arm.arm_id

        return LearningEngineMetrics(
            total_observations=self.total_observations,
            best_strategy_id=best_arm_id,
            cumulative_regret=round(self.cumulative_regret, 4),
            exploration_rate=round(self.bandit_policy.epsilon, 4),
            arms=arms_list,
        )

    def _sync_arms_from_db(self) -> None:
        """Loads strategy arm states from DB into memory if session is available."""
        if self.db_session is None:
            return

        db_models = self.db_session.query(StrategyArmStateModel).all()
        for db_m in db_models:
            self.in_memory_arms[db_m.arm_id] = StrategyArmState(
                arm_id=db_m.arm_id,
                strategy_name=db_m.strategy_name,
                pull_count=db_m.pull_count,
                total_reward=db_m.total_reward,
                mean_reward=db_m.mean_reward,
                alpha=db_m.alpha,
                beta=db_m.beta,
                ucb_score=db_m.ucb_score,
                last_updated=db_m.last_updated,
            )

    def _persist_arm_state(self, arm: StrategyArmState) -> None:
        """Upserts StrategyArmStateModel in DB."""
        if self.db_session is None:
            return

        db_model = (
            self.db_session.query(StrategyArmStateModel)
            .filter(StrategyArmStateModel.arm_id == arm.arm_id)
            .first()
        )
        if db_model is None:
            db_model = StrategyArmStateModel(
                arm_id=arm.arm_id,
                strategy_name=arm.strategy_name,
                pull_count=arm.pull_count,
                total_reward=arm.total_reward,
                mean_reward=arm.mean_reward,
                alpha=arm.alpha,
                beta=arm.beta,
                ucb_score=arm.ucb_score,
            )
            self.db_session.add(db_model)
        else:
            db_model.pull_count = arm.pull_count
            db_model.total_reward = arm.total_reward
            db_model.mean_reward = arm.mean_reward
            db_model.alpha = arm.alpha
            db_model.beta = arm.beta
            db_model.ucb_score = arm.ucb_score

        self.db_session.commit()

    def _persist_observation(self, reward_signal) -> None:
        """Persists LearningObservationModel in DB."""
        if self.db_session is None:
            return

        db_obs = LearningObservationModel(
            observation_id=reward_signal.observation_id,
            strategy_id=reward_signal.strategy_id,
            task_id=reward_signal.task_id,
            quality_score=reward_signal.quality_score,
            cost_usd=reward_signal.cost_usd,
            latency_ms=reward_signal.latency_ms,
            scalar_reward=reward_signal.scalar_reward,
        )
        self.db_session.add(db_obs)
        self.db_session.commit()