"""
Scheduling Policies (C5 §27, §39).

Policies that influence scheduler decisions:
  - Priority ordering
  - Resource awareness
  - Fairness
  - Starvation prevention
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SchedulingStrategy(str, Enum):
    """How the scheduler orders ready nodes (C5 §24)."""

    FIFO = "FIFO"
    """First-ready-first-served (deterministic by node_key)."""

    PRIORITY = "PRIORITY"
    """Priority-based (nodes with explicit priority first)."""

    SHORTEST_FIRST = "SHORTEST_FIRST"
    """Prefer nodes with shorter estimated duration."""

    CRITICAL_PATH = "CRITICAL_PATH"
    """Prefer nodes on the critical path to completion."""


@dataclass(frozen=True)
class SchedulingPolicy:
    """Scheduling behavior configuration (C5 §27)."""

    strategy: SchedulingStrategy = SchedulingStrategy.FIFO

    # Resource awareness
    respect_resource_limits: bool = True
    respect_budget_limits: bool = True

    # Fairness
    prevent_agent_starvation: bool = True
    max_wait_cycles: int = 100

    # Retry handling
    deprioritize_retrying_nodes: bool = False
    """If True, nodes that are RETRYING get lower priority than fresh READY nodes."""

    # Human approval nodes
    pause_on_approval_required: bool = True
    """If True, do not schedule any new nodes while approval is pending."""