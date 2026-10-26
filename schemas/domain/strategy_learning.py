"""
Domain schemas for C11.8 Strategy Learning Engine.

Defines schemas for observation logs, multi-armed bandit arm states,
reward signal computation, policy update results, and learning metrics.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class BanditAlgorithm(str, Enum):
    """Supported multi-armed bandit algorithm strategies."""
    THOMPSON_SAMPLING = "thompson_sampling"
    UPPER_CONFIDENCE_BOUND = "ucb1"
    EPSILON_GREEDY = "epsilon_greedy"


class RewardSignal(BaseModel):
    """Calculated scalar reward and decomposed component metrics."""

    observation_id: str = Field(default_factory=lambda: f"obs-{uuid4().hex[:8]}")
    strategy_id: str = Field(..., description="ID of the strategy arm being evaluated")
    task_id: str = Field(..., description="Associated task identifier")
    quality_score: float = Field(..., ge=0.0, le=1.0, description="Observed quality score")
    cost_usd: float = Field(..., ge=0.0, description="Observed USD cost")
    latency_ms: float = Field(..., ge=0.0, description="Observed execution latency in ms")
    normalized_cost_penalty: float = Field(..., ge=0.0, le=1.0, description="Normalized cost penalty")
    normalized_latency_penalty: float = Field(..., ge=0.0, le=1.0, description="Normalized latency penalty")
    scalar_reward: float = Field(..., ge=0.0, le=1.0, description="Unified scalar reward score [0.0, 1.0]")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StrategyArmState(BaseModel):
    """State of a strategy arm within the learning engine."""

    arm_id: str = Field(..., description="Unique strategy arm identifier")
    strategy_name: str = Field(..., description="Descriptive strategy name")
    pull_count: int = Field(default=0, ge=0, description="Total selection/execution count")
    total_reward: float = Field(default=0.0, ge=0.0, description="Cumulative scalar reward score")
    mean_reward: float = Field(default=0.5, ge=0.0, le=1.0, description="Empirical mean reward")

    # Thompson Sampling Beta Prior parameters (Beta(alpha, beta))
    alpha: float = Field(default=1.0, ge=0.1, description="Beta distribution shape parameter alpha (successes + prior)")
    beta: float = Field(default=1.0, ge=0.1, description="Beta distribution shape parameter beta (failures + prior)")

    # UCB metrics
    ucb_score: float = Field(default=1.0, ge=0.0, description="Upper Confidence Bound score value")
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StrategyFeedbackRequest(BaseModel):
    """Input payload recording an actual task execution outcome for strategy learning."""

    task_id: str = Field(..., description="Task identifier")
    strategy_id: str = Field(..., description="Strategy arm ID used for execution")
    quality_score: float = Field(..., ge=0.0, le=1.0, description="Achieved output quality score")
    cost_usd: float = Field(..., ge=0.0, description="Actual execution cost in USD")
    latency_ms: float = Field(..., ge=0.0, description="Actual latency in milliseconds")
    target_quality: float = Field(default=0.85, ge=0.0, le=1.0, description="Target quality benchmark")
    max_budget_cost: Optional[float] = Field(default=None, ge=0.0, description="Maximum allocated budget")
    max_allowed_latency_ms: Optional[float] = Field(default=None, ge=0.0, description="Maximum latency limit")


class PolicyUpdateResult(BaseModel):
    """Output summary following a strategy learning policy update."""

    strategy_id: str = Field(..., description="Strategy arm updated")
    previous_mean_reward: float = Field(..., ge=0.0, le=1.0)
    updated_mean_reward: float = Field(..., ge=0.0, le=1.0)
    pull_count: int = Field(..., ge=1)
    scalar_reward: float = Field(..., ge=0.0, le=1.0)
    updated_alpha: float = Field(..., ge=0.1)
    updated_beta: float = Field(..., ge=0.1)
    is_best_arm: bool = Field(default=False, description="Whether this arm currently holds the highest mean reward")


class LearningEngineMetrics(BaseModel):
    """Aggregated state and regret metrics across all strategy arms."""

    total_observations: int = Field(..., ge=0, description="Total feedback observations processed")
    best_strategy_id: Optional[str] = Field(default=None, description="Currently optimal strategy arm ID")
    cumulative_regret: float = Field(default=0.0, ge=0.0, description="Estimated cumulative regret")
    exploration_rate: float = Field(default=0.1, ge=0.0, le=1.0, description="Current exploration sampling rate")
    arms: List[StrategyArmState] = Field(default_factory=list, description="All active strategy arms")