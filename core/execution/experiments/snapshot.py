"""
TaskSnapshot — Immutable capture of everything needed to reproduce a task.

The snapshot freezes the task, context, model identity, inference parameters,
and environment state at experiment-creation time so that every run in the
experiment starts from the exact same baseline.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Snapshot domain model
# ---------------------------------------------------------------------------

class TaskSnapshotContext(BaseModel):
    """Frozen context state captured at snapshot time."""

    system_instructions: str = ""
    task_prompt: str = ""
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    project_instructions: str = ""
    relevant_memories: list[str] = Field(default_factory=list)
    relevant_files: list[dict[str, Any]] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class TaskSnapshotModel(BaseModel):
    """Frozen model identity and inference configuration."""

    provider: str = ""
    model_id: str = ""
    model_version: str | None = None
    inference_params: dict[str, Any] = Field(default_factory=dict)
    endpoint_identity: str | None = None


class TaskSnapshotEnvironment(BaseModel):
    """Frozen environment state."""

    workspace_id: str = ""
    initial_file_hashes: dict[str, str] = Field(default_factory=dict)
    environment_type: str | None = None
    environment_config: dict[str, Any] = Field(default_factory=dict)


class TaskSnapshot(BaseModel):
    """
    Immutable capture of the complete task state.

    Every run in an experiment references the same snapshot so that
    differences between runs are attributable to the execution protocol,
    not to differing inputs.
    """

    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    experiment_id: str = ""
    workspace_id: str = ""
    task_id: str = ""

    context: TaskSnapshotContext = Field(default_factory=TaskSnapshotContext)
    model: TaskSnapshotModel = Field(default_factory=TaskSnapshotModel)
    environment: TaskSnapshotEnvironment = Field(default_factory=TaskSnapshotEnvironment)

    # Evaluation
    evaluation_suite_id: str | None = None
    evaluator_version: str | None = None

    # Integrity
    content_hash: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    frozen: bool = False

    def compute_hash(self) -> str:
        """
        Deterministic hash of all content fields.

        Used to verify that the snapshot was not tampered with between
        experiment creation and run execution.
        """
        hashable = {
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "context": self.context.model_dump(),
            "model": self.model.model_dump(),
            "environment": self.environment.model_dump(),
            "evaluation_suite_id": self.evaluation_suite_id,
            "evaluator_version": self.evaluator_version,
        }
        canonical = json.dumps(hashable, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def freeze(self) -> TaskSnapshot:
        """Return a frozen copy with computed content hash."""
        self.content_hash = self.compute_hash()
        self.frozen = True
        return self

    def verify_integrity(self) -> bool:
        """Check that the snapshot has not been modified since freezing."""
        if not self.frozen:
            return False
        return self.compute_hash() == self.content_hash


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class TaskSnapshotBuilder:
    """
    Assembles a TaskSnapshot from workspace / task / model state.

    In production this will pull live state from C4 Context Engine,
    C2 Model Gateway, C7 World Runtime, etc.  The builder keeps the
    snapshot construction deterministic and testable.
    """

    def __init__(self) -> None:
        self._snapshot = TaskSnapshot()

    # -- identity -----------------------------------------------------------

    def set_identifiers(
        self,
        experiment_id: str,
        workspace_id: str,
        task_id: str,
    ) -> TaskSnapshotBuilder:
        self._snapshot.experiment_id = experiment_id
        self._snapshot.workspace_id = workspace_id
        self._snapshot.task_id = task_id
        self._snapshot.environment.workspace_id = workspace_id
        return self

    # -- context ------------------------------------------------------------

    def set_context(
        self,
        *,
        system_instructions: str = "",
        task_prompt: str = "",
        conversation_history: list[dict[str, Any]] | None = None,
        project_instructions: str = "",
        relevant_memories: list[str] | None = None,
        relevant_files: list[dict[str, Any]] | None = None,
        available_tools: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> TaskSnapshotBuilder:
        self._snapshot.context = TaskSnapshotContext(
            system_instructions=system_instructions,
            task_prompt=task_prompt,
            conversation_history=conversation_history or [],
            project_instructions=project_instructions,
            relevant_memories=relevant_memories or [],
            relevant_files=relevant_files or [],
            available_tools=available_tools or [],
            constraints=constraints or [],
        )
        return self

    # -- model --------------------------------------------------------------

    def set_model(
        self,
        *,
        provider: str = "",
        model_id: str = "",
        model_version: str | None = None,
        inference_params: dict[str, Any] | None = None,
        endpoint_identity: str | None = None,
    ) -> TaskSnapshotBuilder:
        self._snapshot.model = TaskSnapshotModel(
            provider=provider,
            model_id=model_id,
            model_version=model_version,
            inference_params=inference_params or {},
            endpoint_identity=endpoint_identity,
        )
        return self

    # -- environment --------------------------------------------------------

    def set_environment(
        self,
        *,
        initial_file_hashes: dict[str, str] | None = None,
        environment_type: str | None = None,
        environment_config: dict[str, Any] | None = None,
    ) -> TaskSnapshotBuilder:
        self._snapshot.environment.initial_file_hashes = initial_file_hashes or {}
        self._snapshot.environment.environment_type = environment_type
        self._snapshot.environment.environment_config = environment_config or {}
        return self

    # -- evaluation ---------------------------------------------------------

    def set_evaluation(
        self,
        *,
        evaluation_suite_id: str | None = None,
        evaluator_version: str | None = None,
    ) -> TaskSnapshotBuilder:
        self._snapshot.evaluation_suite_id = evaluation_suite_id
        self._snapshot.evaluator_version = evaluator_version
        return self

    # -- build --------------------------------------------------------------

    def build(self) -> TaskSnapshot:
        """Freeze and return the snapshot."""
        return self._snapshot.freeze()