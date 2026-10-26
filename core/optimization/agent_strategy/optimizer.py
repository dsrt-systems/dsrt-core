"""
Phase C11.4: Agent & Strategy Optimizer Main Service

Coordinates topology selection, amplification optimization, tool configuration,
context budget tuning, and persistence of optimization plans.
"""

import uuid
from typing import Optional
from sqlalchemy.orm import Session

from schemas.domain.agent_strategy import (
    AgentStrategyOptimizationRequest,
    AgentStrategyOptimizationPlan,
)
from core.optimization.agent_strategy.topology import TopologySelector
from core.optimization.agent_strategy.amplification import AmplificationOptimizer
from core.optimization.agent_strategy.context import ContextToolConfigurator
from core.storage.models.optimization_c11 import StrategyDefinitionModel, StrategyVersionModel


class AgentStrategyOptimizer:
    """Main orchestrator for agent topology and amplification strategy optimization."""

    def __init__(
        self,
        topology_selector: Optional[TopologySelector] = None,
        amplification_optimizer: Optional[AmplificationOptimizer] = None,
        context_configurator: Optional[ContextToolConfigurator] = None,
    ):
        self.topology_selector = topology_selector or TopologySelector()
        self.amplification_optimizer = amplification_optimizer or AmplificationOptimizer()
        self.context_configurator = context_configurator or ContextToolConfigurator()

    def optimize_agent_strategy(
        self,
        request: AgentStrategyOptimizationRequest,
        session: Optional[Session] = None,
    ) -> AgentStrategyOptimizationPlan:
        # 1. Determine Optimal Agent Topology
        topology = self.topology_selector.select_topology(request.task_profile)

        # 2. Determine Optimal Amplification Strategy
        strategy = self.amplification_optimizer.optimize_strategy(
            profile=request.task_profile,
            goal=request.optimization_goal,
        )

        # 3. Configure Tools & Context Budget
        tool_config = self.context_configurator.configure_tools(request.task_profile)
        context_config = self.context_configurator.configure_context(request.task_profile)

        # 4. Calculate Resource Multiplier
        overhead_multiplier = self.amplification_optimizer.calculate_overhead_multiplier(
            strategy=strategy,
            num_agents=topology.max_sub_agents,
        )

        plan_id = str(uuid.uuid4())
        explanation = (
            f"Recommended topology '{topology.topology_type.value}' with {topology.max_sub_agents} agent(s) "
            f"and amplification strategy '{strategy.strategy_type.value}' (overhead multiplier: {overhead_multiplier:.2f}x)."
        )

        plan = AgentStrategyOptimizationPlan(
            plan_id=plan_id,
            request_id=request.request_id,
            organization_id=request.organization_id,
            target_model_id=request.target_model_id,
            topology=topology,
            strategy=strategy,
            tool_config=tool_config,
            context_config=context_config,
            estimated_overhead_multiplier=overhead_multiplier,
            explanation=explanation,
        )

        # Persist Strategy Definition & Version if session provided
        if session is not None:
            strat_def = StrategyDefinitionModel(
                id=plan.plan_id,
                organization_id=plan.organization_id,
                strategy_name=f"strategy_{strategy.strategy_type.value}_{topology.topology_type.value}",
                strategy_type=strategy.strategy_type.value,
                topology_type=topology.topology_type.value,
                created_at=plan.created_at,
            )
            strat_def.set_config_data(plan.model_dump(mode="json"))
            session.add(strat_def)

            strat_ver = StrategyVersionModel(
                id=str(uuid.uuid4()),
                strategy_id=plan.plan_id,
                version_number=1,
                created_at=plan.created_at,
            )
            strat_ver.set_hyperparameters({
                "sample_count": strategy.sample_count,
                "temperature": strategy.temperature,
                "overhead_multiplier": overhead_multiplier,
            })
            session.add(strat_ver)
            session.commit()

        return plan