"""
RunIsolationManager — Ensures each run in an experiment executes in
an isolated context so that side-effects from one run cannot contaminate
another.

Isolation covers:
- Separate execution IDs and trace IDs
- Independent cost accumulators
- Separate artifact namespaces
- Snapshot integrity verification before each run
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from core.execution.experiments.snapshot import TaskSnapshot


# ---------------------------------------------------------------------------
# Isolated run context
# ---------------------------------------------------------------------------

@dataclass
class IsolatedRunContext:
    """
    Everything a single run needs to execute independently.

    Created by RunIsolationManager; consumed by the protocol runtime.
    """

    run_id: str
    experiment_id: str
    execution_id: str
    configuration_id: str
    protocol_type: str

    # Frozen inputs (copied from snapshot)
    task_prompt: str = ""
    system_instructions: str = ""
    model_provider: str = ""
    model_id: str = ""
    model_version: str | None = None
    inference_params: dict[str, Any] = field(default_factory=dict)
    available_tools: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    # Run-specific isolation
    workspace_id: str = ""
    trace_id: str = ""
    cost_accumulator: float = 0.0
    budget_limit_usd: float | None = None
    artifact_namespace: str = ""

    # Snapshot reference
    snapshot_id: str = ""
    snapshot_hash: str = ""

    @property
    def budget_remaining(self) -> float | None:
        if self.budget_limit_usd is None:
            return None
        return max(0.0, self.budget_limit_usd - self.cost_accumulator)

    def add_cost(self, amount_usd: float) -> None:
        self.cost_accumulator += amount_usd

    def is_budget_exceeded(self) -> bool:
        if self.budget_limit_usd is None:
            return False
        return self.cost_accumulator >= self.budget_limit_usd


# ---------------------------------------------------------------------------
# Isolation manager
# ---------------------------------------------------------------------------

class RunIsolationManager:
    """
    Creates isolated execution contexts from a frozen snapshot.

    Each call to ``create_isolated_context`` produces an independent
    ``IsolatedRunContext`` with its own IDs, accumulators, and artifact
    namespace.  The manager verifies snapshot integrity before creating
    each context.
    """

    def __init__(self, snapshot: TaskSnapshot) -> None:
        if not snapshot.frozen:
            raise ValueError(
                "Cannot create isolated contexts from an unfrozen snapshot. "
                "Call snapshot.freeze() first."
            )
        if not snapshot.verify_integrity():
            raise ValueError(
                "Snapshot integrity check failed. The snapshot may have been "
                "modified after freezing."
            )
        self._snapshot = snapshot
        self._created_contexts: list[str] = []

    @property
    def snapshot(self) -> TaskSnapshot:
        return self._snapshot

    @property
    def created_run_ids(self) -> list[str]:
        return list(self._created_contexts)

    def create_isolated_context(
        self,
        *,
        run_id: str | None = None,
        configuration_id: str,
        protocol_type: str,
        budget_limit_usd: float | None = None,
    ) -> IsolatedRunContext:
        """
        Create a fully isolated context for one experiment run.

        Re-verifies snapshot integrity each time to guard against
        in-memory mutation between run creations.
        """
        if not self._snapshot.verify_integrity():
            raise ValueError(
                "Snapshot integrity check failed before creating run context."
            )

        resolved_run_id = run_id or str(uuid4())
        execution_id = str(uuid4())
        trace_id = str(uuid4())
        artifact_ns = f"experiment/{self._snapshot.experiment_id}/run/{resolved_run_id}"

        ctx = IsolatedRunContext(
            run_id=resolved_run_id,
            experiment_id=self._snapshot.experiment_id,
            execution_id=execution_id,
            configuration_id=configuration_id,
            protocol_type=protocol_type,
            task_prompt=self._snapshot.context.task_prompt,
            system_instructions=self._snapshot.context.system_instructions,
            model_provider=self._snapshot.model.provider,
            model_id=self._snapshot.model.model_id,
            model_version=self._snapshot.model.model_version,
            inference_params=dict(self._snapshot.model.inference_params),
            available_tools=list(self._snapshot.context.available_tools),
            constraints=list(self._snapshot.context.constraints),
            workspace_id=self._snapshot.workspace_id,
            trace_id=trace_id,
            cost_accumulator=0.0,
            budget_limit_usd=budget_limit_usd,
            artifact_namespace=artifact_ns,
            snapshot_id=self._snapshot.snapshot_id,
            snapshot_hash=self._snapshot.content_hash,
        )

        self._created_contexts.append(resolved_run_id)
        return ctx