"""
Cycle Detection for Task Graphs (C5 §15, §95 Invariant 7).

Deterministic DFS-based cycle detection. This is pure infrastructure —
it must NOT depend on an LLM or any nondeterministic component.
"""

from __future__ import annotations

from enum import Enum

from core.orchestration.graph.graph import TaskGraph


class _Color(Enum):
    """DFS node coloring for cycle detection."""
    WHITE = "WHITE"  # Unvisited
    GRAY = "GRAY"    # In current DFS path (on the stack)
    BLACK = "BLACK"  # Fully explored


class CycleDetector:
    """Detects cycles in a TaskGraph using iterative DFS.

    Usage:
        detector = CycleDetector(graph)
        if detector.has_cycle():
            cycle_nodes = detector.find_cycle_nodes()
    """

    def __init__(self, graph: TaskGraph) -> None:
        self._graph = graph

    def has_cycle(self) -> bool:
        """Return True if the graph contains at least one cycle.

        Only considers HARD dependencies (SOFT/CONDITION edges cannot
        create blocking cycles).
        """
        return len(self.find_cycle_nodes()) > 0

    def find_cycle_nodes(self) -> list[str]:
        """Return the sorted list of node keys involved in cycles.

        Returns an empty list if the graph is a valid DAG.
        Uses iterative DFS with three-color marking to avoid
        Python recursion limits on deep graphs.
        """
        color: dict[str, _Color] = {
            key: _Color.WHITE for key in self._graph.node_keys
        }
        cycle_nodes: set[str] = set()

        # Build HARD-only adjacency for cycle detection
        hard_adj: dict[str, list[str]] = {
            key: [] for key in self._graph.node_keys
        }
        for edge in self._graph.edges:
            if edge.dependency_type == "HARD":
                hard_adj[edge.source].append(edge.target)

        for start_key in sorted(self._graph.node_keys):
            if color[start_key] != _Color.WHITE:
                continue

            # Iterative DFS
            # Stack entries: (node_key, iterator_over_neighbors)
            stack: list[tuple[str, int]] = [(start_key, 0)]
            color[start_key] = _Color.GRAY
            path: list[str] = [start_key]

            while stack:
                current, idx = stack[-1]
                neighbors = sorted(hard_adj.get(current, []))

                if idx < len(neighbors):
                    # Advance the iterator
                    stack[-1] = (current, idx + 1)
                    neighbor = neighbors[idx]

                    if color[neighbor] == _Color.GRAY:
                        # Back edge found — cycle detected
                        # Collect all nodes in the cycle
                        cycle_start = path.index(neighbor)
                        for node in path[cycle_start:]:
                            cycle_nodes.add(node)
                    elif color[neighbor] == _Color.WHITE:
                        color[neighbor] = _Color.GRAY
                        stack.append((neighbor, 0))
                        path.append(neighbor)
                else:
                    # All neighbors explored
                    color[current] = _Color.BLACK
                    stack.pop()
                    path.pop()

        return sorted(cycle_nodes)

    def validate_acyclic(self) -> None:
        """Raise ValueError if the graph contains a cycle.

        This is the deterministic validation step in the plan pipeline
        (C5 §14-15). It must never depend on an LLM.
        """
        cycle_nodes = self.find_cycle_nodes()
        if cycle_nodes:
            raise ValueError(
                f"Task graph contains a cycle involving nodes: "
                f"{cycle_nodes}. A DAG must not contain cycles (C5 §15)."
            )