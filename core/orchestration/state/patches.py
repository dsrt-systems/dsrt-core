"""
State Patch Validator (C5 §21-22).

Validates and applies JSON Pointer (RFC 6901) patches to the shared state.

Supported operations (C5 §21):
  - add: Insert a value at the given path
  - replace: Overwrite an existing value
  - remove: Delete a value at the given path

Paths use JSON Pointer syntax:
  /research/findings       → state["research"]["findings"]
  /companies/0/name        → state["companies"][0]["name"]
  /metadata                → state["metadata"]

Security:
  - Paths cannot escape the root (no '..' traversal)
  - Paths must start with '/'
  - Empty paths are rejected
"""

from __future__ import annotations

import copy
import re
from typing import Any

from schemas.domain.enums import StatePatchOperation


class PatchApplicationError(Exception):
    """Raised when a patch cannot be applied to the state."""

    def __init__(self, message: str, path: str = "", operation: str = "") -> None:
        self.path = path
        self.operation = operation
        super().__init__(message)


class StatePatchValidator:
    """Validates and applies JSON Pointer patches to a state dict.

    This is a pure-logic class with no database dependency.
    """

    # Valid JSON Pointer path pattern
    _PATH_PATTERN = re.compile(r"^(/[^/]*)*$")

    @classmethod
    def validate_path(cls, path: str) -> None:
        """Validate a JSON Pointer path.

        Raises PatchApplicationError if the path is invalid.
        """
        if not path:
            raise PatchApplicationError(
                "Patch path must not be empty.", path=path,
            )
        if not path.startswith("/"):
            raise PatchApplicationError(
                f"Patch path must start with '/': '{path}'", path=path,
            )
        if ".." in path:
            raise PatchApplicationError(
                f"Patch path cannot contain '..' (traversal): '{path}'",
                path=path,
            )
        if "//" in path:
            raise PatchApplicationError(
                f"Patch path cannot contain empty segments ('//'): '{path}'",
                path=path,
            )
        if not cls._PATH_PATTERN.match(path):
            raise PatchApplicationError(
                f"Invalid JSON Pointer path: '{path}'", path=path,
            )

    @classmethod
    def validate_operation(cls, operation: str) -> None:
        """Validate the patch operation type."""
        valid = {op.value for op in StatePatchOperation}
        if operation not in valid:
            raise PatchApplicationError(
                f"Invalid operation '{operation}'. Must be one of: {sorted(valid)}",
                operation=operation,
            )

    @classmethod
    def parse_path(cls, path: str) -> list[str]:
        """Parse a JSON Pointer path into a list of keys.

        Example: '/research/findings/0' → ['research', 'findings', '0']
        """
        cls.validate_path(path)
        # Remove leading '/' and split
        parts = path.lstrip("/").split("/")
        return [cls._unescape(p) for p in parts if p or path == "/"]

    @classmethod
    def apply_patch(
        cls,
        state: dict[str, Any],
        path: str,
        operation: str,
        value: Any = None,
    ) -> dict[str, Any]:
        """Apply a single patch to a state dict and return the new state.

        The original state is NOT mutated — a deep copy is returned.

        Args:
            state: The current state dict.
            path: JSON Pointer path (e.g., '/research/findings').
            operation: 'add', 'replace', or 'remove'.
            value: The value to set (required for 'add' and 'replace').

        Returns:
            A new state dict with the patch applied.

        Raises:
            PatchApplicationError: If the patch cannot be applied.
        """
        cls.validate_path(path)
        cls.validate_operation(operation)

        # Deep copy to avoid mutating the original
        new_state = copy.deepcopy(state)
        keys = cls.parse_path(path)

        if not keys:
            # Root-level operation
            if operation == StatePatchOperation.REPLACE.value:
                if not isinstance(value, dict):
                    raise PatchApplicationError(
                        "Root replace requires a dict value.",
                        path=path, operation=operation,
                    )
                return copy.deepcopy(value)
            elif operation == StatePatchOperation.ADD.value:
                if not isinstance(value, dict):
                    raise PatchApplicationError(
                        "Root add requires a dict value.",
                        path=path, operation=operation,
                    )
                new_state.update(value)
                return new_state
            else:
                raise PatchApplicationError(
                    "Cannot remove root state.",
                    path=path, operation=operation,
                )

        # Navigate to the parent of the target
        parent = new_state
        for key in keys[:-1]:
            parent = cls._navigate(parent, key, path)

        target_key = keys[-1]

        if operation == StatePatchOperation.ADD.value:
            cls._set_value(parent, target_key, value, path)

        elif operation == StatePatchOperation.REPLACE.value:
            if not cls._has_key(parent, target_key):
                raise PatchApplicationError(
                    f"Cannot replace non-existent path: '{path}'",
                    path=path, operation=operation,
                )
            cls._set_value(parent, target_key, value, path)

        elif operation == StatePatchOperation.REMOVE.value:
            if not cls._has_key(parent, target_key):
                raise PatchApplicationError(
                    f"Cannot remove non-existent path: '{path}'",
                    path=path, operation=operation,
                )
            cls._delete_value(parent, target_key, path)

        return new_state

    @classmethod
    def apply_patches(
        cls,
        state: dict[str, Any],
        patches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply multiple patches sequentially.

        Each patch is a dict with 'path', 'operation', and optionally 'value'.
        Patches are applied in order; each sees the result of the previous.

        Returns:
            The final state after all patches.

        Raises:
            PatchApplicationError: If any patch fails.
        """
        current = state
        for i, patch in enumerate(patches):
            path = patch.get("path", "")
            operation = patch.get("operation", "")
            value = patch.get("value")
            try:
                current = cls.apply_patch(current, path, operation, value)
            except PatchApplicationError as e:
                raise PatchApplicationError(
                    f"Patch {i} failed: {e}",
                    path=path, operation=operation,
                ) from e
        return current

    @classmethod
    def get_value(
        cls, state: dict[str, Any], path: str,
    ) -> Any:
        """Read a value from the state at the given JSON Pointer path.

        Returns None if the path does not exist.
        """
        if path == "/" or not path:
            return state

        cls.validate_path(path)
        keys = cls.parse_path(path)

        current: Any = state
        for key in keys:
            current = cls._navigate_safe(current, key)
            if current is _SENTINEL:
                return None
        return current

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _unescape(segment: str) -> str:
        """Unescape JSON Pointer special characters (RFC 6901)."""
        return segment.replace("~1", "/").replace("~0", "~")

    @staticmethod
    def _navigate(parent: Any, key: str, full_path: str) -> Any:
        """Navigate into a dict or list, raising on failure."""
        if isinstance(parent, dict):
            if key not in parent:
                raise PatchApplicationError(
                    f"Path segment '{key}' not found in dict at '{full_path}'",
                    path=full_path,
                )
            return parent[key]
        elif isinstance(parent, list):
            try:
                idx = int(key)
            except ValueError:
                raise PatchApplicationError(
                    f"Cannot use non-integer key '{key}' on list at '{full_path}'",
                    path=full_path,
                )
            if idx < 0 or idx >= len(parent):
                raise PatchApplicationError(
                    f"List index {idx} out of range at '{full_path}'",
                    path=full_path,
                )
            return parent[idx]
        else:
            raise PatchApplicationError(
                f"Cannot navigate into {type(parent).__name__} at '{full_path}'",
                path=full_path,
            )

    @staticmethod
    def _navigate_safe(parent: Any, key: str) -> Any:
        """Navigate without raising — returns _SENTINEL on failure."""
        if isinstance(parent, dict):
            return parent.get(key, _SENTINEL)
        elif isinstance(parent, list):
            try:
                idx = int(key)
                if 0 <= idx < len(parent):
                    return parent[idx]
            except (ValueError, TypeError):
                pass
        return _SENTINEL

    @staticmethod
    def _has_key(parent: Any, key: str) -> bool:
        """Check if a key exists in a dict or list."""
        if isinstance(parent, dict):
            return key in parent
        elif isinstance(parent, list):
            try:
                idx = int(key)
                return 0 <= idx < len(parent)
            except (ValueError, TypeError):
                return False
        return False

    @staticmethod
    def _set_value(parent: Any, key: str, value: Any, full_path: str) -> None:
        """Set a value in a dict or list."""
        if isinstance(parent, dict):
            parent[key] = value
        elif isinstance(parent, list):
            if key == "-":
                parent.append(value)
            else:
                try:
                    idx = int(key)
                    if idx == len(parent):
                        parent.append(value)
                    elif 0 <= idx < len(parent):
                        parent[idx] = value
                    else:
                        raise PatchApplicationError(
                            f"List index {idx} out of range at '{full_path}'",
                            path=full_path,
                        )
                except ValueError:
                    raise PatchApplicationError(
                        f"Cannot set non-integer key '{key}' on list",
                        path=full_path,
                    )
        else:
            raise PatchApplicationError(
                f"Cannot set value on {type(parent).__name__}",
                path=full_path,
            )

    @staticmethod
    def _delete_value(parent: Any, key: str, full_path: str) -> None:
        """Delete a value from a dict or list."""
        if isinstance(parent, dict):
            del parent[key]
        elif isinstance(parent, list):
            try:
                idx = int(key)
                del parent[idx]
            except (ValueError, IndexError):
                raise PatchApplicationError(
                    f"Cannot delete index '{key}' from list at '{full_path}'",
                    path=full_path,
                )


# Sentinel for missing values
_SENTINEL = object()