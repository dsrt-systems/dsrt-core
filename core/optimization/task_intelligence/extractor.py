"""
Phase C11.1: Constraint & Dependency Extractor Component

Extracts explicit/implicit task constraints and constructs dependency graphs.
"""

from typing import Any, Dict, List
from schemas.domain.task_intelligence import (
    TaskConstraint,
    TaskConstraintSet,
    TaskDependencyNode,
    TaskDependencyGraph,
    ConstraintType,
)


class ConstraintExtractor:
    """Parses text and payload data to extract hard/soft constraints."""

    def extract_constraints(self, provided: Dict[str, Any], payload: Dict[str, Any]) -> TaskConstraintSet:
        hard_constraints: List[TaskConstraint] = []
        soft_constraints: List[TaskConstraint] = []

        max_budget = provided.get("max_budget_usd") or payload.get("max_budget_usd")
        if max_budget is not None:
            max_budget = float(max_budget)
            hard_constraints.append(
                TaskConstraint(
                    key="max_budget_usd",
                    value=max_budget,
                    constraint_type=ConstraintType.HARD,
                    operator="<=",
                    description="Maximum authorized budget limit in USD"
                )
            )

        max_latency = provided.get("max_latency_ms") or payload.get("max_latency_ms")
        if max_latency is not None:
            max_latency = float(max_latency)
            hard_constraints.append(
                TaskConstraint(
                    key="max_latency_ms",
                    value=max_latency,
                    constraint_type=ConstraintType.HARD,
                    operator="<=",
                    description="Maximum authorized latency in milliseconds"
                )
            )

        min_quality = provided.get("min_quality_score") or payload.get("min_quality_score")
        if min_quality is not None:
            min_quality = float(min_quality)
            hard_constraints.append(
                TaskConstraint(
                    key="min_quality_score",
                    value=min_quality,
                    constraint_type=ConstraintType.HARD,
                    operator=">=",
                    description="Minimum required quality threshold"
                )
            )

        min_reliability = provided.get("min_reliability_score") or payload.get("min_reliability_score")
        if min_reliability is not None:
            min_reliability = float(min_reliability)
            hard_constraints.append(
                TaskConstraint(
                    key="min_reliability_score",
                    value=min_reliability,
                    constraint_type=ConstraintType.HARD,
                    operator=">=",
                    description="Minimum required reliability threshold"
                )
            )

        allowed_models = provided.get("allowed_models") or payload.get("allowed_models")
        if allowed_models and isinstance(allowed_models, list):
            hard_constraints.append(
                TaskConstraint(
                    key="allowed_models",
                    value=allowed_models,
                    constraint_type=ConstraintType.HARD,
                    operator="in",
                    description="Explicitly allowed model subset"
                )
            )

        forbidden_models = provided.get("forbidden_models") or payload.get("forbidden_models")
        if forbidden_models and isinstance(forbidden_models, list):
            hard_constraints.append(
                TaskConstraint(
                    key="forbidden_models",
                    value=forbidden_models,
                    constraint_type=ConstraintType.HARD,
                    operator="not_in",
                    description="Explicitly forbidden model list"
                )
            )

        required_tools = provided.get("required_tools") or payload.get("required_tools")
        if required_tools and isinstance(required_tools, list):
            hard_constraints.append(
                TaskConstraint(
                    key="required_tools",
                    value=required_tools,
                    constraint_type=ConstraintType.HARD,
                    operator="contains",
                    description="Required system tools"
                )
            )

        pref_latency = provided.get("target_latency_ms") or payload.get("target_latency_ms")
        if pref_latency is not None:
            soft_constraints.append(
                TaskConstraint(
                    key="target_latency_ms",
                    value=float(pref_latency),
                    constraint_type=ConstraintType.SOFT,
                    operator="<=",
                    description="Preferred response latency target"
                )
            )

        sec_level = provided.get("security_isolation_level") or payload.get("security_isolation_level") or "standard"

        return TaskConstraintSet(
            hard_constraints=hard_constraints,
            soft_constraints=soft_constraints,
            max_budget_usd=max_budget,
            max_latency_ms=max_latency,
            min_quality_score=min_quality,
            min_reliability_score=min_reliability,
            allowed_models=allowed_models,
            forbidden_models=forbidden_models,
            required_tools=required_tools,
            security_isolation_level=sec_level,
        )


class DependencyAnalyzer:
    """Constructs step dependency DAGs and checks for cycles."""

    def analyze_dependencies(self, payload: Dict[str, Any]) -> TaskDependencyGraph:
        raw_steps = payload.get("steps") or payload.get("workflow") or payload.get("subtasks")
        
        if not raw_steps or not isinstance(raw_steps, list):
            single_node = TaskDependencyNode(
                node_id="step_1",
                name="Primary Task Execution",
                dependency_type="sequential",
                prerequisites=[]
            )
            return TaskDependencyGraph(
                nodes=[single_node],
                edges=[],
                has_cycles=False,
                execution_order=["step_1"]
            )

        nodes: List[TaskDependencyNode] = []
        edges: List[Dict[str, str]] = []
        node_ids: List[str] = []

        for idx, item in enumerate(raw_steps):
            if isinstance(item, dict):
                n_id = str(item.get("id") or item.get("step_id") or f"step_{idx+1}")
                n_name = str(item.get("name") or item.get("title") or f"Step {idx+1}")
                prereqs = item.get("prerequisites") or item.get("depends_on") or []
                if not isinstance(prereqs, list):
                    prereqs = [str(prereqs)]
                prereqs = [str(p) for p in prereqs]
                dep_type = str(item.get("type") or "sequential")
            else:
                n_id = f"step_{idx+1}"
                n_name = str(item)
                prereqs = [f"step_{idx}"] if idx > 0 else []
                dep_type = "sequential"

            node_ids.append(n_id)
            nodes.append(TaskDependencyNode(
                node_id=n_id,
                name=n_name,
                dependency_type=dep_type,
                prerequisites=prereqs
            ))

            for prereq in prereqs:
                edges.append({"from": prereq, "to": n_id})

        adj: Dict[str, List[str]] = {n.node_id: [] for n in nodes}
        in_degree: Dict[str, int] = {n.node_id: 0 for n in nodes}

        for edge in edges:
            src, dst = edge["from"], edge["to"]
            if src in adj and dst in in_degree:
                adj[src].append(dst)
                in_degree[dst] += 1

        queue = [n for n in node_ids if in_degree.get(n, 0) == 0]
        execution_order: List[str] = []

        while queue:
            curr = queue.pop(0)
            execution_order.append(curr)
            for neighbor in adj.get(curr, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        has_cycles = len(execution_order) != len(nodes)
        if has_cycles:
            execution_order = node_ids

        return TaskDependencyGraph(
            nodes=nodes,
            edges=edges,
            has_cycles=has_cycles,
            execution_order=execution_order,
        )