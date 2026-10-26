"""
Task Graph — Directed Acyclic Graph for orchestration plans (C5 §8).

Pure-logic DAG implementation using adjacency lists. No database dependency.
Deterministic ordering guaranteed via sorted iteration.

Invariants (C5 §95):
  - Invariant 1: A node cannot execute until required dependencies are satisfied.
  - Invariant 7: No graph cycles.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GraphNode:
    """An immutable node in the task graph."""
    key: str
    node_type: str = "AGENT_TASK"
    agent_slug: str | None = None
    required_capabilities: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    """An immutable directed edge (dependency) in the task graph."""
    source: str
    target: str
    dependency_type: str = "HARD"
    condition: str | None = None


class TaskGraph:
    """Directed Acyclic Graph for orchestration plans.

    Provides:
      - Node and edge management
      - Topological ordering (Kahn's algorithm)
      - Ready-node detection (nodes whose dependencies are all satisfied)
      - Downstream/upstream traversal
      - Subgraph extraction for partial replanning

    Thread-safety: This class is NOT thread-safe. The Scheduler (C5.5)
    is responsible for serializing access.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        # Adjacency: source -> set of targets (forward)
        self._forward: dict[str, set[str]] = defaultdict(set)
        # Adjacency: target -> set of sources (reverse / dependencies)
        self._reverse: dict[str, set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph. Raises ValueError on duplicate key."""
        if node.key in self._nodes:
            raise ValueError(f"Node '{node.key}' already exists in the graph.")
        self._nodes[node.key] = node

    def add_edge(self, edge: GraphEdge) -> None:
        """Add a directed dependency edge. Both nodes must already exist."""
        if edge.source not in self._nodes:
            raise ValueError(f"Source node '{edge.source}' not in graph.")
        if edge.target not in self._nodes:
            raise ValueError(f"Target node '{edge.target}' not in graph.")
        if edge.source == edge.target:
            raise ValueError(f"Self-loop detected: '{edge.source}' -> '{edge.target}'.")

        self._edges.append(edge)
        self._forward[edge.source].add(edge.target)
        self._reverse[edge.target].add(edge.source)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def node_keys(self) -> list[str]:
        """All node keys in insertion order."""
        return list(self._nodes.keys())

    @property
    def nodes(self) -> dict[str, GraphNode]:
        """All nodes keyed by node_key."""
        return dict(self._nodes)

    @property
    def edges(self) -> list[GraphEdge]:
        """All edges."""
        return list(self._edges)

    def get_node(self, key: str) -> GraphNode:
        """Get a node by key. Raises KeyError if not found."""
        return self._nodes[key]

    def get_dependencies(self, node_key: str) -> set[str]:
        """Get the set of node keys that 
ode_key` depends on (upstream)."""
        return set(self._reverse.get(node_key, set()))

    def get_dependents(self, node_key: str) -> set[str]:
        """Get the set of node keys that depend on 
ode_key` (downstream)."""
        return set(self._forward.get(node_key, set()))

    def get_all_downstream(self, node_key: str) -> set[str]:
        """Get ALL transitive downstream nodes (BFS)."""
        visited: set[str] = set()
        queue = deque(self._forward.get(node_key, set()))
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self._forward.get(current, set()) - visited)
        return visited

    def get_all_upstream(self, node_key: str) -> set[str]:
        """Get ALL transitive upstream nodes (BFS)."""
        visited: set[str] = set()
        queue = deque(self._reverse.get(node_key, set()))
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self._reverse.get(current, set()) - visited)
        return visited

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def get_ready_nodes(self, completed: set[str]) -> list[str]:
        """Return node keys whose HARD dependencies are all in `completed`.

        A node is READY if:
          1. It is not already in `completed`.
          2. Every HARD dependency is in `completed`.
          3. SOFT dependencies may be unsatisfied (they pass failure state).

        Returns a deterministically sorted list.
        """
        ready: list[str] = []

        for key in sorted(self._nodes.keys()):
            if key in completed:
                continue

            deps = self._reverse.get(key, set())
            if not deps:
                ready.append(key)
                continue

            # Check HARD dependencies only
            hard_deps = {
                e.source
                for e in self._edges
                if e.target == key and e.dependency_type == "HARD"
            }

            if hard_deps.issubset(completed):
                ready.append(key)

        return ready

    def get_blocked_nodes(
        self, completed: set[str], failed: set[str],
    ) -> list[str]:
        """Return nodes blocked by failed HARD dependencies.

        A node is BLOCKED if any of its HARD dependencies are in `failed`
        and the node itself is not completed or failed.
        """
        blocked: list[str] = []

        for key in sorted(self._nodes.keys()):
            if key in completed or key in failed:
                continue

            hard_deps = {
                e.source
                for e in self._edges
                if e.target == key and e.dependency_type == "HARD"
            }

            if hard_deps & failed:
                blocked.append(key)

        return blocked

    # ------------------------------------------------------------------
    # Topological Sort (Kahn's Algorithm)
    # ------------------------------------------------------------------

    def topological_sort(self) -> list[str]:
        """Return a topological ordering of all nodes (Kahn's algorithm).

        Raises ValueError if the graph contains a cycle.
        The ordering is deterministic (sorted tie-breaking).
        """
        in_degree: dict[str, int] = {key: 0 for key in self._nodes}
        for edge in self._edges:
            if edge.dependency_type == "HARD":
                in_degree[edge.target] += 1

        # Start with nodes that have no HARD dependencies
        queue: list[str] = sorted(
            [k for k, d in in_degree.items() if d == 0]
        )
        result: list[str] = []

        while queue:
            # Deterministic: always pick the lexicographically smallest
            queue.sort()
            current = queue.pop(0)
            result.append(current)

            for target in sorted(self._forward.get(current, set())):
                # Only decrement for HARD edges
                edge = self._get_edge(current, target)
                if edge and edge.dependency_type == "HARD":
                    in_degree[target] -= 1
                    if in_degree[target] == 0:
                        queue.append(target)

        if len(result) != len(self._nodes):
            remaining = set(self._nodes.keys()) - set(result)
            raise ValueError(
                f"Graph contains a cycle. Nodes in cycle: {sorted(remaining)}"
            )

        return result

    # ------------------------------------------------------------------
    # Subgraph Extraction (for partial replanning, C5 §36)
    # ------------------------------------------------------------------

    def extract_subgraph(self, root_keys: list[str]) -> TaskGraph:
        """Extract a subgraph containing the given roots and all downstream nodes.

        Used for partial replanning: only the failed subtree is replaced.
        """
        subgraph = TaskGraph()

        # Collect all nodes in the subtree
        included_keys: set[str] = set()
        for root in root_keys:
            if root in self._nodes:
                included_keys.add(root)
                included_keys.update(self.get_all_downstream(root))

        # Add nodes
        for key in sorted(included_keys):
            subgraph.add_node(self._nodes[key])

        # Add edges where both endpoints are in the subgraph
        for edge in self._edges:
            if edge.source in included_keys and edge.target in included_keys:
                subgraph.add_edge(edge)

        return subgraph

    # ------------------------------------------------------------------
    # Graph Hash (for plan versioning, C5 §64)
    # ------------------------------------------------------------------

    def compute_hash(self) -> str:
        """Compute a deterministic hash of the graph structure.

        Used to detect whether a replan actually changed the graph.
        """
        import hashlib
        import json

        canonical = {
            "nodes": sorted(self._nodes.keys()),
            "edges": sorted(
                f"{e.source}->{e.target}:{e.dependency_type}"
                for e in self._edges
            ),
        }
        raw = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_edge(self, source: str, target: str) -> GraphEdge | None:
        """Find the edge between source and target, if any."""
        for e in self._edges:
            if e.source == source and e.target == target:
                return e
        return None

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, key: str) -> bool:
        return key in self._nodes

    def __repr__(self) -> str:
        return (
            f"TaskGraph(nodes={len(self._nodes)}, "
            f"edges={len(self._edges)})"
        )