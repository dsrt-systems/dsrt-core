"""
Deterministic Evaluator (C8 §21, §25).

Layer 1 evaluation: outcome verification using deterministic checks.

Questions answered (C8 §21):
  - Was the task completed?
  - Was the answer correct?
  - Was the artifact valid?
  - Were constraints satisfied?
  - Did the world reach the required state?

This evaluator uses NO LLM calls. All checks are code-based.
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


logger = get_logger("dsrt.arena.evaluators.deterministic")


class DeterministicEvaluator(BaseEvaluator):
    """Deterministic outcome evaluator (C8 §21, §25).

    Evaluates:
      1. Task success (was the execution completed?)
      2. Artifact validity (do artifacts exist and parse?)
      3. Constraint satisfaction (were all constraints met?)
      4. World state (did the world reach expected state?)
      5. Completeness (were all requirements addressed?)
    """

    @property
    def evaluator_id(self) -> str:
        return "deterministic_outcome_v1"

    @property
    def evaluator_type(self) -> EvaluatorType:
        return EvaluatorType.DETERMINISTIC

    async def evaluate(
        self,
        input_data: EvaluationInput,
    ) -> EvaluationOutput:
        """Run all deterministic checks on the Arena run."""
        metrics = []
        evidence = []
        all_passed = True

        # 1. Task Success (C8 §21)
        task_success = self._check_task_success(input_data)
        metrics.append(self._metric(
            metric_id="task_success",
            metric_type=MetricType.TASK_SUCCESS.value,
            value=task_success,
            explanation="Execution completed successfully" if task_success else "Execution did not complete",
            evidence_refs=[input_data.arena_run_id],
        ))
        if not task_success:
            all_passed = False

        # 2. Artifact Validity (C8 §21, §23)
        artifact_valid = self._check_artifacts(input_data)
        metrics.append(self._metric(
            metric_id="artifact_valid",
            metric_type=MetricType.COMPLETENESS.value,
            value=artifact_valid,
            explanation=f"{len(input_data.artifacts)} artifact(s) checked",
        ))
        if not artifact_valid and input_data.success_conditions.get("report_exists"):
            all_passed = False

        # 3. Constraint Satisfaction (C8 §21)
        constraints_met = self._check_constraints(input_data)
        metrics.append(self._metric(
            metric_id="constraint_adherence",
            metric_type=MetricType.CONSTRAINT_ADHERENCE.value,
            value=constraints_met,
            explanation="All task constraints satisfied" if constraints_met else "Some constraints violated",
        ))
        if not constraints_met:
            all_passed = False

        # 4. World State (C8 §21)
        if input_data.success_conditions:
            world_correct = self._check_world_state(input_data)
            metrics.append(self._metric(
                metric_id="world_state_correct",
                metric_type=MetricType.CORRECTNESS.value,
                value=world_correct,
                explanation="World reached expected state" if world_correct else "World state mismatch",
            ))
            if not world_correct:
                all_passed = False

        # 5. Completeness (C8 §21)
        completeness = self._check_completeness(input_data)
        metrics.append(self._metric(
            metric_id="completeness",
            metric_type=MetricType.COMPLETENESS.value,
            value=completeness,
            explanation=f"Requirement coverage: {completeness:.0%}" if isinstance(completeness, float) else str(completeness),
        ))

        # 6. Resource metrics (C8 §23)
        resource = input_data.resource_usage
        if resource:
            metrics.append(self._metric(
                metric_id="latency",
                metric_type=MetricType.LATENCY.value,
                value=float(resource.get("duration_ms", 0)),
                explanation=f"Execution took {resource.get('duration_ms', 0)}ms",
            ))
            metrics.append(self._metric(
                metric_id="cost",
                metric_type=MetricType.COST.value,
                value=float(resource.get("estimated_cost_usd", 0)),
                explanation=f"Estimated cost: ${resource.get('estimated_cost_usd', 0):.4f}",
            ))

        # 7. Trajectory metrics (C8 §22)
        traj = input_data.trajectory_summary
        if traj:
            metrics.append(self._metric(
                metric_id="tool_efficiency",
                metric_type=MetricType.TOOL_EFFICIENCY.value,
                value=self._compute_tool_efficiency(traj),
                explanation=f"Tool calls: {traj.get('tool_call_count', 0)}, Failures: {traj.get('failure_count', 0)}",
            ))

        summary = (
            f"Deterministic evaluation: {'PASS' if all_passed else 'FAIL'}. "
            f"{len(metrics)} metrics computed."
        )

        logger.info(
            "deterministic_evaluation_complete",
            run_id=input_data.arena_run_id,
            passed=all_passed,
            metrics=len(metrics),
        )

        return EvaluationOutput(
            evaluator_id=self.evaluator_id,
            evaluator_type=self.evaluator_type,
            metrics=metrics,
            passed=all_passed,
            summary=summary,
            evidence_refs=evidence,
        )

    # ------------------------------------------------------------------
    # Individual Checks
    # ------------------------------------------------------------------

    def _check_task_success(self, input_data: EvaluationInput) -> bool:
        """Check if the task execution completed successfully."""
        traj = input_data.trajectory_summary
        if not traj:
            return False
        # Check for completion event in trajectory
        return traj.get("event_count", 0) > 0 and traj.get("failure_count", 0) == 0

    def _check_artifacts(self, input_data: EvaluationInput) -> bool:
        """Check if required artifacts exist and are valid."""
        if not input_data.artifacts:
            # No artifacts required
            return not input_data.success_conditions.get("report_exists", False)

        for artifact in input_data.artifacts:
            if not artifact.get("id"):
                return False
            if artifact.get("size_bytes", 0) == 0 and artifact.get("content", "") == "":
                return False

        return True

    def _check_constraints(self, input_data: EvaluationInput) -> bool:
        """Check if all task constraints were satisfied."""
        constraints = input_data.task_constraints
        if not constraints:
            return True

        # Check duration constraint
        max_duration = constraints.get("max_duration_seconds")
        if max_duration and input_data.trajectory_summary:
            actual_ms = input_data.trajectory_summary.get("duration_ms", 0)
            if actual_ms > max_duration * 1000:
                return False

        # Check cost constraint
        max_cost = constraints.get("max_cost_usd")
        if max_cost and input_data.resource_usage:
            actual_cost = input_data.resource_usage.get("estimated_cost_usd", 0)
            if actual_cost > max_cost:
                return False

        return True

    def _check_world_state(self, input_data: EvaluationInput) -> bool:
        """Check if the world reached the expected state."""
        expected = input_data.success_conditions
        actual = input_data.world_state

        if not expected:
            return True

        for key, expected_val in expected.items():
            if key in ("report_exists", "claims_verified", "minimum_sources"):
                continue  # Handled by other checks
            actual_val = actual.get(key)
            if actual_val != expected_val:
                return False

        return True

    def _check_completeness(self, input_data: EvaluationInput) -> float:
        """Check requirement coverage (0.0 to 1.0)."""
        conditions = input_data.success_conditions
        if not conditions:
            return 1.0

        total = 0
        met = 0

        for key, expected in conditions.items():
            if isinstance(expected, bool):
                total += 1
                if expected:
                    # Check if the condition is met in artifacts or world state
                    if key == "report_exists" and input_data.artifacts:
                        met += 1
                    elif key == "claims_verified":
                        # Check verification results
                        verified = any(
                            v.get("status") == "PASSED"
                            for v in input_data.verification_results
                        )
                        if verified:
                            met += 1
                    elif key in input_data.world_state:
                        met += 1
            elif isinstance(expected, int):
                total += 1
                actual = input_data.world_state.get(key, 0)
                if actual >= expected:
                    met += 1

        return met / total if total > 0 else 1.0

    @staticmethod
    def _compute_tool_efficiency(trajectory: dict[str, Any]) -> float:
        """Compute tool efficiency from trajectory data.

        Efficiency = successful tool calls / total tool calls.
        """
        total = trajectory.get("tool_call_count", 0)
        failures = trajectory.get("failure_count", 0)

        if total == 0:
            return 1.0

        return max(0.0, (total - failures) / total)