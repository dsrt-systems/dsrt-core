"""
World State Management (C7 §15-19, §45-47).

Versioned state tracking, snapshot/restore, and diff computation
for World instances.
"""

from core.worlds.state.state_manager import WorldStateManager
from core.worlds.state.snapshots import WorldSnapshotManager
from core.worlds.state.diffs import WorldDiffEngine

__all__ = ["WorldDiffEngine", "WorldSnapshotManager", "WorldStateManager"]