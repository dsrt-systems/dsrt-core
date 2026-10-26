"""
Unit tests for C11.8 Strategy Learning Engine.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

# SQLite compilation workaround for PostgreSQL JSONB
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"

from core.storage.database import Base
# Import ORM models to register metadata prior to create_all
from core.storage.models.optimization_c11 import (
    StrategyArmStateModel,
    LearningObservationModel,
)

from schemas.domain.strategy_learning import (
    BanditAlgorithm,
    StrategyFeedbackRequest,
    StrategyArmState,
)
from core.optimization.strategy_learning.reward import RewardCalculator
from core.optimization.strategy_learning.bandit import MultiArmedBanditPolicy
from core.optimization.strategy_learning.engine import StrategyLearningEngine


@pytest.fixture
def db_session():
    """Sets up an in-memory SQLite database session with translated schema."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"dsrt": None})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_reward_calculator_bounds():
    """Verifies reward computation is bounded strictly within [0.0, 1.0]."""
    feedback_high = StrategyFeedbackRequest(
        task_id="t1",
        strategy_id="strat-a",
        quality_score=0.95,
        cost_usd=0.01,
        latency_ms=100.0,
        max_budget_cost=0.10,
        max_allowed_latency_ms=2000.0,
    )
    signal_high = RewardCalculator.compute_reward(feedback_high)
    assert 0.0 <= signal_high.scalar_reward <= 1.0
    assert signal_high.scalar_reward >= 0.80

    feedback_poor = StrategyFeedbackRequest(
        task_id="t2",
        strategy_id="strat-b",
        quality_score=0.20,
        cost_usd=0.50,
        latency_ms=10000.0,
        max_budget_cost=0.10,
        max_allowed_latency_ms=2000.0,
    )
    signal_poor = RewardCalculator.compute_reward(feedback_poor)
    assert 0.0 <= signal_poor.scalar_reward <= 1.0
    assert signal_poor.scalar_reward < signal_high.scalar_reward


def test_thompson_sampling_arm_selection():
    """Verifies Thompson Sampling selects highest expected arm over repeated samples."""
    policy = MultiArmedBanditPolicy(algorithm=BanditAlgorithm.THOMPSON_SAMPLING)

    arm_poor = StrategyArmState(arm_id="arm-poor", strategy_name="Poor", alpha=1.0, beta=10.0)
    arm_strong = StrategyArmState(arm_id="arm-strong", strategy_name="Strong", alpha=10.0, beta=1.0)

    arms = {"arm-poor": arm_poor, "arm-strong": arm_strong}

    selections = [policy.select_best_arm(arms).arm_id for _ in range(50)]
    strong_count = selections.count("arm-strong")
    assert strong_count > 40  # Strong arm sampled predominantly


def test_ucb1_arm_selection():
    """Verifies UCB1 prioritizes unpulled arms then selects highest mean + variance bound."""
    policy = MultiArmedBanditPolicy(algorithm=BanditAlgorithm.UPPER_CONFIDENCE_BOUND)

    arm_unpulled = StrategyArmState(arm_id="unpulled", strategy_name="New", pull_count=0)
    arm_pulled = StrategyArmState(arm_id="pulled", strategy_name="Old", pull_count=5, mean_reward=0.7)

    arms = {"unpulled": arm_unpulled, "pulled": arm_pulled}
    selected = policy.select_best_arm(arms)
    assert selected.arm_id == "unpulled"


def test_strategy_learning_engine_feedback_loop(db_session):
    """Verifies full learning loop: feedback processing, arm parameter updating, and DB persistence."""
    engine = StrategyLearningEngine(db_session=db_session)
    engine.register_arm("strat-1", "Fast Strategy")
    engine.register_arm("strat-2", "Accurate Strategy")

    # Ingest multiple feedback outcomes favoring strat-2
    for i in range(5):
        engine.process_feedback(
            StrategyFeedbackRequest(
                task_id=f"task-loop-{i}",
                strategy_id="strat-1",
                quality_score=0.50,
                cost_usd=0.05,
                latency_ms=500.0,
            )
        )
        engine.process_feedback(
            StrategyFeedbackRequest(
                task_id=f"task-loop-{i}",
                strategy_id="strat-2",
                quality_score=0.95,
                cost_usd=0.02,
                latency_ms=300.0,
            )
        )

    metrics = engine.get_metrics()
    assert metrics.total_observations == 10
    assert metrics.best_strategy_id == "strat-2"
    assert len(metrics.arms) == 2

    # Verify database persistence of arm state and observations
    db_arms = db_session.query(StrategyArmStateModel).all()
    assert len(db_arms) == 2

    db_obs = db_session.query(LearningObservationModel).all()
    assert len(db_obs) == 10