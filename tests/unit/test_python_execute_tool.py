"""Unit tests for PythonExecuteTool contract (C3.9)."""

from __future__ import annotations

import pytest

from core.tools import DSRTTool
from core.tools.builtins import PythonExecuteTool


class TestPythonExecuteToolContract:
    def test_satisfies_dsrt_tool_protocol(self):
        tool = PythonExecuteTool()
        assert isinstance(tool, DSRTTool)

    def test_identity(self):
        tool = PythonExecuteTool()
        assert tool.identity.slug == "python.execute"
        assert tool.identity.category == "python"
        assert tool.identity.contract_version == "1.0"
        assert tool.identity.version == "1.0.0"

    def test_manifest_declares_medium_risk(self):
        assert PythonExecuteTool.manifest.risk_level.value == "medium"

    def test_manifest_declares_write_side_effect(self):
        assert PythonExecuteTool.manifest.side_effect.value == "WRITE"

    def test_manifest_declares_filesystem_permission(self):
        perms = PythonExecuteTool.manifest.permissions
        assert perms.filesystem.read is True
        assert perms.filesystem.write is True

    def test_manifest_is_not_retryable(self):
        assert PythonExecuteTool.manifest.retry.allowed is False

    def test_manifest_has_input_schema(self):
        schema = PythonExecuteTool.manifest.input_schema
        assert "code" in schema["properties"]
        assert "code" in schema["required"]


class TestPythonExecuteToolBehavior:
    @pytest.mark.asyncio
    async def test_rejects_missing_code(self):
        from schemas.domain.tool import ToolContext, ToolExecutionRequest

        tool = PythonExecuteTool()
        await tool.initialize(
            ToolContext(
                execution_id="exe_x", task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test", agent_version="1.0.0",
            )
        )
        result = await tool.execute(
            ToolExecutionRequest(
                request_id="req_x",
                tool_slug="python.execute",
                execution_id="exe_x", task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test", agent_version="1.0.0",
                arguments={},
            )
        )
        assert result.status.value == "FAILED"
        assert result.errors[0].code == "TOOL_INVALID_ARGUMENT"

    @pytest.mark.asyncio
    async def test_executes_simple_code(self):
        from schemas.domain.tool import ToolContext, ToolExecutionRequest

        tool = PythonExecuteTool()
        await tool.initialize(
            ToolContext(
                execution_id="exe_test_py", task_id="tsk_test_py",
                organization_id="org_test_py",
                agent_slug="test", agent_version="1.0.0",
            )
        )
        result = await tool.execute(
            ToolExecutionRequest(
                request_id="req_py_1",
                tool_slug="python.execute",
                execution_id="exe_test_py",
                task_id="tsk_test_py",
                organization_id="org_test_py",
                agent_slug="test", agent_version="1.0.0",
                arguments={"code": "result = 10 * 10"},
            )
        )
        assert result.status.value == "COMPLETED"
        assert result.output["success"] is True
        assert result.output["result"] == 100
        assert len(result.observations) >= 1