"""Tests for state machine transition validation."""

import pytest

from core.api.errors.exceptions import ValidationError
from core.kernel.lifecycle import (
    validate_execution_transition,
    validate_task_transition,
)
from schemas.domain.enums import ExecutionStatus, TaskStatus


class TestLifecycleTransitions:
    def test_valid_task_transitions(self):
        validate_task_transition(TaskStatus.CREATED, TaskStatus.QUEUED)
        validate_task_transition(TaskStatus.QUEUED, TaskStatus.EXECUTING)
        validate_task_transition(TaskStatus.EXECUTING, TaskStatus.COMPLETED)

    def test_invalid_task_transition_raises(self):
        with pytest.raises(ValidationError):
            validate_task_transition(TaskStatus.CREATED, TaskStatus.COMPLETED)

    def test_valid_execution_transitions(self):
        validate_execution_transition(
            ExecutionStatus.QUEUED, ExecutionStatus.INITIALIZING,
        )
        validate_execution_transition(
            ExecutionStatus.INITIALIZING, ExecutionStatus.RUNNING,
        )
        validate_execution_transition(
            ExecutionStatus.RUNNING, ExecutionStatus.VERIFYING,
        )
        validate_execution_transition(
            ExecutionStatus.VERIFYING, ExecutionStatus.FINALIZING,
        )
        validate_execution_transition(
            ExecutionStatus.FINALIZING, ExecutionStatus.COMPLETED,
        )

    def test_execution_cancellation_transitions(self):
        validate_execution_transition(
            ExecutionStatus.RUNNING, ExecutionStatus.CANCELLING,
        )
        validate_execution_transition(
            ExecutionStatus.CANCELLING, ExecutionStatus.CANCELLED,
        )

    def test_invalid_execution_transition_raises(self):
        with pytest.raises(ValidationError):
            validate_execution_transition(
                ExecutionStatus.QUEUED, ExecutionStatus.COMPLETED,
            )