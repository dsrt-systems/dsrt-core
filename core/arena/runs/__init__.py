"""
Arena Experiment & Run Management (C8 §5, §13-14, §33-37, §43).

Manages the creation of experiments (configuration matrices) and
the lifecycle of individual Arena runs.
"""

from core.arena.runs.experiment_manager import ExperimentManager
from core.arena.runs.run_manager import ArenaRunManager

__all__ = ["ArenaRunManager", "ExperimentManager"]