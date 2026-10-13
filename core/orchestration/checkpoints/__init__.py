"""
Checkpoint Manager (C5 §28-29).

Creates and restores durable snapshots of orchestration state
for crash recovery and long-running execution support.
"""

from core.orchestration.checkpoints.checkpoint import CheckpointManager

__all__ = ["CheckpointManager"]