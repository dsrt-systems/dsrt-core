"""
Trajectory Evaluator (C8 §22).

Layer 2 evaluation: process quality assessment from the trajectory.

Questions answered (C8 §22):
  - How did the agent work?
  - How many actions?
  - How many failed actions?
  - Did it recover?
  - Did it use appropriate tools?
  - Did it waste resources?
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import EvaluatorType, MetricType

from core.arena.evaluators.base import (
    BaseEvaluator,
    EvaluationInput,
    EvaluationOutput,
)
from core.observability.logging import get_logger


logger = get_logger("dsrt.arena.evaluators.trajectory")


class TrajectoryEvaluator(BaseEvaluator):
    """Evaluates the quality of the execution process (C8 §22).

    Unlike the DeterministicEvaluator (which checks outcomes),
    this evaluator checks HOW the agent achieved the result.
    """

    @property
    def evaluator_id(self) -> str:
        return "trajectory_process_v1"

    @property
    def evaluator_type(self) -> EvaluatorType:
        return EvaluatorType.RULE_BASED

    async def evaluate(
        self,
        input_data: EvaluationInput,
    ) -> EvaluationOutput:
        """Evaluate the execution trajectory for process quality."""
        traj = input_data.trajectory_summary
        if not traj:
            return EvaluationOutput(
                evaluator_id=self.evaluator_id,
                evaluator_type=self.evaluator_type,
                passed=False,
                summary="No trajectory data available.",
            )

        metrics = []
        event_count = traj.get("event_count", 0)
        tool_calls = traj.get("tool_call_count", 0)
        model_calls = traj.get("model_call_count", 0)
        failures = traj.get("failure_count", 0)
        recoveries = traj.get("recovery_count", 0)
        duration_ms = traj.get("duration_ms", 0)

        # 1. Reliability metric
        reliability = 1.0
        if event_count > 0:
            reliability = max(0.0, 1.0 - (failures / max(event_count, 1)))
        metrics.append(self._metric(
            metric_id="reliability",
            metric_type=MetricType.RELIABILITY.value,
            value=reliability,
            explanation=f"{failures} failures out of {event_count} events",
        ))

        # 2. Recovery metric
        recovery_score = 1.0
        if failures > 0:
            recovery_score = min(1.0, recoveries / failures)
        metrics.append(self._metric(
            metric_id="recovery",
            metric_type=MetricType.RECOVERY.value,
            value=recovery_score,
            explanation=f"{recoveries} recoveries out of {failures} failures",
        ))

        # 3. Tool efficiency
        tool_efficiency = 1.0
        if tool_calls > 0:
            tool_efficiency = max(0.0, 1.0 - (failures / tool_calls))
        metrics.append(self._metric(
            metric_id="tool_efficiency",
            metric_type=MetricType.TOOL_EFFICIENCY.value,
            value=tool_efficiency,
            explanation=f"{tool_calls} tool calls, {failures} failures",
        ))

        # 4. Action count (informational — more isn't always worse)
        metrics.append(self._metric(
            metric_id="action_count",
            metric_type=MetricType.TOOL_EFFICIENCY.value,
            value=float(event_count),
            explanation=f"Total events: {event_count}, tools: {tool_calls}, models: {model_calls}",
        ))

        # 5. Duration efficiency
        metrics.append(self._metric(
            metric_id="latency",
            metric_type=MetricType.LATENCY.value,
            value=float(duration_ms),
            explanation=f"Total duration: {duration_ms}ms",
        ))

        all_passed = reliability >= 0.5 and tool_efficiency >= 0.5

        return EvaluationOutput(
            evaluator_id=self.evaluator_id,
            evaluator_type=self.evaluator_type,
            metrics=metrics,
            passed=all_passed,
            summary=(
                f"Trajectory: {event_count} events, reliability={reliability:.2f}, "
                f"recovery={recovery_score:.2f}, efficiency={tool_efficiency:.2f}"
            ),
        )