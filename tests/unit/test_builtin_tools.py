"""Unit tests for built-in tool manifests and contract compliance (C3.7)."""

from __future__ import annotations

import pytest

from core.tools import DSRTTool
from core.tools.builtins import HttpRequestTool, WebRetrieveTool, WebSearchTool


class TestBuiltinToolContracts:
    """Verify each built-in tool satisfies the DSRTTool protocol."""

    def test_web_search_satisfies_protocol(self):
        tool = WebSearchTool()
        assert isinstance(tool, DSRTTool)
        assert tool.identity.slug == "web.search"
        assert tool.identity.version == "1.0.0"
        assert tool.identity.contract_version == "1.0"

    def test_web_retrieve_satisfies_protocol(self):
        tool = WebRetrieveTool()
        assert isinstance(tool, DSRTTool)
        assert tool.identity.slug == "web.retrieve"

    def test_http_request_satisfies_protocol(self):
        tool = HttpRequestTool()
        assert isinstance(tool, DSRTTool)
        assert tool.identity.slug == "http.request"


class TestBuiltinToolManifests:
    def test_web_search_manifest_declares_network(self):
        manifest = WebSearchTool.manifest
        assert manifest.permissions.network.required is True
        assert manifest.permissions.network.outbound is True

    def test_web_search_declares_low_risk_read(self):
        manifest = WebSearchTool.manifest
        assert manifest.risk_level.value == "low"
        assert manifest.side_effect.value == "READ"

    def test_web_retrieve_declares_low_risk_read(self):
        manifest = WebRetrieveTool.manifest
        assert manifest.risk_level.value == "low"
        assert manifest.side_effect.value == "READ"

    def test_http_request_declares_low_risk_read(self):
        manifest = HttpRequestTool.manifest
        assert manifest.risk_level.value == "low"
        assert manifest.side_effect.value == "READ"

    def test_all_builtins_have_capabilities(self):
        for tool_cls in (WebSearchTool, WebRetrieveTool, HttpRequestTool):
            manifest = tool_cls.manifest
            assert len(manifest.capabilities) > 0, f"{tool_cls.__name__} missing capabilities"

    def test_all_builtins_have_input_schema(self):
        for tool_cls in (WebSearchTool, WebRetrieveTool, HttpRequestTool):
            manifest = tool_cls.manifest
            assert manifest.input_schema, f"{tool_cls.__name__} missing input_schema"

    def test_all_builtins_have_output_schema(self):
        for tool_cls in (WebSearchTool, WebRetrieveTool, HttpRequestTool):
            manifest = tool_cls.manifest
            assert manifest.output_schema, f"{tool_cls.__name__} missing output_schema"


class TestBuiltinToolInputValidation:
    """Verify each tool rejects invalid arguments."""

    @pytest.mark.asyncio
    async def test_web_search_rejects_missing_query(self):
        from schemas.domain.tool import ToolContext, ToolExecutionRequest

        tool = WebSearchTool()
        await tool.initialize(
            ToolContext(
                execution_id="exe_x",
                task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test_agent",
                agent_version="1.0.0",
            )
        )

        result = await tool.execute(
            ToolExecutionRequest(
                request_id="req_x",
                tool_slug="web.search",
                execution_id="exe_x",
                task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test_agent",
                agent_version="1.0.0",
                arguments={},  # Missing 'query'
            )
        )
        assert result.status.value == "FAILED"
        assert len(result.errors) == 1
        assert result.errors[0].code == "TOOL_INVALID_ARGUMENT"

    @pytest.mark.asyncio
    async def test_http_request_rejects_missing_url(self):
        from schemas.domain.tool import ToolContext, ToolExecutionRequest

        tool = HttpRequestTool()
        await tool.initialize(
            ToolContext(
                execution_id="exe_x",
                task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test_agent",
                agent_version="1.0.0",
            )
        )

        result = await tool.execute(
            ToolExecutionRequest(
                request_id="req_x",
                tool_slug="http.request",
                execution_id="exe_x",
                task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test_agent",
                agent_version="1.0.0",
                arguments={"method": "GET"},
            )
        )
        assert result.status.value == "FAILED"
        assert result.errors[0].code == "TOOL_INVALID_ARGUMENT"

    @pytest.mark.asyncio
    async def test_http_request_rejects_invalid_method(self):
        from schemas.domain.tool import ToolContext, ToolExecutionRequest

        tool = HttpRequestTool()
        await tool.initialize(
            ToolContext(
                execution_id="exe_x",
                task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test_agent",
                agent_version="1.0.0",
            )
        )

        result = await tool.execute(
            ToolExecutionRequest(
                request_id="req_x",
                tool_slug="http.request",
                execution_id="exe_x",
                task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test_agent",
                agent_version="1.0.0",
                arguments={"method": "INVALID", "url": "https://example.com"},
            )
        )
        assert result.status.value == "FAILED"
        assert result.errors[0].code == "TOOL_INVALID_ARGUMENT"

    @pytest.mark.asyncio
    async def test_http_request_rejects_file_url(self):
        from schemas.domain.tool import ToolContext, ToolExecutionRequest

        tool = HttpRequestTool()
        await tool.initialize(
            ToolContext(
                execution_id="exe_x",
                task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test_agent",
                agent_version="1.0.0",
            )
        )

        result = await tool.execute(
            ToolExecutionRequest(
                request_id="req_x",
                tool_slug="http.request",
                execution_id="exe_x",
                task_id="tsk_x",
                organization_id="org_x",
                agent_slug="test_agent",
                agent_version="1.0.0",
                arguments={"method": "GET", "url": "file:///etc/passwd"},
            )
        )
        assert result.status.value == "FAILED"
        assert result.errors[0].code == "TOOL_INVALID_ARGUMENT"


class TestBuiltinToolHealth:
    @pytest.mark.asyncio
    async def test_web_search_reports_healthy(self):
        tool = WebSearchTool()
        health = await tool.health()
        assert health.status.value == "healthy"
        assert health.tool_slug == "web.search"