"""
Unit tests for C5.4 Planner and PlanValidator.
"""

from __future__ import annotations

import pytest

from schemas.domain.orchestration import PlanConstraints, PlanDependency, PlanNode
from core.orchestration.planner.validator import PlanValidator


class TestPlanValidator:
    @pytest.fixture
    def validator(self):
        return PlanValidator(
            registered_capabilities={"web_search", "data_analysis", "report_gen"},
            registered_agents={
                "research_agent": {"web_search", "report_gen"},
                "data_agent": {"data_analysis"},
            },
        )

    def test_valid_plan(self, validator):
        nodes = [
            PlanNode(node_key="research", name="Research", node_type="AGENT_TASK",
                     required_capabilities=["web_search"]),
            PlanNode(node_key="verify", name="Verify", node_type="VERIFICATION",
                     depends_on=["research"]),
        ]
        deps = [
            PlanDependency(source_node_key="research", target_node_key="verify"),
        ]
        result = validator.validate(nodes, deps, PlanConstraints())
        assert result.valid
        assert result.graph is not None

    def test_empty_plan_invalid(self, validator):
        result = validator.validate([], [], PlanConstraints())
        assert not result.valid

    def test_duplicate_node_keys(self, validator):
        nodes = [
            PlanNode(node_key="dup", name="A", node_type="AGENT_TASK"),
            PlanNode(node_key="dup", name="B", node_type="AGENT_TASK"),
        ]
        result = validator.validate(nodes, [], PlanConstraints())
        assert not result.valid
        assert any("Duplicate" in e for e in result.errors)

    def test_cyclic_plan_invalid(self, validator):
        nodes = [
            PlanNode(node_key="a", name="A", node_type="AGENT_TASK"),
            PlanNode(node_key="b", name="B", node_type="AGENT_TASK"),
        ]
        deps = [
            PlanDependency(source_node_key="a", target_node_key="b"),
            PlanDependency(source_node_key="b", target_node_key="a"),
        ]
        result = validator.validate(nodes, deps, PlanConstraints())
        assert not result.valid

    def test_missing_capability(self, validator):
        nodes = [
            PlanNode(node_key="task", name="T", node_type="AGENT_TASK",
                     required_capabilities=["nonexistent_cap"]),
        ]
        result = validator.validate(nodes, [], PlanConstraints())
        assert not result.valid
        assert any("nonexistent_cap" in e for e in result.errors)

    def test_max_nodes_exceeded(self, validator):
        nodes = [
            PlanNode(node_key=f"n{i}", name=f"N{i}", node_type="AGENT_TASK")
            for i in range(10)
        ]
        constraints = PlanConstraints(max_nodes=5)
        result = validator.validate(nodes, [], constraints)
        assert not result.valid

    def test_dangling_dependency_reference(self, validator):
        nodes = [
            PlanNode(node_key="a", name="A", node_type="AGENT_TASK"),
        ]
        deps = [
            PlanDependency(source_node_key="a", target_node_key="nonexistent"),
        ]
        result = validator.validate(nodes, deps, PlanConstraints())
        assert not result.valid

    def test_self_dependency(self, validator):
        nodes = [
            PlanNode(node_key="a", name="A", node_type="AGENT_TASK"),
        ]
        deps = [
            PlanDependency(source_node_key="a", target_node_key="a"),
        ]
        result = validator.validate(nodes, deps, PlanConstraints())
        assert not result.valid