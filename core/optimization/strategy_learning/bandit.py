"""
Multi-Armed Bandit module for C11.8 Strategy Learning Engine.

Implements Thompson Sampling and Upper Confidence Bound (UCB1) algorithms
for adaptive strategy exploration and exploitation.
"""

import math
import random
from typing import Dict, List, Optional, Tuple

from schemas.domain.strategy_learning import (
    BanditAlgorithm,
    StrategyArmState,
    PolicyUpdateResult,
)


class MultiArmedBanditPolicy:
    """Manages strategy selection algorithms and policy state updates."""

    def __init__(
        self,
        algorithm: BanditAlgorithm = BanditAlgorithm.THOMPSON_SAMPLING,
        c_ucb: float = 1.414,
        epsilon: float = 0.10,
    ):
        self.algorithm = algorithm
        self.c_ucb = c_ucb  # Exploration parameter for UCB1
        self.epsilon = epsilon  # Exploration probability for Epsilon-Greedy

    def select_best_arm(
        self, arms: Dict[str, StrategyArmState]
    ) -> Optional[StrategyArmState]:
        """
        Selects the optimal strategy arm according to the configured bandit policy.
        """
        if not arms:
            return None

        arm_list = list(arms.values())

        if self.algorithm == BanditAlgorithm.THOMPSON_SAMPLING:
            return self._select_thompson(arm_list)
        elif self.algorithm == BanditAlgorithm.UPPER_CONFIDENCE_BOUND:
            return self._select_ucb1(arm_list)
        elif self.algorithm == BanditAlgorithm.EPSILON_GREEDY:
            return self._select_epsilon_greedy(arm_list)
        else:
            return self._select_thompson(arm_list)

    def _select_thompson(self, arms: List[StrategyArmState]) -> StrategyArmState:
        """Selects arm via Beta-Binomial Thompson Sampling."""
        best_arm = None
        max_sample = -1.0

        for arm in arms:
            # Sample from Beta(alpha, beta) using random.betavariate
            sample = random.betavariate(max(0.1, arm.alpha), max(0.1, arm.beta))
            if sample > max_sample:
                max_sample = sample
                best_arm = arm

        return best_arm or arms[0]

    def _select_ucb1(self, arms: List[StrategyArmState]) -> StrategyArmState:
        """Selects arm using UCB1 algorithm."""
        total_pulls = sum(arm.pull_count for arm in arms)
        if total_pulls == 0:
            return random.choice(arms)

        # Unpulled arms have infinite priority
        unpulled = [arm for arm in arms if arm.pull_count == 0]
        if unpulled:
            return random.choice(unpulled)

        best_arm = None
        max_ucb = -1.0

        for arm in arms:
            variance_term = self.c_ucb * math.sqrt(
                math.log(total_pulls) / arm.pull_count
            )
            ucb_score = arm.mean_reward + variance_term
            arm.ucb_score = round(ucb_score, 4)
            if ucb_score > max_ucb:
                max_ucb = ucb_score
                best_arm = arm

        return best_arm or arms[0]

    def _select_epsilon_greedy(self, arms: List[StrategyArmState]) -> StrategyArmState:
        """Selects arm using Epsilon-Greedy strategy."""
        if random.random() < self.epsilon:
            # Explore randomly
            return random.choice(arms)
        # Exploit highest mean reward
        return max(arms, key=lambda a: a.mean_reward)

    def update_arm_state(
        self,
        arm: StrategyArmState,
        scalar_reward: float,
        best_mean_across_all: float = 0.0,
    ) -> PolicyUpdateResult:
        """
        Updates arm statistics and Thompson Beta parameters based on scalar reward feedback.
        """
        previous_mean = arm.mean_reward

        # Update pull count and cumulative reward
        arm.pull_count += 1
        arm.total_reward += scalar_reward
        arm.mean_reward = round(arm.total_reward / arm.pull_count, 4)

        # Update Beta parameters for Thompson Sampling
        # Treat scalar_reward as fraction of pseudo-success (scale factor = 2.0)
        arm.alpha += scalar_reward * 2.0
        arm.beta += (1.0 - scalar_reward) * 2.0

        is_best = arm.mean_reward >= best_mean_across_all

        return PolicyUpdateResult(
            strategy_id=arm.arm_id,
            previous_mean_reward=previous_mean,
            updated_mean_reward=arm.mean_reward,
            pull_count=arm.pull_count,
            scalar_reward=scalar_reward,
            updated_alpha=round(arm.alpha, 4),
            updated_beta=round(arm.beta, 4),
            is_best_arm=is_best,
        )