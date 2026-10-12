"""Unit tests for filesystem built-in tool contracts (C3.8)."""

from __future__ import annotations

import pytest

from core.tools import DSRTTool
from core.tools.builtins import (
    FilesystemDeleteTool,
    FilesystemListTool,
    FilesystemMoveTool,
    FilesystemPromoteToArtifactTool,
    FilesystemReadTool,
    FilesystemStatTool,
    FilesystemWriteTool,
)


class TestFilesystemToolContracts:
    @pytest.mark.parametrize("tool_cls", [
        FilesystemReadTool,
        FilesystemWriteTool,
        FilesystemListTool,
        FilesystemDeleteTool,
        FilesystemMoveTool,
        FilesystemStatTool,
        FilesystemPromoteToArtifactTool,
    ])
    def test_satisfies_dsrt_tool_protocol(self, tool_cls):
        tool = tool_cls()
        assert isinstance(tool, DSRTTool)
        assert tool.identity.contract_version == "1.0"
        assert tool.identity.version == "1.0.0"
        assert tool.identity.category == "filesystem"

    @pytest.mark.parametrize("tool_cls", [
        FilesystemReadTool,
        FilesystemWriteTool,
        FilesystemListTool,
        FilesystemDeleteTool,
        FilesystemMoveTool,
        FilesystemStatTool,
        FilesystemPromoteToArtifactTool,
    ])
    def test_has_manifest_with_capabilities(self, tool_cls):
        tool = tool_cls()
        assert len(tool.manifest.capabilities) > 0

    @pytest.mark.parametrize("tool_cls", [
        FilesystemReadTool,
        FilesystemWriteTool,
        FilesystemListTool,
        FilesystemDeleteTool,
        FilesystemMoveTool,
        FilesystemStatTool,
        FilesystemPromoteToArtifactTool,
    ])
    def test_has_input_and_output_schema(self, tool_cls):
        tool = tool_cls()
        assert tool.manifest.input_schema
        assert tool.manifest.output_schema

    def test_read_is_low_risk(self):
        assert FilesystemReadTool.manifest.risk_level.value == "low"

    def test_write_is_medium_risk(self):
        assert FilesystemWriteTool.manifest.risk_level.value == "medium"

    def test_read_is_read_side_effect(self):
        assert FilesystemReadTool.manifest.side_effect.value == "READ"

    def test_write_is_write_side_effect(self):
        assert FilesystemWriteTool.manifest.side_effect.value == "WRITE"