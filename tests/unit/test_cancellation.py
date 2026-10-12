"""Unit tests for CancellationManager (C1 §34)."""

import asyncio
import pytest

from core.kernel.cancellation import CancellationManager


@pytest.mark.asyncio
async def test_cancellation_manager_registers_token():
    mgr = CancellationManager()
    token = mgr.register("exe_1")
    
    assert isinstance(token, asyncio.Event)
    assert not token.is_set()
    assert mgr.get_token("exe_1") is token

@pytest.mark.asyncio
async def test_cancellation_manager_cancels_token():
    mgr = CancellationManager()
    token = mgr.register("exe_1")
    
    assert mgr.cancel("exe_1") is True
    assert token.is_set()

@pytest.mark.asyncio
async def test_cancellation_manager_unregister():
    mgr = CancellationManager()
    mgr.register("exe_1")
    mgr.unregister("exe_1")
    
    assert mgr.get_token("exe_1") is None
    assert mgr.cancel("exe_1") is False