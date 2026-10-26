"""
Phase C11.4: Agent & Strategy Optimization Schemas

Defines domain schemas for agent topologies, amplification strategies,
tool usage policies, context compilation parameters, and optimization plans.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict

from schemas.domain.task_intelligence import TaskProfile, OptimizationGoal


class AgentTopologyType(str, Enum):
    SINGLE_AGENT = "single_agent"
    MULTI_AGENT_PARALLEL = "multi_agent_parallel"
    PIPELINE_SEQUENTIAL = "pipeline_sequential"
    COMMITTEE_ENSEMBLE = "committee_ensemble"
    SPECIALIST_DECOMPOSITION = "specialist_decomposition"


class AmplificationStrategyType(str, Enum):
    DIRECT = "direct"
    MAJORITY_VOTE = "majority_vote"
    SELF_CONSISTENCY = "self_consistency"
    REFLECTION_REFINEMENT = "reflection_refinement"
    STEP_BY_STEP_VERIFICATION = "step_by_step_verification"


class AgentRoleConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    role_name: str = Field(..., description="Role identifier (e.g., 'generator', 'reviewer', 'verifier')")
    description: str = Field("", description="Functional description of agent role")
    specialized_prompt_prefix: str = Field("", description="System prompt prefix for specialized persona")
    assigned_tools: List[str] = Field(default_factory=list, description="Tools available to this role")


class TopologyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    topology_type: AgentTopologyType = Field(AgentTopologyType.SINGLE_AGENT)
    max_sub_agents: int = Field(1, ge=1, le=10, description="Maximum sub-agents to instantiate")
    roles: List[AgentRoleConfig] = Field(default_factory=list, description="Roles in multi-agent configuration")
    delegation_rules: Dict[str, Any] = Field(default_factory=dict, description="Routing and handoff rules")


class StrategyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_type: AmplificationStrategyType = Field(AmplificationStrategyType.DIRECT)
    sample_count: int = Field(1, ge=1, le=10, description="Parallel candidate outputs for voting/consistency")
    consensus_threshold: float = Field(0.6, ge=0.5, le=1.0, description="Minimum consensus agreement ratio")
    max_refinement_rounds: int = Field(0, ge=0, le=5, description="Maximum critique-refine iteration loops")
    temperature: float = Field(0.2, ge=0.0, le=2.0, description="Model sampling temperature")
    system_prompt_overrides: Dict[str, str] = Field(default_factory=dict)


class ToolSelectionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    required_tools: List[str] = Field(default_factory=list)
    optional_tools: List[str] = Field(default_factory=list)
    max_tool_invocations: int = Field(10, ge=0, le=50)
    timeout_per_tool_ms: float = Field(5000.0, ge=100.0)


class ContextCompilationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_context_tokens: int = Field(4096, ge=512)
    pruning_strategy: str = Field("fifo", description="Pruning policy: fifo, relevance_summary, head_tail")
    enable_code_stripping: bool = Field(False)
    enable_retrieval_augmentation: bool = Field(False)


class AgentStrategyOptimizationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str = Field(..., description="Unique optimization request identifier")
    organization_id: str = Field(..., description="Tenant organization identifier")
    task_profile: TaskProfile
    target_model_id: str = Field(..., description="Model selected for execution")
    optimization_goal: OptimizationGoal = Field(OptimizationGoal.BALANCED)


class AgentStrategyOptimizationPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(..., description="Unique optimization plan identifier")
    request_id: str = Field(..., description="Associated request identifier")
    organization_id: str = Field(..., description="Tenant organization identifier")
    target_model_id: str = Field(..., description="Target execution model")
    topology: TopologyConfig
    strategy: StrategyConfig
    tool_config: ToolSelectionConfig
    context_config: ContextCompilationConfig
    estimated_overhead_multiplier: float = Field(1.0, ge=1.0, description="Resource/cost multiplier vs direct execution")
    explanation: str = Field("", description="Reasoning behind recommended strategy")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))