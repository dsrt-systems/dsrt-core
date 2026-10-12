"""Unit tests for ResourceController (C1 §33)."""

import pytest

from core.api.errors.exceptions import ResourceLimitError
from core.kernel.resources import ResourceController
from schemas.domain import ResourceLimits


class TestResourceController:
    def test_model_calls_tracked(self):
        limits = ResourceLimits(
            max_duration_seconds=100, max_model_calls=2, max_tool_calls=10, max_storage_mb=10,
        )
        ctrl = ResourceController("exe_1", limits)
        
        ctrl.track_model_call(tokens=100)
        ctrl.track_model_call(tokens=200)
        
        usage = ctrl.get_usage()
        assert usage["model_calls"] == 2
        assert usage["tokens"] == 300

    def test_model_call_limit_exceeded(self):
        limits = ResourceLimits(
            max_duration_seconds=100, max_model_calls=1, max_tool_calls=10, max_storage_mb=10,
        )
        ctrl = ResourceController("exe_1", limits)
        
        ctrl.track_model_call()
        with pytest.raises(ResourceLimitError, match="model_calls"):
            ctrl.track_model_call()

    def test_tool_calls_tracked(self):
        limits = ResourceLimits(
            max_duration_seconds=100, max_model_calls=10, max_tool_calls=2, max_storage_mb=10,
        )
        ctrl = ResourceController("exe_1", limits)
        
        ctrl.track_tool_call()
        ctrl.track_tool_call()
        
        usage = ctrl.get_usage()
        assert usage["tool_calls"] == 2

    def test_tool_call_limit_exceeded(self):
        limits = ResourceLimits(
            max_duration_seconds=100, max_model_calls=10, max_tool_calls=1, max_storage_mb=10,
        )
        ctrl = ResourceController("exe_1", limits)
        
        ctrl.track_tool_call()
        with pytest.raises(ResourceLimitError, match="tool_calls"):
            ctrl.track_tool_call()

    def test_token_limit_exceeded(self):
        limits = ResourceLimits(
            max_duration_seconds=100, max_model_calls=10, max_tool_calls=10, max_storage_mb=10, max_tokens=500
        )
        ctrl = ResourceController("exe_1", limits)
        
        ctrl.track_model_call(tokens=300)
        with pytest.raises(ResourceLimitError, match="tokens"):
            ctrl.track_model_call(tokens=300)