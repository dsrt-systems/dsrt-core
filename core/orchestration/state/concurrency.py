"""
Optimistic Concurrency Control (C5 §23).

Prevents lost updates when multiple agents modify shared state
simultaneously. Uses version numbers instead of locks.

Protocol (C5 §23):
  1. Agent reads state at version N
  2. Agent computes patch
  3. Agent submits patch with expected_version=N
  4. If current version == N → apply patch, version becomes N+1
  5. If current version != N → CONFLICT → reject/retry/merge
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ConcurrencyConflict(Exception):
    """Represents a concurrency conflict when two agents modify state.

    This is an Exception (not a dataclass) because it is raised by
    OptimisticConcurrencyControl.check_version() and must be catchable
    by pytest.raises() and standard try/except blocks.
    """

    def __init__(
        self,
        expected_version: int,
        actual_version: int,
        patch_source: str = "unknown",
        patch_path: str = "",
        resolution: str = "REJECTED",
    ) -> None:
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.patch_source = patch_source
        self.patch_path = patch_path
        self.resolution = resolution
        super().__init__(self.message)

    @property
    def message(self) -> str:
        return (
            f"Concurrency conflict: expected version {self.expected_version} "
            f"but state is at version {self.actual_version}. "
            f"Patch from '{self.patch_source}' at path '{self.patch_path}' "
            f"was {self.resolution}."
        )


class OptimisticConcurrencyControl:
    """Manages optimistic concurrency for shared state updates.

    This is a pure-logic class. The SharedStateStore (state_store.py)
    uses it to validate patches before applying them.

    Usage:
        occ = OptimisticConcurrencyControl()
        occ.check_version(expected=5, actual=5)  # OK
        occ.check_version(expected=5, actual=6)  # Raises ConcurrencyConflict
    """

    @staticmethod
    def check_version(
        expected_version: int,
        actual_version: int,
        patch_source: str = "unknown",
        patch_path: str = "",
    ) -> None:
        """Verify that the expected version matches the actual version.

        Raises ConcurrencyConflict if they don't match.
        """
        if expected_version != actual_version:
            raise ConcurrencyConflict(
                expected_version=expected_version,
                actual_version=actual_version,
                patch_source=patch_source,
                patch_path=patch_path,
            )

    @staticmethod
    def can_auto_merge(
        patch_a_path: str,
        patch_b_path: str,
    ) -> bool:
        """Determine if two concurrent patches can be auto-merged.

        Two patches can be auto-merged if they modify non-overlapping
        subtrees of the state.

        Examples:
          /research/findings  +  /companies/list  → CAN merge (different subtrees)
          /research/findings  +  /research         → CANNOT merge (overlapping)
          /data/0             +  /data/1            → CAN merge (different indices)
        """
        parts_a = patch_a_path.strip("/").split("/")
        parts_b = patch_b_path.strip("/").split("/")

        # Check if one path is a prefix of the other
        min_len = min(len(parts_a), len(parts_b))
        for i in range(min_len):
            if parts_a[i] != parts_b[i]:
                return True  # Diverged — non-overlapping

        # One is a prefix of the other — overlapping
        return False

    @staticmethod
    def resolve_conflict(
        patch_a: dict[str, Any],
        patch_b: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Attempt to auto-merge two conflicting patches.

        Returns the merged state if auto-merge is possible, or None
        if manual resolution is required.
        """
        path_a = patch_a.get("path", "")
        path_b = patch_b.get("path", "")

        if OptimisticConcurrencyControl.can_auto_merge(path_a, path_b):
            # Apply both patches sequentially (order doesn't matter
            # since they're non-overlapping)
            from core.orchestration.state.patches import (
                PatchApplicationError,
                StatePatchValidator,
            )

            try:
                result = StatePatchValidator.apply_patch(
                    state,
                    path_a,
                    patch_a.get("operation", "add"),
                    patch_a.get("value"),
                )
                result = StatePatchValidator.apply_patch(
                    result,
                    path_b,
                    patch_b.get("operation", "add"),
                    patch_b.get("value"),
                )
                return result
            except PatchApplicationError:
                return None

        return None  # Cannot auto-merge