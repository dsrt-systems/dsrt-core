"""Unit tests for WorkspaceManager security and isolation (C3 §24-25)."""

from __future__ import annotations

import os
import tempfile

import pytest

from core.tools.environments.workspace.manager import (
    ALLOWED_SUBDIRS,
    WorkspaceError,
    WorkspaceManager,
)


@pytest.fixture
def ws(tmp_path):
    """Create a WorkspaceManager with a temporary root."""
    return WorkspaceManager(root=str(tmp_path / "workspace"))


class TestWorkspaceCreation:
    def test_creates_workspace_with_subdirs(self, ws):
        path = ws.create_workspace("org_123", "exe_456")
        assert path.exists()
        for subdir in ALLOWED_SUBDIRS:
            assert (path / subdir).is_dir()

    def test_idempotent_creation(self, ws):
        p1 = ws.create_workspace("org_123", "exe_456")
        p2 = ws.create_workspace("org_123", "exe_456")
        assert p1 == p2

    def test_isolated_workspaces(self, ws):
        p1 = ws.create_workspace("org_123", "exe_A")
        p2 = ws.create_workspace("org_123", "exe_B")
        assert p1 != p2

    def test_destroy_workspace(self, ws):
        ws.create_workspace("org_123", "exe_456")
        assert ws.workspace_exists("org_123", "exe_456")
        ws.destroy_workspace("org_123", "exe_456")
        assert not ws.workspace_exists("org_123", "exe_456")


class TestPathResolution:
    def test_valid_working_path(self, ws):
        ws.create_workspace("org_1", "exe_1")
        real = ws.resolve_virtual_path("/workspace/working/file.txt", "org_1", "exe_1")
        assert real.name == "file.txt"
        assert "working" in str(real)

    def test_valid_input_path(self, ws):
        ws.create_workspace("org_1", "exe_1")
        real = ws.resolve_virtual_path("/workspace/input/data.csv", "org_1", "exe_1")
        assert "input" in str(real)

    def test_rejects_path_traversal(self, ws):
        ws.create_workspace("org_1", "exe_1")
        with pytest.raises(WorkspaceError, match="traversal"):
            ws.resolve_virtual_path("/workspace/working/../../../etc/passwd", "org_1", "exe_1")

    def test_rejects_absolute_after_strip(self, ws):
        ws.create_workspace("org_1", "exe_1")
        with pytest.raises(WorkspaceError):
            ws.resolve_virtual_path("/etc/passwd", "org_1", "exe_1")

    def test_rejects_invalid_subdir(self, ws):
        ws.create_workspace("org_1", "exe_1")
        with pytest.raises(WorkspaceError, match="must start with"):
            ws.resolve_virtual_path("/workspace/secret/file.txt", "org_1", "exe_1")

    def test_rejects_empty_path(self, ws):
        ws.create_workspace("org_1", "exe_1")
        with pytest.raises(WorkspaceError, match="Empty"):
            ws.resolve_virtual_path("", "org_1", "exe_1")

    def test_rejects_null_bytes(self, ws):
        ws.create_workspace("org_1", "exe_1")
        with pytest.raises(WorkspaceError, match="Null"):
            ws.resolve_virtual_path("/workspace/working/file\x00.txt", "org_1", "exe_1")

    def test_nested_paths_allowed(self, ws):
        ws.create_workspace("org_1", "exe_1")
        real = ws.resolve_virtual_path(
            "/workspace/working/reports/2024/q1/data.csv", "org_1", "exe_1",
        )
        assert real.name == "data.csv"


class TestFileOperations:
    def test_write_and_read(self, ws):
        ws.create_workspace("org_1", "exe_1")
        ws.write_file("/workspace/working/hello.txt", "Hello World", "org_1", "exe_1")
        data = ws.read_file("/workspace/working/hello.txt", "org_1", "exe_1")
        assert data == b"Hello World"

    def test_read_nonexistent_raises(self, ws):
        ws.create_workspace("org_1", "exe_1")
        with pytest.raises(WorkspaceError, match="not found"):
            ws.read_file("/workspace/working/nope.txt", "org_1", "exe_1")

    def test_list_directory(self, ws):
        ws.create_workspace("org_1", "exe_1")
        ws.write_file("/workspace/working/a.txt", "a", "org_1", "exe_1")
        ws.write_file("/workspace/working/b.txt", "b", "org_1", "exe_1")
        entries = ws.list_directory("/workspace/working", "org_1", "exe_1")
        names = [e["name"] for e in entries]
        assert "a.txt" in names
        assert "b.txt" in names

    def test_delete_file(self, ws):
        ws.create_workspace("org_1", "exe_1")
        ws.write_file("/workspace/working/temp.txt", "temp", "org_1", "exe_1")
        assert ws.delete_file("/workspace/working/temp.txt", "org_1", "exe_1")
        with pytest.raises(WorkspaceError):
            ws.read_file("/workspace/working/temp.txt", "org_1", "exe_1")

    def test_move_file(self, ws):
        ws.create_workspace("org_1", "exe_1")
        ws.write_file("/workspace/working/old.txt", "data", "org_1", "exe_1")
        ws.move_file(
            "/workspace/working/old.txt",
            "/workspace/output/new.txt",
            "org_1", "exe_1",
        )
        data = ws.read_file("/workspace/output/new.txt", "org_1", "exe_1")
        assert data == b"data"

    def test_stat_file(self, ws):
        ws.create_workspace("org_1", "exe_1")
        ws.write_file("/workspace/working/info.txt", "12345", "org_1", "exe_1")
        info = ws.stat_file("/workspace/working/info.txt", "org_1", "exe_1")
        assert info["type"] == "file"
        assert info["size_bytes"] == 5


class TestCrossExecutionIsolation:
    def test_cannot_read_other_execution(self, ws):
        ws.create_workspace("org_1", "exe_A")
        ws.create_workspace("org_1", "exe_B")
        ws.write_file("/workspace/working/secret.txt", "secret", "org_1", "exe_A")

        with pytest.raises(WorkspaceError):
            ws.read_file("/workspace/working/secret.txt", "org_1", "exe_B")