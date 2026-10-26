"""
World Diff Engine (C7 §45-47).

Computes differences between world state snapshots, enabling:
  - Action verification (C7 §44): did the world change as expected?
  - Debugging: what changed between two points?
  - C6 verification: state consistency checks
  - Arena evaluation: trajectory reconstruction

Diff output format (C7 §45):
    BEFORE: /data/report.csv absent
    ACTION: create report.csv
    AFTER:  /data/report.csv present, size = 82 KB
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schemas.domain.enums import WorldActionReversibility, WorldChangeType
from schemas.domain.world import WorldChange, WorldStateDiff

from core.observability.logging import get_logger
from core.storage.models.world_state import WorldStateVersionORM
from core.worlds.state.state_manager import WorldStateManager


logger = get_logger("dsrt.worlds.diffs")


@dataclass
class StateDimensionDiff:
    """Diff for a single state dimension (filesystem, database, etc.)."""
    dimension: str
    added: dict[str, Any] = field(default_factory=dict)
    removed: dict[str, Any] = field(default_factory=dict)
    modified: dict[str, Any] = field(default_factory=dict)
    unchanged_count: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.modified)


class WorldDiffEngine:
    """Computes diffs between world state versions (C7 §45-47).

    Usage:
        engine = WorldDiffEngine(session)
        diff = await engine.compute_diff(
            world_instance_id="wi_1",
            before_version=1,
            after_version=5,
        )
        for change in diff.changes:
            print(f"{change.change_type}: {change.target}")
    """

    def __init__(self, session) -> None:
        self._session = session
        self._state_mgr = WorldStateManager(session)

    async def compute_diff(
        self,
        world_instance_id: str,
        before_version: int,
        after_version: int,
    ) -> WorldStateDiff:
        """Compute the diff between two state versions (C7 §45-46).

        Args:
            world_instance_id: The world instance.
            before_version: The earlier state version.
            after_version: The later state version.

        Returns:
            WorldStateDiff with all changes between the two versions.
        """
        before_state = await self._state_mgr.get_state_at_version(
            world_instance_id, before_version,
        )
        after_state = await self._state_mgr.get_state_at_version(
            world_instance_id, after_version,
        )

        if not before_state or not after_state:
            return WorldStateDiff(
                world_id=world_instance_id,
                before_snapshot_id=str(before_version),
                after_snapshot_id=str(after_version),
                changes=[],
                total_changes=0,
            )

        # Compute diffs for each state dimension
        dimensions = [
            ("filesystem", before_state.filesystem_state, after_state.filesystem_state),
            ("database", before_state.database_state, after_state.database_state),
            ("browser", before_state.browser_state, after_state.browser_state),
            ("application", before_state.application_state, after_state.application_state),
            ("environment", before_state.environment_variables, after_state.environment_variables),
            ("network", before_state.network_state, after_state.network_state),
        ]

        all_changes: list[WorldChange] = []

        for dim_name, before_dict, after_dict in dimensions:
            dim_diff = self._diff_dicts(dim_name, before_dict, after_dict)
            all_changes.extend(self._dimension_to_changes(dim_diff))

        return WorldStateDiff(
            world_id=world_instance_id,
            before_snapshot_id=str(before_version),
            after_snapshot_id=str(after_version),
            changes=all_changes,
            total_changes=len(all_changes),
        )

    async def compute_diff_from_changes(
        self,
        world_instance_id: str,
        from_version: int,
        to_version: int,
    ) -> list[dict[str, Any]]:
        """Get the recorded changes between two versions.

        Unlike compute_diff (which compares state snapshots), this
        returns the actual change records logged during execution.
        """
        all_changes = await self._state_mgr.get_all_changes(
            world_instance_id, limit=1000,
        )

        # Filter changes that fall within the version range
        relevant: list[dict[str, Any]] = []
        for change in all_changes:
            if change.state_version_id:
                # Load the version to check its number
                version_state = await self._state_mgr.get_state_at_version(
                    world_instance_id,
                    from_version,
                )
                # Simplified: include all changes for now
                relevant.append({
                    "change_type": change.change_type,
                    "component": change.component,
                    "target": change.target,
                    "reversibility": change.reversibility,
                    "created_at": change.created_at.isoformat() if change.created_at else None,
                })

        return relevant

    def _diff_dicts(
        self,
        dimension: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> StateDimensionDiff:
        """Compute the diff between two dicts for a state dimension."""
        before_keys = set(before.keys())
        after_keys = set(after.keys())

        added_keys = after_keys - before_keys
        removed_keys = before_keys - after_keys
        common_keys = before_keys & after_keys

        added = {k: after[k] for k in added_keys}
        removed = {k: before[k] for k in removed_keys}
        modified = {}
        unchanged = 0

        for k in common_keys:
            if before[k] != after[k]:
                modified[k] = {
                    "before": before[k],
                    "after": after[k],
                }
            else:
                unchanged += 1

        return StateDimensionDiff(
            dimension=dimension,
            added=added,
            removed=removed,
            modified=modified,
            unchanged_count=unchanged,
        )

    def _dimension_to_changes(
        self, dim: StateDimensionDiff,
    ) -> list[WorldChange]:
        """Convert a StateDimensionDiff to a list of WorldChange objects."""
        changes: list[WorldChange] = []

        # Map dimension to change type prefix
        type_map = {
            "filesystem": {
                "added": WorldChangeType.FILE_CREATED,
                "removed": WorldChangeType.FILE_DELETED,
                "modified": WorldChangeType.FILE_MODIFIED,
            },
            "database": {
                "added": WorldChangeType.DATABASE_ROW_CREATED,
                "removed": WorldChangeType.DATABASE_ROW_DELETED,
                "modified": WorldChangeType.DATABASE_ROW_UPDATED,
            },
            "browser": {
                "added": WorldChangeType.BROWSER_NAVIGATED,
                "removed": WorldChangeType.BROWSER_NAVIGATED,
                "modified": WorldChangeType.STATE_MUTATED,
            },
        }

        prefix = type_map.get(dim.dimension, {})

        for key, value in dim.added.items():
            changes.append(WorldChange(
                change_type=prefix.get("added", WorldChangeType.STATE_MUTATED),
                component=dim.dimension,
                target=key,
                after={"value": value} if not isinstance(value, dict) else value,
                reversibility=WorldActionReversibility.REVERSIBLE,
            ))

        for key, value in dim.removed.items():
            changes.append(WorldChange(
                change_type=prefix.get("removed", WorldChangeType.STATE_MUTATED),
                component=dim.dimension,
                target=key,
                before={"value": value} if not isinstance(value, dict) else value,
                reversibility=WorldActionReversibility.PARTIALLY_REVERSIBLE,
            ))

        for key, diff in dim.modified.items():
            changes.append(WorldChange(
                change_type=prefix.get("modified", WorldChangeType.STATE_MUTATED),
                component=dim.dimension,
                target=key,
                before=diff.get("before"),
                after=diff.get("after"),
                reversibility=WorldActionReversibility.REVERSIBLE,
            ))

        return changes

    @staticmethod
    def summarize_diff(diff: WorldStateDiff) -> dict[str, Any]:
        """Generate a human-readable summary of a diff."""
        by_component: dict[str, int] = {}
        by_type: dict[str, int] = {}
        irreversible_count = 0

        for change in diff.changes:
            comp = change.component
            by_component[comp] = by_component.get(comp, 0) + 1

            ct = change.change_type.value if hasattr(change.change_type, "value") else str(change.change_type)
            by_type[ct] = by_type.get(ct, 0) + 1

            rev = change.reversibility.value if hasattr(change.reversibility, "value") else str(change.reversibility)
            if rev == WorldActionReversibility.IRREVERSIBLE.value:
                irreversible_count += 1

        return {
            "total_changes": diff.total_changes,
            "by_component": by_component,
            "by_change_type": by_type,
            "irreversible_actions": irreversible_count,
            "before_version": diff.before_snapshot_id,
            "after_version": diff.after_snapshot_id,
        }