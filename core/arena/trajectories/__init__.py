"""
Arena Trajectory Engine (C8 §16-19, §43, §54).

Builds, persists, and queries execution trajectories from the
C1 event stream. Trajectories are the primary evaluation artifact.
"""

from core.arena.trajectories.builder import TrajectoryBuilder
from core.arena.trajectories.store import TrajectoryStore

__all__ = ["TrajectoryBuilder", "TrajectoryStore"]