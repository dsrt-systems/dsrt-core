"""
Arena SDK Contract (C8 §56).

Agents can RECORD benchmark metrics but CANNOT control evaluation.
This prevents agents from manipulating their own scores (C8 §57).

The existing BenchmarkSDK.record() is preserved. This module adds
read-only access to Arena results for agents that need to adapt
their behavior based on past performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKArenaResult:
    """Read-only Arena result exposed to agents."""
    run_id: str
    status: str
    task_success: bool = False
    dimensions: dict[str, float] = field(default_factory=dict)
    feedback: str = ""


class ArenaSDK(Protocol):
    """Arena SDK — read-only access to evaluation results (C8 §56).

    Agents can:
      - Record benchmark metrics (via existing BenchmarkSDK)
      - Read past Arena results for self-improvement

    Agents CANNOT:
      - Modify evaluation results
      - Access hidden evaluation state
      - Trigger evaluations
      - Read benchmark database directly
    """

    async def get_last_result(
        self,
        benchmark_id: str | None = None,
    ) -> SDKArenaResult | None:
        """Get the most recent Arena result for this agent.

        Returns None if no results exist.
        """
        ...

    async def get_capability_scores(
        self,
    ) -> dict[str, float]:
        """Get this agent's capability scores from past Arena runs.

        Returns a dict of capability_name → score (0.0-1.0).
        """
        ...