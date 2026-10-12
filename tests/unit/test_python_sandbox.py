"""Unit tests for the Python Sandbox (C3 §26-27)."""

from __future__ import annotations

import pytest

from core.tools.environments.python_sandbox.sandbox import (
    PythonSandbox,
    PythonSandboxError,
)


@pytest.fixture
def sandbox(tmp_path):
    return PythonSandbox(
        max_runtime_seconds=10,
        max_memory_mb=256,
        max_output_bytes=1024 * 1024,
        max_code_bytes=64 * 1024,
        workspace_dir=tmp_path / "sandbox_root",
    )


class TestBasicExecution:
    @pytest.mark.asyncio
    async def test_simple_print(self, sandbox):
        result = await sandbox.execute("print('hello world')")
        assert result.success is True
        assert result.exit_code == 0
        assert "hello world" in result.stdout
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_captures_result_variable(self, sandbox):
        result = await sandbox.execute("result = 2 + 2")
        assert result.success is True
        assert result.result_value == 4

    @pytest.mark.asyncio
    async def test_captures_dict_result(self, sandbox):
        result = await sandbox.execute("result = {'a': 1, 'b': [2, 3]}")
        assert result.success is True
        assert result.result_value == {"a": 1, "b": [2, 3]}

    @pytest.mark.asyncio
    async def test_captures_list_result(self, sandbox):
        result = await sandbox.execute("result = [1, 2, 3, 4, 5]")
        assert result.success is True
        assert result.result_value == [1, 2, 3, 4, 5]


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_syntax_error(self, sandbox):
        result = await sandbox.execute("def broken(\n")
        assert result.success is False
        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_runtime_error(self, sandbox):
        result = await sandbox.execute("raise ValueError('boom')")
        assert result.success is False
        assert "ValueError" in result.stderr or result.error_type == "ValueError"

    @pytest.mark.asyncio
    async def test_name_error(self, sandbox):
        result = await sandbox.execute("print(undefined_variable)")
        assert result.success is False
        assert "NameError" in result.stderr or result.error_type == "NameError"


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_rejects_empty_code(self, sandbox):
        with pytest.raises(PythonSandboxError):
            await sandbox.execute("")

    @pytest.mark.asyncio
    async def test_rejects_whitespace_only(self, sandbox):
        with pytest.raises(PythonSandboxError):
            await sandbox.execute("   \n   ")

    @pytest.mark.asyncio
    async def test_rejects_oversized_code(self, tmp_path):
        tiny_sandbox = PythonSandbox(
            max_runtime_seconds=10,
            max_memory_mb=256,
            max_output_bytes=1024,
            max_code_bytes=100,  # Very small
            workspace_dir=tmp_path / "sandbox",
        )
        with pytest.raises(PythonSandboxError, match="exceeds max"):
            await tiny_sandbox.execute("x = 1\n" * 1000)


class TestTimeout:
    @pytest.mark.asyncio
    async def test_infinite_loop_times_out(self, tmp_path):
        quick_sandbox = PythonSandbox(
            max_runtime_seconds=3,
            max_memory_mb=256,
            max_output_bytes=1024 * 1024,
            max_code_bytes=64 * 1024,
            workspace_dir=tmp_path / "sandbox",
        )
        result = await quick_sandbox.execute(
            "while True:\n    pass"
        )
        assert result.timed_out is True
        assert result.success is False
        assert result.error_type == "Timeout"

    @pytest.mark.asyncio
    async def test_sleep_longer_than_timeout(self, tmp_path):
        quick_sandbox = PythonSandbox(
            max_runtime_seconds=2,
            max_memory_mb=256,
            max_output_bytes=1024 * 1024,
            max_code_bytes=64 * 1024,
            workspace_dir=tmp_path / "sandbox",
        )
        result = await quick_sandbox.execute(
            "import time\ntime.sleep(10)"
        )
        assert result.timed_out is True


class TestOutputCaps:
    @pytest.mark.asyncio
    async def test_truncates_large_output(self, tmp_path):
        small_sandbox = PythonSandbox(
            max_runtime_seconds=10,
            max_memory_mb=256,
            max_output_bytes=1024,  # Only 1 KB
            max_code_bytes=64 * 1024,
            workspace_dir=tmp_path / "sandbox",
        )
        result = await small_sandbox.execute(
            "for i in range(100000):\n    print('x' * 100)"
        )
        # Either succeeds with truncated output or times out — both are OK
        assert len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")) <= 1024 * 2


class TestIsolation:
    @pytest.mark.asyncio
    async def test_fresh_environment_per_call(self, sandbox):
        # First execution sets a variable
        result1 = await sandbox.execute("x = 42\nresult = x")
        assert result1.result_value == 42

        # Second execution must NOT see x
        result2 = await sandbox.execute("try:\n    result = x\nexcept NameError:\n    result = 'isolated'")
        assert result2.result_value == "isolated"

    @pytest.mark.asyncio
    async def test_environment_is_scrubbed(self, sandbox):
        # DSRT_SECRET_KEY should not be visible inside the sandbox
        result = await sandbox.execute(
            "import os\nresult = 'DSRT_SECRET_KEY' in os.environ"
        )
        assert result.success is True
        assert result.result_value is False