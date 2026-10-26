"""
PairedComparisonProtocol — Execution protocol that runs a task through
two or more configurations under controlled, isolated conditions.

This protocol is registered with the ExecutionController protocol
registry and delegates to ExperimentController for the actual
experiment lifecycle.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from core.execution.experiments.experiment_controller import (
    ExperimentConfiguration,
    ExperimentController,
    ExperimentRequest,
    ExperimentResult,
)
from core.execution.experiments.coordinator import RunExecutor
from core.execution.protocols.base import BaseExecutionProtocol

logger = logging.getLogger(__name__)


class PairedComparisonProtocol(BaseExecutionProtocol):
    """
    Wraps ExperimentController as a BaseExecutionProtocol so it can
    be registered alongside DirectExecutionProtocol and
    AmplifiedExecutionProtocol.

    The ``execute`` method expects ``prepared.config`` to contain:
    - ``configurations``: list of ExperimentConfiguration dicts
    - ``task_prompt``: the task text
    - ``system_instructions``: optional system prompt
    - ``evaluation_suite_id``: optional evaluator reference
    - ``budget``: optional ExperimentBudget dict
    - ``concurrent``: optional bool
    """

    protocol_id: str = "paired_comparison"
    protocol_version: str = "1.0.0"

    def __init__(
        self,
        *,
        executors: dict[str, RunExecutor],
    ) -> None:
        self._executors = executors
        self._experiment_controller = ExperimentController(
            executors=executors,
        )

    # -- BaseExecutionProtocol interface ------------------------------------

    async def validate(self, request: Any) -> dict[str, Any]:
        """
        Validate that the request has the minimum fields for a paired
        experiment.
        """
        errors: list[str] = []

        workspace_id = self._safe_get(request, "workspace_id", "")
        task_id = self._safe_get(request, "task_id", "")
        config = self._safe_get(request, "config", {})

        if not workspace_id:
            errors.append("workspace_id is required.")
        if not task_id:
            errors.append("task_id is required.")

        configurations = config.get("configurations", [])
        if len(configurations) < 2:
            errors.append(
                "At least two configurations are required for a paired experiment."
            )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": [],
        }

    async def prepare(self, request: Any) -> dict[str, Any]:
        """Build the ExperimentRequest from the generic execution request."""
        workspace_id = self._safe_get(request, "workspace_id", "")
        task_id = self._safe_get(request, "task_id", "")
        config = self._safe_get(request, "config", {})

        raw_configs = config.get("configurations", [])
        configurations = [
            ExperimentConfiguration(**cfg) if isinstance(cfg, dict) else cfg
            for cfg in raw_configs
        ]

        experiment_request = ExperimentRequest(
            workspace_id=workspace_id,
            task_id=task_id,
            task_prompt=config.get("task_prompt", ""),
            system_instructions=config.get("system_instructions", ""),
            configurations=configurations,
            evaluation_suite_id=config.get("evaluation_suite_id"),
            concurrent=config.get("concurrent", False),
        )

        return {
            "execution_id": self._safe_get(request, "execution_id", str(uuid4())),
            "protocol": self.protocol_id,
            "experiment_request": experiment_request,
            "config": config,
        }

    async def execute(self, prepared: Any) -> dict[str, Any]:
        """Delegate to ExperimentController."""
        if isinstance(prepared, dict):
            experiment_request = prepared.get("experiment_request")
        else:
            experiment_request = getattr(prepared, "experiment_request", None)

        if experiment_request is None:
            return {
                "success": False,
                "error": "No experiment_request found in prepared data.",
                "output": None,
            }

        result: ExperimentResult = (
            await self._experiment_controller.create_and_execute(
                experiment_request
            )
        )

        return {
            "success": result.status in ("COMPLETED", "PARTIALLY_COMPLETED"),
            "experiment_id": result.experiment_id,
            "snapshot_id": result.snapshot_id,
            "status": result.status,
            "run_outcomes": result.run_outcomes,
            "total_cost_usd": result.total_cost_usd,
            "total_duration_ms": result.total_duration_ms,
            "completed_runs": result.completed_runs,
            "failed_runs": result.failed_runs,
            "cancelled_runs": result.cancelled_runs,
            "output": None,  # experiment output is per-run
        }

    async def finalize(self, execution_id: str) -> dict[str, Any]:
        """No additional finalization needed for experiments."""
        return {
            "execution_id": execution_id,
            "finalized": True,
        }

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _safe_get(obj: Any, attr: str, default: Any) -> Any:
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)