"""
Plan Validator (C5 §14).

Implements the complete deterministic validation pipeline for generated plans.
The planner proposes; the validator decides. This separation is critical —
the validator must NEVER depend on an LLM (C5 §15).

Validation pipeline (C5 §14):
  1. Schema validation
  2. Graph validation
  3. Dependency validation
  4. Capability validation
  5. Permission validation (deferred to execution)
  6. Resource validation
  7. Cycle detection (C5 §15)
  8. Policy validation
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.domain.enums import DependencyType, NodeType
from schemas.domain.orchestration import PlanConstraints, PlanDependency, PlanNode

from core.orchestration.graph.cycle_detection import CycleDetector
from core.orchestration.graph.graph import GraphEdge, GraphNode, TaskGraph
from core.orchestration.graph.validator import (
    GraphValidator,
    ValidationResult,
)


@dataclass
class PlanValidationResult:
    """Complete result of the plan validation pipeline (C5 §14)."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    graph: TaskGraph | None = None

    def merge(self, other: ValidationResult | PlanValidationResult) -> PlanValidationResult:
        """Merge another result into this one."""
        return PlanValidationResult(
            valid=self.valid and other.valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + getattr(other, "warnings", []),
            graph=self.graph,
        )


class PlanValidator:
    """Validates orchestration plans through the full C5 §14 pipeline.

    This is deterministic infrastructure. It must NOT depend on an LLM.
    """

    def __init__(
        self,
        registered_capabilities: set[str] | None = None,
        registered_agents: dict[str, set[str]] | None = None,
    ) -> None:
        """Initialize with optional registry data for capability/agent checks.

        Args:
            registered_capabilities: Set of capability slugs in the registry.
            registered_agents: Map of agent_slug -> set of capability slugs.
        """
        self._capabilities = registered_capabilities or set()
        self._agents = registered_agents or {}
        self._graph_validator = GraphValidator()

    def validate(
        self,
        nodes: list[PlanNode],
        dependencies: list[PlanDependency],
        constraints: PlanConstraints,
    ) -> PlanValidationResult:
        """Run the full C5 §14 validation pipeline.

        Returns a PlanValidationResult with the validated TaskGraph if valid.
        """
        result = PlanValidationResult(valid=True)

        # 1. Schema validation
        result = result.merge(self._validate_schema(nodes, dependencies))
        if not result.valid:
            return result

        # 2. Build TaskGraph for structural checks
        graph = self._build_graph(nodes, dependencies)

        # 3. Graph validation (C5.3 GraphValidator)
        graph_result = self._graph_validator.validate(graph)
        result = result.merge(graph_result)
        if not result.valid:
            return result

        # 4. Dependency validation
        result = result.merge(self._validate_dependencies(nodes, dependencies))

        # 5. Capability validation
        if self._capabilities:
            result = result.merge(self._validate_capabilities(nodes))

        # 6. Resource validation
        result = result.merge(self._validate_resources(nodes, constraints))

        # 7. Cycle detection (already covered by GraphValidator, but explicit)
        detector = CycleDetector(graph)
        if detector.has_cycle():
            result = PlanValidationResult(
                valid=False,
                errors=result.errors + [
                    f"Cycle detected: {detector.find_cycle_nodes()}"
                ],
                warnings=result.warnings,
            )
            return result

        # 8. Policy validation
        result = result.merge(self._validate_policy(nodes, constraints))

        if result.valid:
            result.graph = graph

        return result

    # ------------------------------------------------------------------
    # Pipeline Stages
    # ------------------------------------------------------------------

    def _validate_schema(
        self,
        nodes: list[PlanNode],
        dependencies: list[PlanDependency],
    ) -> PlanValidationResult:
        """Stage 1: Schema validation — required fields, types, uniqueness."""
        errors: list[str] = []
        warnings: list[str] = []

        if not nodes:
            errors.append("Plan must contain at least one node.")
            return PlanValidationResult(valid=False, errors=errors)

        # Check node key uniqueness
        keys = [n.node_key for n in nodes]
        if len(keys) != len(set(keys)):
            duplicates = [k for k in keys if keys.count(k) > 1]
            errors.append(f"Duplicate node keys: {sorted(set(duplicates))}")

        # Check node key format
        for node in nodes:
            if not node.node_key or not node.node_key.strip():
                errors.append("Node key must not be empty.")
            if len(node.node_key) > 120:
                errors.append(
                    f"Node key '{node.node_key}' exceeds 120 characters."
                )
            if not node.name:
                errors.append(f"Node '{node.node_key}' must have a name.")

        # Check dependency references and self-dependencies
        key_set = set(keys)
        for dep in dependencies:
            if dep.source_node_key not in key_set:
                errors.append(
                    f"Dependency source '{dep.source_node_key}' "
                    f"not found in nodes."
                )
            if dep.target_node_key not in key_set:
                errors.append(
                    f"Dependency target '{dep.target_node_key}' "
                    f"not found in nodes."
                )
            if dep.source_node_key == dep.target_node_key:
                errors.append(
                    f"Self-dependency detected: '{dep.source_node_key}' "
                    f"depends on itself."
                )

        return PlanValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_dependencies(
        self,
        nodes: list[PlanNode],
        dependencies: list[PlanDependency],
    ) -> PlanValidationResult:
        """Stage 3: Dependency validation — consistency between node.depends_on and edges."""
        errors: list[str] = []
        warnings: list[str] = []

        # Build edge set from explicit dependencies
        edge_set: set[tuple[str, str]] = set()
        for dep in dependencies:
            edge = (dep.source_node_key, dep.target_node_key)
            if edge in edge_set:
                warnings.append(
                    f"Duplicate dependency: {dep.source_node_key} "
                    f"-> {dep.target_node_key}"
                )
            edge_set.add(edge)

        # Check that node.depends_on matches explicit dependencies
        for node in nodes:
            for dep_key in node.depends_on:
                if (dep_key, node.node_key) not in edge_set:
                    warnings.append(
                        f"Node '{node.node_key}' declares dependency on "
                        f"'{dep_key}' but no explicit edge exists. "
                        f"Adding implicit HARD dependency."
                    )

        # Check for self-dependencies
        for dep in dependencies:
            if dep.source_node_key == dep.target_node_key:
                errors.append(
                    f"Self-dependency: '{dep.source_node_key}' depends on itself."
                )

        return PlanValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_capabilities(
        self,
        nodes: list[PlanNode],
    ) -> PlanValidationResult:
        """Stage 4: Capability validation — required capabilities exist in registry."""
        errors: list[str] = []
        warnings: list[str] = []

        for node in nodes:
            if node.node_type != NodeType.AGENT_TASK.value:
                continue

            for cap in node.required_capabilities:
                if cap not in self._capabilities:
                    errors.append(
                        f"Node '{node.node_key}' requires capability "
                        f"'{cap}' which is not registered."
                    )

            # Check if any agent can fulfill this node
            if node.required_capabilities and self._agents:
                eligible = self._find_eligible_agents(node.required_capabilities)
                if not eligible:
                    warnings.append(
                        f"Node '{node.node_key}' requires capabilities "
                        f"{node.required_capabilities} but no registered "
                        f"agent provides all of them."
                    )

        return PlanValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_resources(
        self,
        nodes: list[PlanNode],
        constraints: PlanConstraints,
    ) -> PlanValidationResult:
        """Stage 6: Resource validation — plan fits within constraints."""
        errors: list[str] = []
        warnings: list[str] = []

        if len(nodes) > constraints.max_nodes:
            errors.append(
                f"Plan has {len(nodes)} nodes but constraint "
                f"allows max {constraints.max_nodes}."
            )

        # Check for excessive parallelism
        graph = self._build_graph(nodes, [])
        roots = [
            k for k in graph.node_keys
            if not graph.get_dependencies(k)
        ]
        if len(roots) > constraints.max_parallel_nodes:
            warnings.append(
                f"Plan has {len(roots)} root nodes that could run in "
                f"parallel, but max_parallel_nodes is "
                f"{constraints.max_parallel_nodes}."
            )

        return PlanValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_policy(
        self,
        nodes: list[PlanNode],
        constraints: PlanConstraints,
    ) -> PlanValidationResult:
        """Stage 8: Policy validation — plan respects org policy."""
        errors: list[str] = []
        warnings: list[str] = []

        # Check delegation policy
        if not constraints.allow_delegation:
            delegation_nodes = [
                n for n in nodes
                if n.node_type == NodeType.AGENT_TASK.value
                and n.agent_slug is None
            ]
            if len(delegation_nodes) > 1:
                warnings.append(
                    "Delegation is disabled but multiple agent nodes "
                    "lack explicit agent assignment."
                )

        # Check approval requirements
        for action in constraints.require_approval_for:
            has_approval = any(
                n.node_type == NodeType.HUMAN_APPROVAL.value
                for n in nodes
            )
            if not has_approval:
                warnings.append(
                    f"Policy requires approval for '{action}' but "
                    f"no HUMAN_APPROVAL node exists in the plan."
                )

        return PlanValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_graph(
        self,
        nodes: list[PlanNode],
        dependencies: list[PlanDependency],
    ) -> TaskGraph:
        """Build a TaskGraph from plan nodes and dependencies."""
        graph = TaskGraph()

        for node in nodes:
            graph.add_node(GraphNode(
                key=node.node_key,
                node_type=node.node_type,
                agent_slug=node.agent_slug,
                required_capabilities=tuple(node.required_capabilities),
            ))

        for dep in dependencies:
            if dep.source_node_key in graph and dep.target_node_key in graph:
                graph.add_edge(GraphEdge(
                    source=dep.source_node_key,
                    target=dep.target_node_key,
                    dependency_type=dep.dependency_type,
                    condition=dep.condition,
                ))

        # Add implicit edges from node.depends_on
        edge_set = {
            (d.source_node_key, d.target_node_key) for d in dependencies
        }
        for node in nodes:
            for dep_key in node.depends_on:
                if (dep_key, node.node_key) not in edge_set:
                    if dep_key in graph and node.node_key in graph:
                        graph.add_edge(GraphEdge(
                            source=dep_key,
                            target=node.node_key,
                            dependency_type=DependencyType.HARD.value,
                        ))

        return graph

    def _find_eligible_agents(
        self, required_capabilities: list[str],
    ) -> list[str]:
        """Find agents that provide all required capabilities."""
        required = set(required_capabilities)
        eligible: list[str] = []
        for slug, caps in self._agents.items():
            if required.issubset(caps):
                eligible.append(slug)
        return eligible