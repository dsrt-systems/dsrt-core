"""Unit tests for Environment lifecycle state machine (C3 §35)."""

from __future__ import annotations

import pytest

from core.api.errors.exceptions import ValidationError
from core.environments.lifecycle import (
    EnvironmentStatus,
    is_terminal_environment_status,
    validate_environment_transition,
)


class TestEnvironmentLifecycle:
    def test_valid_full_lifecycle(self):
        transitions = [
            (EnvironmentStatus.REQUESTED, EnvironmentStatus.PROVISIONING),
            (EnvironmentStatus.PROVISIONING, EnvironmentStatus.READY),
            (EnvironmentStatus.READY, EnvironmentStatus.ACTIVE),
            (EnvironmentStatus.ACTIVE, EnvironmentStatus.IDLE),
            (EnvironmentStatus.IDLE, EnvironmentStatus.ACTIVE),
            (EnvironmentStatus.ACTIVE, EnvironmentStatus.TERMINATING),
            (EnvironmentStatus.TERMINATING, EnvironmentStatus.TERMINATED),
        ]
        for current, target in transitions:
            validate_environment_transition(current, target)

    def test_provisioning_can_fail(self):
        validate_environment_transition(
            EnvironmentStatus.PROVISIONING, EnvironmentStatus.FAILED,
        )

    def test_active_can_fail(self):
        validate_environment_transition(
            EnvironmentStatus.ACTIVE, EnvironmentStatus.FAILED,
        )

    def test_invalid_transition_raises(self):
        with pytest.raises(ValidationError):
            validate_environment_transition(
                EnvironmentStatus.TERMINATED, EnvironmentStatus.ACTIVE,
            )

    def test_cannot_skip_provisioning(self):
        with pytest.raises(ValidationError):
            validate_environment_transition(
                EnvironmentStatus.REQUESTED, EnvironmentStatus.ACTIVE,
            )

    def test_same_status_is_noop(self):
        validate_environment_transition(
            EnvironmentStatus.ACTIVE, EnvironmentStatus.ACTIVE,
        )

    def test_terminal_states(self):
        assert is_terminal_environment_status(EnvironmentStatus.TERMINATED)
        assert is_terminal_environment_status(EnvironmentStatus.FAILED)
        assert not is_terminal_environment_status(EnvironmentStatus.ACTIVE)
        assert not is_terminal_environment_status(EnvironmentStatus.READY)