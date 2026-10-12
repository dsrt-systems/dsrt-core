"""Unit tests for Tool Execution Engine components (C3 §16-19)."""

from __future__ import annotations

import pytest

from schemas.domain.enums import ToolExecutionStatus

from core.api.errors.exceptions import ValidationError
from core.tools.execution.lifecycle import (
    is_terminal,
    validate_tool_execution_transition,
)
from core.tools.execution.impl_loader import load_tool_implementation
from core.tools.observations.normalizer import (
    normalize_output,
    redact_secrets,
    redact_secrets_in_dict,
)


class TestToolExecutionLifecycle:
    def test_valid_full_lifecycle(self):
        transitions = [
            (ToolExecutionStatus.REQUESTED, ToolExecutionStatus.AUTHORIZED),
            (ToolExecutionStatus.AUTHORIZED, ToolExecutionStatus.STARTED),
            (ToolExecutionStatus.STARTED, ToolExecutionStatus.RUNNING),
            (ToolExecutionStatus.RUNNING, ToolExecutionStatus.OBSERVING),
            (ToolExecutionStatus.OBSERVING, ToolExecutionStatus.COMPLETED),
        ]
        for current, target in transitions:
            validate_tool_execution_transition(current, target)

    def test_valid_failure_from_running(self):
        validate_tool_execution_transition(
            ToolExecutionStatus.RUNNING, ToolExecutionStatus.FAILED,
        )

    def test_valid_cancellation(self):
        validate_tool_execution_transition(
            ToolExecutionStatus.RUNNING, ToolExecutionStatus.CANCELLING,
        )
        validate_tool_execution_transition(
            ToolExecutionStatus.CANCELLING, ToolExecutionStatus.CANCELLED,
        )

    def test_invalid_transition_raises(self):
        with pytest.raises(ValidationError):
            validate_tool_execution_transition(
                ToolExecutionStatus.COMPLETED, ToolExecutionStatus.RUNNING,
            )

    def test_invalid_skip_raises(self):
        with pytest.raises(ValidationError):
            validate_tool_execution_transition(
                ToolExecutionStatus.REQUESTED, ToolExecutionStatus.COMPLETED,
            )

    def test_same_status_is_noop(self):
        validate_tool_execution_transition(
            ToolExecutionStatus.RUNNING, ToolExecutionStatus.RUNNING,
        )

    def test_terminal_states(self):
        assert is_terminal(ToolExecutionStatus.COMPLETED) is True
        assert is_terminal(ToolExecutionStatus.FAILED) is True
        assert is_terminal(ToolExecutionStatus.CANCELLED) is True
        assert is_terminal(ToolExecutionStatus.RUNNING) is False
        assert is_terminal(ToolExecutionStatus.REQUESTED) is False


class TestImplLoader:
    def test_load_nonexistent_module_raises(self):
        from core.tools.errors import ToolRuntimeError
        with pytest.raises(ToolRuntimeError, match="Cannot import"):
            load_tool_implementation("nonexistent.module:FakeTool")

    def test_load_invalid_format_raises(self):
        from core.tools.errors import ToolRuntimeError
        with pytest.raises(ToolRuntimeError, match="Invalid implementation_class"):
            load_tool_implementation("NoDotsOrColons")

    def test_load_nonexistent_class_raises(self):
        from core.tools.errors import ToolRuntimeError
        with pytest.raises(ToolRuntimeError, match="not found"):
            load_tool_implementation("core.tools.execution.engine:NonExistentClass")


class TestSecretRedaction:
    def test_redacts_openai_key(self):
        text = "My key is sk-abc123def456ghi789jkl012mno345pqr678"
        result = redact_secrets(text)
        assert "sk-abc123" not in result
        assert "***REDACTED***" in result

    def test_redacts_api_key_pattern(self):
        text = 'api_key: "abcdef1234567890abcdef"'
        result = redact_secrets(text)
        assert "abcdef1234567890" not in result

    def test_preserves_safe_text(self):
        text = "The research found 42 sources about quantum computing."
        result = redact_secrets(text)
        assert result == text

    def test_redacts_nested_dict(self):
        data = {
            "result": "ok",
            "config": {"api_key": "sk-abc123def456ghi789jkl012mno345pqr678"},
        }
        result = redact_secrets_in_dict(data)
        assert "sk-abc123" not in str(result)
        assert result["result"] == "ok"


class TestOutputNormalizer:
    def test_string_output(self):
        obs = normalize_output(
            "Hello world",
            tool_slug="test.tool",
            tool_execution_id="tex_test",
            execution_id="exe_test",
        )
        assert len(obs) == 1
        assert obs[0].observation_type.value == "TEXT"
        assert obs[0].content == "Hello world"

    def test_dict_output(self):
        obs = normalize_output(
            {"key": "value", "count": 42},
            tool_slug="test.tool",
            tool_execution_id="tex_test",
            execution_id="exe_test",
        )
        assert len(obs) == 1
        assert obs[0].observation_type.value == "STRUCTURED_DATA"

    def test_none_output(self):
        obs = normalize_output(
            None,
            tool_slug="test.tool",
            tool_execution_id="tex_test",
            execution_id="exe_test",
        )
        assert len(obs) == 0

    def test_truncation_on_large_output(self):
        large_text = "x" * (10 * 1024 * 1024)  # 10 MB
        obs = normalize_output(
            large_text,
            tool_slug="test.tool",
            tool_execution_id="tex_test",
            execution_id="exe_test",
            max_bytes=1024,
        )
        assert len(obs) == 1
        assert obs[0].truncated is True

    def test_provenance_attached(self):
        obs = normalize_output(
            "test",
            tool_slug="web.search",
            tool_execution_id="tex_123",
            execution_id="exe_456",
        )
        assert obs[0].provenance["tool_execution_id"] == "tex_123"
        assert obs[0].provenance["execution_id"] == "exe_456"