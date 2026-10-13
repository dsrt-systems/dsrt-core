"""
Concurrency Limits (C5 §26).

Multi-level concurrency controls:
  - Global
  - Per organization
  - Per task
  - Per agent
  - Per tool

The Scheduler enforces the most restrictive applicable limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConcurrencyLimits:
    """Multi-level concurrency limits (C5 §26)."""

    # Global limit (applies to the entire DSRT instance)
    global_max_parallel_nodes: int = 20

    # Per-organization limit
    org_max_parallel_nodes: int = 10

    # Per-task limit (plan constraint)
    task_max_parallel_nodes: int = 5

    # Per-agent limit (prevents overloading a single agent)
    agent_max_concurrent_executions: int = 3

    # Per-tool limit (prevents overloading a single tool runtime)
    tool_max_concurrent_requests: int = 10

    def most_restrictive(
        self,
        active_global: int,
        active_org: int,
        active_task: int,
        active_per_agent: dict[str, int] | None = None,
    ) -> int:
        """Return the maximum additional nodes we can start right now.

        Returns 0 if any limit is already saturated.
        """
        slots_global = max(0, self.global_max_parallel_nodes - active_global)
        slots_org = max(0, self.org_max_parallel_nodes - active_org)
        slots_task = max(0, self.task_max_parallel_nodes - active_task)

        return min(slots_global, slots_org, slots_task)

    def agent_has_capacity(
        self, agent_slug: str, active_per_agent: dict[str, int],
    ) -> bool:
        """Check if a specific agent has concurrency capacity."""
        current = active_per_agent.get(agent_slug, 0)
        return current < self.agent_max_concurrent_executions