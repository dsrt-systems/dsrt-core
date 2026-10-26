"""
World Verification Hook (C7 §44, §64).

Bridges C7 World state to C6 Verification. After an agent performs
actions in a world, C6 can verify that the world reached the expected
state.

Flow (C7 §44):
    Agent requested action
        ↓
    World executed action
        ↓
    World state changed?
        ↓
    Expected state?
        ↓
    Verification: PASS / FAIL

This hook is called by the C6 VerificationEngine as a check type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import VerificationStatus
from schemas.domain.verification import VerificationCheckResult, VerificationPolicy

from core.observability.logging import get_logger
from core.verification.checks.base import BaseCheck
from core.worlds.state.diffs import WorldDiffEngine
from core.worlds.state.state_manager import WorldStateManager


logger = get_logger("dsrt.worlds.verification")


@dataclass
class WorldVerificationResult:
    """Result of verifying world state after an action."""
    verified: bool
    expected_state: dict[str, Any] = field(default_factory=dict)
    actual_state: dict[str, Any] = field(default_factory=dict)
    changes_detected: int = 0
    mismatches: list[str] = field(default_factory=list)
    details: str = ""


class WorldVerificationHook(BaseCheck):
    """C6 verification check for world state (C7 §44).

    Verifies that the world reached the expected state after
    an agent's actions. Plugs into the C6 VerificationEngine
    as a standard check.

    Expected inputs:
      - inputs["world_instance_id"]: The world to verify
      - inputs["expected_state"]: Dict of expected state values
      - inputs["before_version"]: State version before the action
      - inputs["after_version"]: State version after the action (optional)
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        self._session = session

    @property
    def check_type(self) -> str:
        return "WORLD_STATE_VERIFIED"

    @property
    def evaluator_type(self) -> str:
        return "deterministic"

    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ) -> VerificationCheckResult:
        """Verify world state against expected values (C7 §44)."""
        world_instance_id = inputs.get("world_instance_id")
        expected_state = inputs.get("expected_state", {})

        if not world_instance_id:
            return self._inconclusive(
                summary="No world_instance_id provided for world verification.",
                details={"reason": "missing_world_instance_id"},
            )

        if not expected_state:
            return self._inconclusive(
                summary="No expected_state provided for world verification.",
                details={"reason": "missing_expected_state"},
            )

        if not self._session:
            return self._inconclusive(
                summary="World verification requires a database session.",
            )

        # Get current world state
        state_mgr = WorldStateManager(self._session)
        current_state = await state_mgr.get_current_state(world_instance_id)

        if not current_state:
            return self._failed(
                summary=f"No state found for world '{world_instance_id}'.",
                details={"world_instance_id": world_instance_id},
            )

        # Verify expected state against actual state
        mismatches: list[str] = []
        actual_values: dict[str, Any] = {}

        for key, expected_value in expected_state.items():
            actual_value = self._get_nested_value(
                self._state_to_dict(current_state), key,
            )
            actual_values[key] = actual_value

            if actual_value != expected_value:
                mismatches.append(
                    f"State '{key}': expected {expected_value!r}, "
                    f"got {actual_value!r}"
                )

        # Compute diff if before/after versions provided
        changes_detected = 0
        before_version = inputs.get("before_version")
        after_version = inputs.get("after_version")

        if before_version is not None and after_version is not None:
            diff_engine = WorldDiffEngine(self._session)
            diff = await diff_engine.compute_diff(
                world_instance_id, before_version, after_version,
            )
            changes_detected = diff.total_changes

        if mismatches:
            return self._failed(
                summary=(
                    f"World state verification failed: "
                    f"{len(mismatches)} mismatch(es)."
                ),
                details={
                    "mismatches": mismatches,
                    "expected": expected_state,
                    "actual": actual_values,
                    "changes_detected": changes_detected,
                },
            )

        return self._passed(
            summary=(
                f"World state verified. {len(expected_state)} check(s) passed, "
                f"{changes_detected} change(s) detected."
            ),
            details={
                "expected": expected_state,
                "actual": actual_values,
                "changes_detected": changes_detected,
            },
        )

    async def verify_action_effect(
        self,
        world_instance_id: str,
        action_description: str,
        expected_changes: dict[str, Any],
    ) -> WorldVerificationResult:
        """Verify that a specific action produced the expected world changes.

        This is a higher-level verification used by C6 after tool execution.

        Args:
            world_instance_id: The world where the action occurred.
            action_description: Human-readable action description.
            expected_changes: Dict of expected state changes.

        Returns:
            WorldVerificationResult with pass/fail and details.
        """
        if not self._session:
            return WorldVerificationResult(
                verified=False,
                details="No database session available.",
            )

        state_mgr = WorldStateManager(self._session)
        current_state = await state_mgr.get_current_state(world_instance_id)

        if not current_state:
            return WorldVerificationResult(
                verified=False,
                details=f"No state for world '{world_instance_id}'.",
            )

        state_dict = self._state_to_dict(current_state)
        mismatches: list[str] = []
        actual: dict[str, Any] = {}

        for key, expected in expected_changes.items():
            actual_val = self._get_nested_value(state_dict, key)
            actual[key] = actual_val
            if actual_val != expected:
                mismatches.append(
                    f"'{key}': expected {expected!r}, got {actual_val!r}"
                )

        return WorldVerificationResult(
            verified=len(mismatches) == 0,
            expected_state=expected_changes,
            actual_state=actual,
            changes_detected=current_state.version,
            mismatches=mismatches,
            details=(
                f"Action '{action_description}': "
                f"{'PASS' if not mismatches else 'FAIL — ' + '; '.join(mismatches)}"
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _state_to_dict(state) -> dict[str, Any]:
        """Convert a WorldStateVersionORM to a flat dict for verification."""
        return {
            "filesystem": state.filesystem_state or {},
            "database": state.database_state or {},
            "browser": state.browser_state or {},
            "application": state.application_state or {},
            "environment": state.environment_variables or {},
            "network": state.network_state or {},
            "packages": state.installed_packages or [],
            "version": state.version,
        }

    @staticmethod
    def _get_nested_value(data: dict[str, Any], path: str) -> Any:
        """Get a value from a nested dict using dot-notation path.

        Handles keys that contain dots (e.g., 'report.md') by trying
        progressively longer key segments at each level.
        """
        if not path:
            return data
        if not isinstance(data, dict):
            return None

        segments = path.split(".")

        # Greedy matching: at each level, try the longest possible key first
        def _resolve(d: Any, segs: list[str]) -> Any:
            if not segs:
                return d
            if not isinstance(d, dict):
                return None

            # Try consuming 1, 2, 3, ... segments as the key
            for i in range(1, len(segs) + 1):
                candidate_key = ".".join(segs[:i])
                if candidate_key in d:
                    result = _resolve(d[candidate_key], segs[i:])
                    if result is not None:
                        return result
                    # If deeper resolution failed, try a longer key
            return None

        return _resolve(data, segments)