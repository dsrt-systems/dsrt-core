"""
Unit tests for C5.5 Scheduler.
"""

from __future__ import annotations

import pytest

from core.orchestration.graph.graph import GraphEdge, GraphNode, TaskGraph
from core.orchestration.scheduler import (
    ConcurrencyLimits, Scheduler, SchedulingContext, SchedulingPolicy,
)
from core.orchestration.scheduler.policies import SchedulingStrategy


class TestScheduler:
    @pytest.fixture
    def diamond_graph(self):
        g = TaskGraph()
        for k in ["A", "B", "C", "D"]:
            g.add_node(GraphNode(key=k, agent_slug=f"agent_{k}"))
        g.add_edge(GraphEdge(source="A", target="C"))
        g.add_edge(GraphEdge(source="B", target="C"))
        g.add_edge(GraphEdge(source="C", target="D"))
        return g

    def test_initial_ready(self, diamond_graph):
        s = Scheduler()
        d = s.decide(SchedulingContext(graph=diamond_graph))
        assert d.nodes_to_start == ["A", "B"]

    def test_after_partial_completion(self, diamond_graph):
        s = Scheduler()
        ctx = SchedulingContext(
            graph=diamond_graph,
            node_statuses={"A": "COMPLETED", "B": "COMPLETED"},
        )
        d = s.decide(ctx)
        assert d.nodes_to_start == ["C"]

    def test_blocked_by_failure(self, diamond_graph):
        s = Scheduler()
        ctx = SchedulingContext(
            graph=diamond_graph,
            node_statuses={"A": "COMPLETED", "B": "FAILED"},
        )
        d = s.decide(ctx)
        # C is directly blocked (depends on failed B via HARD dep)
        assert "C" in d.nodes_blocked
        # D is NOT directly blocked — its dep is C (not failed).
        # D is simply "not ready" because C hasn't completed.
        # Transitive blocking is handled by the Replanner (C5.10).
        assert "D" not in d.nodes_blocked
        assert "D" not in d.nodes_to_start

    def test_concurrency_limit(self, diamond_graph):
        s = Scheduler(concurrency=ConcurrencyLimits(task_max_parallel_nodes=1))
        d = s.decide(SchedulingContext(graph=diamond_graph))
        assert len(d.nodes_to_start) == 1
        assert len(d.waiting_for_capacity) == 1

    def test_saturated(self, diamond_graph):
        s = Scheduler()
        ctx = SchedulingContext(graph=diamond_graph, active_global_count=20)
        d = s.decide(ctx)
        assert d.nodes_to_start == []
        assert d.is_stalled

    def test_approval_gate(self, diamond_graph):
        s = Scheduler()
        ctx = SchedulingContext(
            graph=diamond_graph,
            pending_approvals={"approval_1"},
        )
        d = s.decide(ctx)
        assert d.nodes_to_start == []
        assert "paused_for_approval" in d.reasoning

    def test_retrying_nodes_rescheduled(self, diamond_graph):
        s = Scheduler()
        ctx = SchedulingContext(
            graph=diamond_graph,
            node_statuses={"A": "COMPLETED", "B": "COMPLETED", "C": "RETRYING"},
        )
        d = s.decide(ctx)
        assert "C" in d.nodes_to_start

    def test_priority_strategy(self):
        g = TaskGraph()
        g.add_node(GraphNode(key="low", configuration={"priority": 10}))
        g.add_node(GraphNode(key="high", configuration={"priority": 90}))
        s = Scheduler(policy=SchedulingPolicy(strategy=SchedulingStrategy.PRIORITY))
        d = s.decide(SchedulingContext(graph=g))
        assert d.nodes_to_start == ["high", "low"]

    def test_budget_exhausted(self):
        g = TaskGraph()
        g.add_node(GraphNode(key="expensive", configuration={"estimated_cost_usd": 5.0}))
        s = Scheduler()
        ctx = SchedulingContext(graph=g, budget_remaining_usd=0.0)
        d = s.decide(ctx)
        assert d.nodes_to_start == []