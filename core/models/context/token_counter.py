"""
Token Counter (C2).

Provides abstract token counting for the context compiler.
"""

from __future__ import annotations

import json
from typing import Any


class TokenCounter:
    """Estimates token usage for context budgeting."""

    @staticmethod
    def count_text(text: str) -> int:
        """Fast heuristic: ~4 characters per token."""
        if not text:
            return 0
        return len(text) // 4 + 1

    @staticmethod
    def count_dict(data: dict[str, Any]) -> int:
        """Estimate tokens for a JSON object."""
        if not data:
            return 0
        text = json.dumps(data)
        return len(text) // 4 + 1

    @staticmethod
    def truncate_text(text: str, max_tokens: int) -> tuple[str, bool]:
        """Truncate text to fit within a token limit."""
        if max_tokens <= 0:
            return "", True
            
        current_tokens = TokenCounter.count_text(text)
        if current_tokens <= max_tokens:
            return text, False
            
        # Truncate by character ratio
        allowed_chars = max_tokens * 4
        # Leave room for truncation marker
        truncated = text[: max(0, allowed_chars - 10)] + "...[TRUNC]"
        return truncated, True