"""
Unit tests for C5.3 Task Graph Engine.

Tests DAG construction, topological sorting, cycle detection,
ready-node detection, blocked-node detection, and subgraph extraction.
"""

from __future__ import annotations

import pytest

from core.orchestration.graph.graph import GraphEdge, GraphNode, TaskGraph
from core.orchestration.graph.cycle_detection import CycleDetector
from core.orchestration.graph.validator import GraphValidator


class TestTaskGraph:
    def test_add_nodes_and_edges(self):
        g = TaskGraph()
        g.add_node(GraphNode(key="A"))
        g.add_node(GraphNode(key="B"))
        g.add_edge(GraphEdge(source="A", target="B"))
        assert len(g) == 2
        assert len(g.edges) == 1

    def test_duplicate_node_raises(self):
        g = TaskGraph()
        g.add_node(GraphNode(key="A"))
        with pytest.raises(ValueError, match="already exists"):
            g.add_node(GraphNode(key="A"))

    def test_self_loop_raises(self):
        g = TaskGraph()
        g.add_node(GraphNode(key="A"))
        with pytest.raises(ValueError, match="Self-loop"):
            g.add_edge(GraphEdge(source="A", target="A"))

    def test_missing_node_edge_raises(self):
        g = TaskGraph()
        g.add_node(GraphNode(key="A"))
        with pytest.raises(ValueError, match="not in graph"):
            g.add_edge(GraphEdge(source="A", target="Z"))

    def test_topological_sort_linear(self):
        g = TaskGraph()
        for k in ["A", "B", "C", "D"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="B"))
        g.add_edge(GraphEdge(source="B", target="C"))
        g.add_edge(GraphEdge(source="C", target="D"))
        topo = g.topological_sort()
        assert topo == ["A", "B", "C", "D"]

    def test_topological_sort_diamond(self):
        g = TaskGraph()
        for k in ["A", "B", "C", "D"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="B"))
        g.add_edge(GraphEdge(source="A", target="C"))
        g.add_edge(GraphEdge(source="B", target="D"))
        g.add_edge(GraphEdge(source="C", target="D"))
        topo = g.topological_sort()
        assert topo.index("A") < topo.index("B")
        assert topo.index("A") < topo.index("C")
        assert topo.index("B") < topo.index("D")
        assert topo.index("C") < topo.index("D")

    def test_topological_sort_cycle_raises(self):
        g = TaskGraph()
        for k in ["X", "Y", "Z"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="X", target="Y"))
        g.add_edge(GraphEdge(source="Y", target="Z"))
        g.add_edge(GraphEdge(source="Z", target="X"))
        with pytest.raises(ValueError, match="cycle"):
            g.topological_sort()

    def test_ready_nodes_initial(self):
        g = TaskGraph()
        for k in ["A", "B", "C"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="C"))
        g.add_edge(GraphEdge(source="B", target="C"))
        ready = g.get_ready_nodes(completed=set())
        assert ready == ["A", "B"]

    def test_ready_nodes_after_completion(self):
        g = TaskGraph()
        for k in ["A", "B", "C"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="C"))
        g.add_edge(GraphEdge(source="B", target="C"))
        ready = g.get_ready_nodes(completed={"A", "B"})
        assert ready == ["C"]

    def test_blocked_nodes(self):
        g = TaskGraph()
        for k in ["A", "B", "C"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="C"))
        g.add_edge(GraphEdge(source="B", target="C"))
        blocked = g.get_blocked_nodes(completed={"A"}, failed={"B"})
        assert "C" in blocked

    def test_downstream(self):
        g = TaskGraph()
        for k in ["A", "B", "C", "D"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="B"))
        g.add_edge(GraphEdge(source="B", target="C"))
        g.add_edge(GraphEdge(source="C", target="D"))
        assert g.get_all_downstream("A") == {"B", "C", "D"}
        assert g.get_all_downstream("C") == {"D"}
        assert g.get_all_downstream("D") == set()

    def test_upstream(self):
        g = TaskGraph()
        for k in ["A", "B", "C"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="C"))
        g.add_edge(GraphEdge(source="B", target="C"))
        assert g.get_all_upstream("C") == {"A", "B"}

    def test_subgraph_extraction(self):
        g = TaskGraph()
        for k in ["A", "B", "C", "D", "E"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="B"))
        g.add_edge(GraphEdge(source="B", target="C"))
        g.add_edge(GraphEdge(source="C", target="D"))
        g.add_edge(GraphEdge(source="A", target="E"))
        sub = g.extract_subgraph(["B"])
        assert set(sub.node_keys) == {"B", "C", "D"}
        assert "A" not in sub
        assert "E" not in sub

    def test_graph_hash_deterministic(self):
        g = TaskGraph()
        for k in ["A", "B"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="B"))
        h1 = g.compute_hash()
        h2 = g.compute_hash()
        assert h1 == h2
        assert len(h1) == 64

    def test_soft_dependency_not_blocking(self):
        g = TaskGraph()
        for k in ["A", "B"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="B", dependency_type="SOFT"))
        # B should be ready even though A is not completed (SOFT dep)
        ready = g.get_ready_nodes(completed=set())
        assert "A" in ready
        assert "B" in ready


class TestCycleDetector:
    def test_acyclic_graph(self):
        g = TaskGraph()
        for k in ["A", "B", "C"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="B"))
        g.add_edge(GraphEdge(source="B", target="C"))
        detector = CycleDetector(g)
        assert not detector.has_cycle()

    def test_cyclic_graph(self):
        g = TaskGraph()
        for k in ["A", "B", "C"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="B"))
        g.add_edge(GraphEdge(source="B", target="C"))
        g.add_edge(GraphEdge(source="C", target="A"))
        detector = CycleDetector(g)
        assert detector.has_cycle()
        assert set(detector.find_cycle_nodes()) == {"A", "B", "C"}

    def test_validate_acyclic_raises(self):
        g = TaskGraph()
        for k in ["X", "Y"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="X", target="Y"))
        g.add_edge(GraphEdge(source="Y", target="X"))
        detector = CycleDetector(g)
        with pytest.raises(ValueError, match="cycle"):
            detector.validate_acyclic()


class TestGraphValidator:
    def test_valid_graph(self):
        g = TaskGraph()
        for k in ["A", "B"]:
            g.add_node(GraphNode(key=k))
        g.add_edge(GraphEdge(source="A", target="B"))
        validator = GraphValidator()
        result = validator.validate(g)
        assert result.valid

    def test_empty_graph_invalid(self):
        g = TaskGraph()
        validator = GraphValidator()
        result = validator.validate(g)
        assert not result.valid