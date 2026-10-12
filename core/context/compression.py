"""
Context Compression Engine (C4 §29-30).

Reduces conversation history and structured working state when context
approaches model token limits, preserving core objectives and recent turns.
"""

from __future__ import annotations

import json
from typing import Any

from core.models.context.token_counter import TokenCounter
from core.observability.logging import get_logger
from schemas.domain.enums import MessageRole
from schemas.domain.model_fabric import ModelMessage


logger = get_logger("dsrt.context.compression")


class ContextCompressor:
    """Compresses context payloads to fit model token budgets."""

    @staticmethod
    def compress_history(
        messages: list[ModelMessage],
        target_tokens: int,
    ) -> tuple[list[ModelMessage], bool]:
        """Compress conversation history into a concise summary + recent turns.

        Args:
            messages: Full list of conversation messages.
            target_tokens: Maximum tokens allowed for the history block.

        Returns:
            (compressed_messages, was_compressed)
        """
        if not messages:
            return [], False

        total_tokens = sum(
            TokenCounter.count_text(str(m.content)) for m in messages
        )

        if total_tokens <= target_tokens:
            return messages, False

        # Keep the 2 most recent messages intact
        recent_count = min(2, len(messages))
        recent_messages = messages[-recent_count:]
        older_messages = messages[:-recent_count]

        # Summarize older messages into a single system/user summary turn
        summary_lines = []
        for msg in older_messages:
            role_label = msg.role.value.upper()
            text = str(msg.content)[:150]  # Truncate each turn
            summary_lines.append(f"[{role_label}]: {text}")

        summary_text = "Prior Conversation Summary:\n" + "\n".join(summary_lines)

        # Truncate summary text if it still exceeds target
        summary_tokens = TokenCounter.count_text(summary_text)
        recent_tokens = sum(
            TokenCounter.count_text(str(m.content)) for m in recent_messages
        )

        available_for_summary = max(50, target_tokens - recent_tokens)
        if summary_tokens > available_for_summary:
            summary_text, _ = TokenCounter.truncate_text(
                summary_text, available_for_summary
            )

        compressed = [
            ModelMessage(
                role=MessageRole.USER,
                content=f"[CONTEXT COMPRESSED]\n{summary_text}",
            )
        ] + recent_messages

        logger.info(
            "context_history_compressed",
            original_messages=len(messages),
            compressed_messages=len(compressed),
            original_tokens=total_tokens,
            target_tokens=target_tokens,
        )

        return compressed, True

    @staticmethod
    def summarize_working_state(
        working_state: dict[str, Any],
        max_keys: int = 10,
    ) -> tuple[dict[str, Any], bool]:
        """Summarize working state dictionary by keeping key fields and truncating large values."""
        if not working_state:
            return {}, False

        compressed: dict[str, Any] = {}
        was_compressed = False

        items = list(working_state.items())[:max_keys]
        if len(working_state) > max_keys:
            was_compressed = True

        for k, v in items:
            val_str = str(v)
            if len(val_str) > 500:
                was_compressed = True
                compressed[k] = val_str[:500] + "... [TRUNCATED]"
            else:
                compressed[k] = v

        return compressed, was_compressed