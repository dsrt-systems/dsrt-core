"""
Unit tests for SDK adapters and in-memory state.

Note: ToolSDKImpl (C3) and MemorySDKImpl (C4) are no longer stubs — they are
live, production-grade implementations tested in:
  - tests/unit/test_tool_execution_engine.py
  - tests/unit/test_memory_sdk_impl.py
"""

from __future__ import annotations

import pytest

from sdk.agent.adapters import StateSDKImpl


class TestStateSDK:
    """Tests for the in-memory working state SDK adapter."""

    @pytest.mark.asyncio
    async def test_state_roundtrip(self) -> None:
        state_sdk = StateSDKImpl()
        assert await state_sdk.get("key") is None

        await state_sdk.set("key", "value")
        assert await state_sdk.get("key") == "value"

        await state_sdk.delete("key")
        assert await state_sdk.get("key") is None

    @pytest.mark.asyncio
    async def test_state_merge_and_snapshot(self) -> None:
        state_sdk = StateSDKImpl()
        await state_sdk.set_many({"a": 1, "b": 2})

        snapshot = await state_sdk.snapshot()
        assert snapshot == {"a": 1, "b": 2}

        await state_sdk.clear()
        assert await state_sdk.snapshot() == {}