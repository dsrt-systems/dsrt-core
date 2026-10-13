"""
Graph Validator (C5 §14).

Validates a TaskGraph against the complete set of structural rules
before it can be accepted as a Plan. This is deterministic infrastructure.

Validation pipeline (C5 §14):
  1. Schema validation (node keys unique, edges reference valid nodes)
  2. Graph validation (at least one node)
  3. Dependency validation (no dangling references)
  4. Capability validation (deferred to Planner — requires registry)
  5. Permission validation (deferred to Planner — requires security context)
  6. Resource validation (deferred to Planner — requires budget)
  7. Cycle detection (C5 §15)
  8. Policy validation (deferred to Planner — requires org policy)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.orchestration.graph.cycle_detection import CycleDetector
from core.orchestration.graph.graph import TaskGraph


@dataclass
class ValidationResult:
    """Result of a graph validation check."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: ValidationResult) -> ValidationResult:
        """Merge another result into this one."""
        return ValidationResult(
            valid=self.valid and other.valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


class GraphValidator:
    """Validates the structural integrity of a TaskGraph.

    This class performs ONLY deterministic, graph-structural checks.
    Capability, permission, resource, and policy checks are performed
    by the Planner (C5.4) which has access to registries and security.
    """

    def validate(self, graph: TaskGraph) -> ValidationResult:
        """Run all structural validations and return a combined result."""
        result = ValidationResult(valid=True)

        result = result.merge(self._validate_not_empty(graph))
        result = result.merge(self._validate_node_keys_unique(graph))
        result = result.merge(self._validate_edges_reference_valid_nodes(graph))
        result = result.merge(self._validate_no_self_loops(graph))
        result = result.merge(self._validate_acyclic(graph))
        result = result.merge(self._validate_reachable(graph))
        result = result.merge(self._validate_node_types(graph))

        return result

    # ------------------------------------------------------------------
    # Individual Checks
    # ------------------------------------------------------------------

    def _validate_not_empty(self, graph: TaskGraph) -> ValidationResult:
        """Graph must contain at least one node."""
        if len(graph) == 0:
            return ValidationResult(
                valid=False,
                errors=["Graph must contain at least one node."],
            )
        return ValidationResult(valid=True)

    def _validate_node_keys_unique(self, graph: TaskGraph) -> ValidationResult:
        """All node keys must be unique (guaranteed by TaskGraph.add_node)."""
        keys = graph.node_keys
        if len(keys) != len(set(keys)):
            duplicates = [k for k in keys if keys.count(k) > 1]
            return ValidationResult(
                valid=False,
                errors=[f"Duplicate node keys: {sorted(set(duplicates))}"],
            )
        return ValidationResult(valid=True)

    def _validate_edges_reference_valid_nodes(
        self, graph: TaskGraph,
    ) -> ValidationResult:
        """Every edge must reference nodes that exist in the graph."""
        errors: list[str] = []
        for edge in graph.edges:
            if edge.source not in graph:
                errors.append(
                    f"Edge source '{edge.source}' not found in graph."
                )
            if edge.target not in graph:
                errors.append(
                    f"Edge target '{edge.target}' not found in graph."
                )
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _validate_no_self_loops(self, graph: TaskGraph) -> ValidationResult:
        """No node can depend on itself."""
        errors: list[str] = []
        for edge in graph.edges:
            if edge.source == edge.target:
                errors.append(
                    f"Self-loop detected: '{edge.source}' -> '{edge.target}'."
                )
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _validate_acyclic(self, graph: TaskGraph) -> ValidationResult:
        """Graph must be a DAG — no cycles in HARD dependencies (C5 §15)."""
        detector = CycleDetector(graph)
        cycle_nodes = detector.find_cycle_nodes()
        if cycle_nodes:
            return ValidationResult(
                valid=False,
                errors=[
                    f"Cycle detected involving nodes: {cycle_nodes}. "
                    f"A task graph must be a directed acyclic graph (C5 §15)."
                ],
            )
        return ValidationResult(valid=True)

    def _validate_reachable(self, graph: TaskGraph) -> ValidationResult:
        """Warn if there are disconnected subgraphs (isolated nodes).

        This is a warning, not an error — isolated nodes may be valid
        for parallel independent work streams.
        """
        if len(graph) <= 1:
            return ValidationResult(valid=True)

        # Find root nodes (no incoming HARD edges)
        roots = set(graph.node_keys)
        for edge in graph.edges:
            if edge.dependency_type == "HARD":
                roots.discard(edge.target)

        if not roots:
            return ValidationResult(
                valid=True,
                warnings=["No root nodes found — all nodes have dependencies."],
            )

        # BFS from all roots to find reachable nodes
        from collections import deque
        visited: set[str] = set()
        queue = deque(roots)
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            queue.extend(graph.get_dependents(current) - visited)

        unreachable = set(graph.node_keys) - visited
        if unreachable:
            return ValidationResult(
                valid=True,
                warnings=[
                    f"Unreachable nodes (not connected to any root): "
                    f"{sorted(unreachable)}"
                ],
            )

        return ValidationResult(valid=True)

    def _validate_node_types(self, graph: TaskGraph) -> ValidationResult:
        """Validate that node types are recognized."""
        valid_types = {
            "AGENT_TASK", "VERIFICATION", "CONDITION",
            "MERGE", "CHECKPOINT", "HUMAN_APPROVAL",
        }
        errors: list[str] = []
        for key, node in graph.nodes.items():
            if node.node_type not in valid_types:
                errors.append(
                    f"Node '{key}' has unrecognized type '{node.node_type}'. "
                    f"Valid types: {sorted(valid_types)}"
                )
        return ValidationResult(valid=len(errors) == 0, errors=errors)