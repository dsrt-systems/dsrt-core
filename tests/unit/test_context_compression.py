"""Unit tests for Context Compression (C4 §29)."""

from __future__ import annotations

import pytest

from schemas.domain.enums import MessageRole
from schemas.domain.model_fabric import ModelMessage

from core.context.compression import ContextCompressor


class TestContextCompressor:
    def test_compress_history_when_under_budget_is_noop(self):
        messages = [
            ModelMessage(role=MessageRole.USER, content="Hello"),
            ModelMessage(role=MessageRole.ASSISTANT, content="Hi there"),
        ]
        compressed, was_compressed = ContextCompressor.compress_history(messages, target_tokens=1000)
        assert was_compressed is False
        assert len(compressed) == 2

    def test_compress_history_when_over_budget(self):
        messages = [
            ModelMessage(role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT, content=f"Turn {i}: " + "words " * 50)
            for i in range(10)
        ]

        compressed, was_compressed = ContextCompressor.compress_history(messages, target_tokens=100)
        assert was_compressed is True
        assert len(compressed) <= 3
        assert "[CONTEXT COMPRESSED]" in str(compressed[0].content)

    def test_summarize_working_state(self):
        # Value length = 600 chars, which exceeds max 500 chars limit per value
        state = {f"key_{i}": "val_" * 150 for i in range(20)}
        summary, was_compressed = ContextCompressor.summarize_working_state(state, max_keys=5)
        assert was_compressed is True
        assert len(summary) == 5
        assert "[TRUNCATED]" in str(summary["key_0"])