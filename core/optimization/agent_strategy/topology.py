"""
Phase C11.4: Agent Topology Selector Component

Determines optimal agent topologies (single agent, sequential pipeline,
parallel multi-agent, committee ensemble, specialist decomposition)
based on task complexity, risk, and domain context.
"""

from schemas.domain.agent_strategy import (
    AgentTopologyType,
    AgentRoleConfig,
    TopologyConfig,
)
from schemas.domain.task_intelligence import TaskProfile, TaskComplexityLevel, RiskLevel


class TopologySelector:
    """Evaluates task profiles and constructs topology configurations."""

    def select_topology(self, profile: TaskProfile) -> TopologyConfig:
        comp_level = profile.complexity.level
        risk_level = profile.risk.overall_level
        has_dependencies = len(profile.dependencies.nodes) > 1

        # 1. Pipeline Sequential for multi-step task graphs
        if has_dependencies:
            roles = [
                AgentRoleConfig(
                    role_name=f"step_executor_{node.node_id}",
                    description=f"Executes pipeline step: {node.name}",
                )
                for node in profile.dependencies.nodes
            ]
            return TopologyConfig(
                topology_type=AgentTopologyType.PIPELINE_SEQUENTIAL,
                max_sub_agents=min(len(roles), 5),
                roles=roles,
                delegation_rules={"execution_order": profile.dependencies.execution_order},
            )

        # 2. Specialist Decomposition for Extreme/Very High Complexity
        if comp_level in (TaskComplexityLevel.EXTREME, TaskComplexityLevel.VERY_HIGH):
            roles = [
                AgentRoleConfig(
                    role_name="decomposer",
                    description="Decomposes high-complexity task into specialized sub-tasks",
                ),
                AgentRoleConfig(
                    role_name="domain_specialist",
                    description=f"Specialist for domain {profile.classification.primary_domain.value}",
                ),
                AgentRoleConfig(
                    role_name="synthesizer",
                    description="Synthesizes specialist outputs into unified response",
                ),
            ]
            return TopologyConfig(
                topology_type=AgentTopologyType.SPECIALIST_DECOMPOSITION,
                max_sub_agents=3,
                roles=roles,
                delegation_rules={"pattern": "map_reduce"},
            )

        # 3. Committee Ensemble for Critical / High Risk Tasks
        if risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH):
            roles = [
                AgentRoleConfig(
                    role_name="primary_generator",
                    description="Generates initial task output candidate",
                ),
                AgentRoleConfig(
                    role_name="safety_verifier",
                    description="Audits candidate for security, compliance, and operational risks",
                ),
                AgentRoleConfig(
                    role_name="quality_critic",
                    description="Evaluates output completeness and correctness",
                ),
            ]
            return TopologyConfig(
                topology_type=AgentTopologyType.COMMITTEE_ENSEMBLE,
                max_sub_agents=3,
                roles=roles,
                delegation_rules={"consensus": "unanimous_approval"},
            )

        # 4. Multi-Agent Parallel for High Complexity + Moderate Risk
        if comp_level == TaskComplexityLevel.HIGH:
            roles = [
                AgentRoleConfig(role_name="worker_1", description="Parallel output candidate generator A"),
                AgentRoleConfig(role_name="worker_2", description="Parallel output candidate generator B"),
            ]
            return TopologyConfig(
                topology_type=AgentTopologyType.MULTI_AGENT_PARALLEL,
                max_sub_agents=2,
                roles=roles,
                delegation_rules={"pattern": "scatter_gather"},
            )

        # 5. Default Single Agent for Trivial / Low / Medium Complexity
        return TopologyConfig(
            topology_type=AgentTopologyType.SINGLE_AGENT,
            max_sub_agents=1,
            roles=[AgentRoleConfig(role_name="primary_agent", description="Executes task end-to-end")],
            delegation_rules={},
        )