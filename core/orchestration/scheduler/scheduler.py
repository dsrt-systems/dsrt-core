"""
Scheduler (C5 §24-27).

Stateless scheduling engine. Given the current execution state, returns
the set of nodes that should start executing right now.

Architecture (C5 §24):
    TaskGraph + Node States + Concurrency + Resources + Policies
                            ↓
                      Scheduler.decide()
                            ↓
                      SchedulerDecision
                      ├── nodes_to_start: list[str]
                      ├── nodes_blocked: list[str]
                      ├── waiting_for_capacity: list[str]
                      └── reasoning: dict

Key invariants (C5 §95):
  - Invariant 1: A node cannot execute until required dependencies are satisfied.
  - Invariant 7: No graph cycles (enforced by TaskGraph).
  - The scheduler is deterministic: same input → same output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schemas.domain.enums import NodeStatus

from core.observability.logging import get_logger
from core.orchestration.graph.graph import TaskGraph
from core.orchestration.scheduler.concurrency import ConcurrencyLimits
from core.orchestration.scheduler.policies import (
    SchedulingPolicy,
    SchedulingStrategy,
)


logger = get_logger("dsrt.orchestration.scheduler")


@dataclass
class SchedulingContext:
    """Current execution state passed to the Scheduler.

    This is the ONLY input the scheduler needs — it is otherwise stateless.
    """

    graph: TaskGraph

    # Per-node status (node_key -> NodeStatus value)
    node_statuses: dict[str, str] = field(default_factory=dict)

    # Nodes currently running (active)
    active_nodes: set[str] = field(default_factory=set)

    # Concurrency context
    active_global_count: int = 0
    active_org_count: int = 0
    active_per_agent: dict[str, int] = field(default_factory=dict)

    # Resource budgets (remaining)
    budget_remaining_usd: float | None = None
    budget_remaining_model_calls: int | None = None
    budget_remaining_tool_calls: int | None = None

    # Pending approvals
    pending_approvals: set[str] = field(default_factory=set)

    # Wait cycle counters (for starvation prevention)
    wait_cycles: dict[str, int] = field(default_factory=dict)

    @property
    def completed_nodes(self) -> set[str]:
        """Derive completed nodes from node_statuses."""
        return {
            k for k, s in self.node_statuses.items()
            if s == NodeStatus.COMPLETED.value
        }

    @property
    def failed_nodes(self) -> set[str]:
        """Derive failed nodes from node_statuses."""
        return {
            k for k, s in self.node_statuses.items()
            if s == NodeStatus.FAILED.value
        }

    @property
    def retrying_nodes(self) -> set[str]:
        """Derive retrying nodes from node_statuses."""
        return {
            k for k, s in self.node_statuses.items()
            if s == NodeStatus.RETRYING.value
        }


@dataclass
class SchedulerDecision:
    """Deterministic result of a scheduling pass."""

    # Nodes that should start executing now
    nodes_to_start: list[str] = field(default_factory=list)

    # Nodes blocked by failed HARD dependencies
    nodes_blocked: list[str] = field(default_factory=list)

    # Nodes that are ready but waiting for concurrency/resource capacity
    waiting_for_capacity: list[str] = field(default_factory=list)

    # Reasoning (for observability and debugging)
    reasoning: dict[str, Any] = field(default_factory=dict)

    @property
    def has_work(self) -> bool:
        """True if the decision includes any nodes to start."""
        return len(self.nodes_to_start) > 0

    @property
    def is_stalled(self) -> bool:
        """True if there is work to do but no capacity to do it."""
        return (
            not self.has_work
            and len(self.waiting_for_capacity) > 0
        )


class Scheduler:
    """Stateless orchestration scheduler.

    Given a SchedulingContext, returns a SchedulerDecision describing
    which nodes should start executing right now.

    The scheduler does NOT:
      - Persist state
      - Execute nodes
      - Modify node statuses
      - Allocate resources

    It only decides. Execution and persistence belong to C5.6 Node Executor.
    """

    def __init__(
        self,
        concurrency: ConcurrencyLimits | None = None,
        policy: SchedulingPolicy | None = None,
    ) -> None:
        self._concurrency = concurrency or ConcurrencyLimits()
        self._policy = policy or SchedulingPolicy()

    def decide(self, context: SchedulingContext) -> SchedulerDecision:
        """Run a scheduling pass and return the decision.

        Pipeline (C5 §24):
          1. Identify blocked nodes (failed HARD deps)
          2. Identify ready nodes (deps satisfied)
          3. Add retrying nodes to the ready set
          4. Check approval gate
          5. Apply strategy ordering
          6. Apply concurrency limits
          7. Apply resource limits
          8. Return decision
        """
        decision = SchedulerDecision()

        # 1. Blocked nodes (C5 Invariant 1)
        blocked = context.graph.get_blocked_nodes(
            completed=context.completed_nodes,
            failed=context.failed_nodes,
        )
        decision.nodes_blocked = blocked

        # 2. Ready nodes (dependencies satisfied)
        ready = context.graph.get_ready_nodes(
            completed=context.completed_nodes,
        )

        # Filter out nodes that are already active or in terminal state
        ready = [
            n for n in ready
            if n not in context.active_nodes
            and context.node_statuses.get(n) not in (
                NodeStatus.COMPLETED.value,
                NodeStatus.FAILED.value,
                NodeStatus.CANCELLED.value,
                NodeStatus.SKIPPED.value,
                NodeStatus.BLOCKED.value,
                NodeStatus.RUNNING.value,
                NodeStatus.QUEUED.value,
            )
        ]

        # 3. Add retrying nodes back into the ready pool
        retrying = [
            n for n in sorted(context.retrying_nodes)
            if n not in context.active_nodes
        ]

        # Combine ready + retrying, respecting policy
        if self._policy.deprioritize_retrying_nodes:
            candidates = ready + retrying
        else:
            candidates = ready + retrying

        # Deduplicate while preserving order
        seen: set[str] = set()
        candidates = [n for n in candidates if not (n in seen or seen.add(n))]

        # 4. Approval gate
        if (
            self._policy.pause_on_approval_required
            and context.pending_approvals
        ):
            decision.reasoning["paused_for_approval"] = sorted(
                context.pending_approvals
            )
            decision.waiting_for_capacity = candidates
            logger.debug(
                "scheduler_paused_for_approval",
                pending_count=len(context.pending_approvals),
                candidates_waiting=len(candidates),
            )
            return decision

        if not candidates:
            decision.reasoning["no_ready_nodes"] = True
            return decision

        # 5. Apply strategy ordering
        ordered = self._apply_strategy(candidates, context)

        # 6. Apply concurrency limits
        available_slots = self._concurrency.most_restrictive(
            active_global=context.active_global_count,
            active_org=context.active_org_count,
            active_task=len(context.active_nodes),
            active_per_agent=context.active_per_agent,
        )

        if available_slots == 0:
            decision.waiting_for_capacity = ordered
            decision.reasoning["no_capacity"] = {
                "active_global": context.active_global_count,
                "active_org": context.active_org_count,
                "active_task": len(context.active_nodes),
                "global_limit": self._concurrency.global_max_parallel_nodes,
                "org_limit": self._concurrency.org_max_parallel_nodes,
                "task_limit": self._concurrency.task_max_parallel_nodes,
            }
            logger.debug(
                "scheduler_no_capacity",
                available_slots=0,
                waiting=len(ordered),
            )
            return decision

        # 7. Apply per-agent concurrency + resource limits
        selected: list[str] = []
        waiting: list[str] = []

        for node_key in ordered:
            if len(selected) >= available_slots:
                waiting.append(node_key)
                continue

            node = context.graph.get_node(node_key)

            # Per-agent concurrency check
            if node.agent_slug:
                if not self._concurrency.agent_has_capacity(
                    node.agent_slug, context.active_per_agent,
                ):
                    waiting.append(node_key)
                    continue

            # Resource budget check
            if self._policy.respect_budget_limits:
                if not self._has_budget_for_node(node_key, node, context):
                    waiting.append(node_key)
                    decision.reasoning.setdefault("budget_blocked", []).append(
                        node_key
                    )
                    continue

            selected.append(node_key)

        decision.nodes_to_start = selected
        decision.waiting_for_capacity = waiting

        decision.reasoning["strategy"] = self._policy.strategy.value
        decision.reasoning["available_slots"] = available_slots
        decision.reasoning["selected_count"] = len(selected)
        decision.reasoning["waiting_count"] = len(waiting)
        decision.reasoning["blocked_count"] = len(blocked)

        if selected:
            logger.info(
                "scheduler_decision",
                nodes_to_start=selected,
                waiting_count=len(waiting),
                blocked_count=len(blocked),
            )

        return decision

    # ------------------------------------------------------------------
    # Strategy Application
    # ------------------------------------------------------------------

    def _apply_strategy(
        self, candidates: list[str], context: SchedulingContext,
    ) -> list[str]:
        """Order candidates according to the configured strategy."""
        strategy = self._policy.strategy

        if strategy == SchedulingStrategy.FIFO:
            # Deterministic: already sorted by get_ready_nodes
            return sorted(candidates)

        if strategy == SchedulingStrategy.PRIORITY:
            # Sort by node configuration priority (default = 50)
            def priority_key(key: str) -> tuple[int, str]:
                try:
                    node = context.graph.get_node(key)
                    pri = node.configuration.get("priority", 50)
                    return (-int(pri), key)  # Higher priority first
                except (KeyError, ValueError, TypeError):
                    return (-50, key)
            return sorted(candidates, key=priority_key)

        if strategy == SchedulingStrategy.SHORTEST_FIRST:
            def duration_key(key: str) -> tuple[int, str]:
                try:
                    node = context.graph.get_node(key)
                    dur = node.configuration.get("estimated_duration_seconds", 60)
                    return (int(dur), key)
                except (KeyError, ValueError, TypeError):
                    return (60, key)
            return sorted(candidates, key=duration_key)

        if strategy == SchedulingStrategy.CRITICAL_PATH:
            # Prefer nodes with most downstream work
            def downstream_key(key: str) -> tuple[int, str]:
                downstream_count = len(context.graph.get_all_downstream(key))
                return (-downstream_count, key)  # Most downstream first
            return sorted(candidates, key=downstream_key)

        return sorted(candidates)

    # ------------------------------------------------------------------
    # Resource Checks
    # ------------------------------------------------------------------

    def _has_budget_for_node(
        self,
        node_key: str,
        node: Any,
        context: SchedulingContext,
    ) -> bool:
        """Check if there is sufficient budget for this node."""
        # If no budget tracking, allow
        if context.budget_remaining_usd is None:
            return True

        # Estimate node cost from configuration
        estimated_cost = node.configuration.get("estimated_cost_usd", 0.0)
        if estimated_cost > 0 and context.budget_remaining_usd < estimated_cost:
            return False

        # Model call budget
        if context.budget_remaining_model_calls is not None:
            est_calls = node.configuration.get("estimated_model_calls", 1)
            if context.budget_remaining_model_calls < est_calls:
                return False

        # Tool call budget
        if context.budget_remaining_tool_calls is not None:
            est_calls = node.configuration.get("estimated_tool_calls", 0)
            if context.budget_remaining_tool_calls < est_calls:
                return False

        return True