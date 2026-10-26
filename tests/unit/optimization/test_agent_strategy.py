"""
Unit tests for C11.4 Agent & Strategy Optimizer
Verifies topology selection, amplification optimization, tool configuration,
context budget compilation, overhead multiplier calculation, and ORM persistence.
"""

import pytest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from core.storage.database import Base
from core.storage.models.optimization_c11 import StrategyDefinitionModel, StrategyVersionModel
from schemas.domain.task_intelligence import (
    TaskProfile,
    TaskClassification,
    TaskComplexityScore,
    TaskRiskProfile,
    TaskConstraintSet,
    TaskDependencyGraph,
    TaskDependencyNode,
    TaskDomain,
    TaskIntent,
    TaskComplexityLevel,
    RiskLevel,
    OptimizationGoal,
)
from schemas.domain.agent_strategy import (
    AgentTopologyType,
    AmplificationStrategyType,
    AgentStrategyOptimizationRequest,
)
from core.optimization.agent_strategy import (
    AgentStrategyOptimizer,
    TopologySelector,
    AmplificationOptimizer,
    ContextToolConfigurator,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"dsrt": None})

    tables = [
        StrategyDefinitionModel.__table__,
        StrategyVersionModel.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)

    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def sample_task_profile():
    return TaskProfile(
        profile_id="tp_agent_1",
        task_id="task_agent_1",
        organization_id="org_agent",
        classification=TaskClassification(
            primary_domain=TaskDomain.SOFTWARE_ENGINEERING,
            primary_intent=TaskIntent.CODE_GENERATION,
        ),
        complexity=TaskComplexityScore(
            score=0.4,
            level=TaskComplexityLevel.MEDIUM,
        ),
        risk=TaskRiskProfile(
            overall_level=RiskLevel.LOW,
            score=0.1,
        ),
        constraints=TaskConstraintSet(max_budget_usd=0.05),
        dependencies=TaskDependencyGraph(),
    )


@pytest.fixture
def optimizer():
    return AgentStrategyOptimizer()


class TestTopologySelector:
    def test_single_agent_for_medium_complexity(self, sample_task_profile):
        selector = TopologySelector()
        top = selector.select_topology(sample_task_profile)
        assert top.topology_type == AgentTopologyType.SINGLE_AGENT
        assert top.max_sub_agents == 1

    def test_pipeline_sequential_for_dependencies(self, sample_task_profile):
        selector = TopologySelector()
        graph = TaskDependencyGraph(
            nodes=[
                TaskDependencyNode(node_id="s1", name="Step 1"),
                TaskDependencyNode(node_id="s2", name="Step 2", prerequisites=["s1"]),
            ],
            execution_order=["s1", "s2"],
        )
        dep_profile = sample_task_profile.model_copy(update={"dependencies": graph})
        top = selector.select_topology(dep_profile)
        assert top.topology_type == AgentTopologyType.PIPELINE_SEQUENTIAL
        assert top.max_sub_agents == 2

    def test_committee_ensemble_for_critical_risk(self, sample_task_profile):
        selector = TopologySelector()
        crit_profile = sample_task_profile.model_copy(
            update={"risk": TaskRiskProfile(overall_level=RiskLevel.CRITICAL, score=0.9)}
        )
        top = selector.select_topology(crit_profile)
        assert top.topology_type == AgentTopologyType.COMMITTEE_ENSEMBLE
        assert top.max_sub_agents == 3


class TestAmplificationOptimizer:
    def test_direct_strategy_for_minimize_cost(self, sample_task_profile):
        opt = AmplificationOptimizer()
        strat = opt.optimize_strategy(sample_task_profile, goal=OptimizationGoal.MINIMIZE_COST)
        assert strat.strategy_type == AmplificationStrategyType.DIRECT
        assert strat.sample_count == 1

    def test_step_by_step_verification_for_high_complexity_code(self, sample_task_profile):
        opt = AmplificationOptimizer()
        high_comp_profile = sample_task_profile.model_copy(
            update={"complexity": TaskComplexityScore(score=0.8, level=TaskComplexityLevel.HIGH)}
        )
        strat = opt.optimize_strategy(high_comp_profile, goal=OptimizationGoal.BALANCED)
        assert strat.strategy_type == AmplificationStrategyType.STEP_BY_STEP_VERIFICATION

    def test_calculate_overhead_multiplier(self):
        opt = AmplificationOptimizer()
        from schemas.domain.agent_strategy import StrategyConfig
        cfg = StrategyConfig(strategy_type=AmplificationStrategyType.SELF_CONSISTENCY, sample_count=3)
        mult = opt.calculate_overhead_multiplier(cfg, num_agents=2)
        # 2 agents * 3 samples = 6.0x
        assert mult == 6.0


class TestAgentStrategyOptimizer:
    def test_optimize_agent_strategy_end_to_end(self, optimizer, sample_task_profile):
        req = AgentStrategyOptimizationRequest(
            request_id="req_opt_1",
            organization_id="org_agent",
            task_profile=sample_task_profile,
            target_model_id="gpt-4o",
            optimization_goal=OptimizationGoal.BALANCED,
        )
        plan = optimizer.optimize_agent_strategy(req)
        assert plan.target_model_id == "gpt-4o"
        assert plan.topology.topology_type == AgentTopologyType.SINGLE_AGENT
        assert plan.estimated_overhead_multiplier >= 1.0

    def test_optimize_agent_strategy_persists_to_db(self, optimizer, sample_task_profile, db_session):
        req = AgentStrategyOptimizationRequest(
            request_id="req_opt_db",
            organization_id="org_agent",
            task_profile=sample_task_profile,
            target_model_id="claude-3-5-sonnet",
            optimization_goal=OptimizationGoal.MAXIMIZE_QUALITY,
        )
        plan = optimizer.optimize_agent_strategy(req, session=db_session)

        stored_def = db_session.query(StrategyDefinitionModel).filter_by(id=plan.plan_id).first()
        assert stored_def is not None
        assert stored_def.topology_type == plan.topology.topology_type.value

        stored_ver = db_session.query(StrategyVersionModel).filter_by(strategy_id=plan.plan_id).first()
        assert stored_ver is not None
        assert stored_ver.version_number == 1