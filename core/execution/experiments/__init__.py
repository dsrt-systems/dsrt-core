"""
C10.5 — Paired Experiment Controller.

Coordinates controlled comparison experiments where the same task
executes through multiple configurations under fair conditions.
"""

from core.execution.experiments.snapshot import TaskSnapshot, TaskSnapshotBuilder
from core.execution.experiments.isolation import RunIsolationManager, IsolatedRunContext
from core.execution.experiments.coordinator import RunCoordinator, RunOutcome
from core.execution.experiments.experiment_controller import ExperimentController

__all__ = [
    "TaskSnapshot",
    "TaskSnapshotBuilder",
    "RunIsolationManager",
    "IsolatedRunContext",
    "RunCoordinator",
    "RunOutcome",
    "ExperimentController",
]