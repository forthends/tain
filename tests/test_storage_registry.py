"""Tests for the storage registry path resolution."""

import pytest
import tempfile
import os
from pathlib import Path
from tain_agent.storage_registry import (
    resolve_content_path,
    STORAGE_SCHEMA,
    WORKSPACE_DIRS,
    get_schema_description,
)


class TestResolveContentPath:
    def test_normal_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir).resolve() / "agent_workspace" / "test_agent"
            ws.mkdir(parents=True)
            result = resolve_content_path(ws, "poem", "spring.md")
            assert result.name == "spring.md"
            assert "poetry" in str(result)

    def test_unknown_type_falls_back_to_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir).resolve() / "agent_workspace" / "test_agent"
            ws.mkdir(parents=True)
            result = resolve_content_path(ws, "nonexistent_type", "data.txt")
            assert "files" in str(result)

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir).resolve() / "agent_workspace" / "test_agent"
            ws.mkdir(parents=True)
            with pytest.raises(ValueError):
                resolve_content_path(ws, "poem", "../escape.md")

    def test_absolute_filename_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir).resolve() / "agent_workspace" / "test_agent"
            ws.mkdir(parents=True)
            with pytest.raises(ValueError):
                resolve_content_path(ws, "poem", "/etc/passwd")

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir).resolve() / "agent_workspace" / "test_agent"
            ws.mkdir(parents=True)

            # Create a symlink within the workspace
            outside = Path(tmpdir).resolve() / "outside_dir"
            outside.mkdir()
            symlink_path = ws / "knowledge" / "escape_link"
            symlink_path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(str(outside), str(symlink_path))

            with pytest.raises(ValueError, match="Symlink|escape"):
                resolve_content_path(ws, "knowledge", "escape_link/data.txt")

            symlink_path.unlink()

    def test_valid_path_within_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir).resolve() / "agent_workspace" / "test_agent"
            ws.mkdir(parents=True)
            result = resolve_content_path(ws, "knowledge", "research_notes.md")
            resolved_ws = ws.resolve()
            assert str(result.resolve().parent).startswith(str(resolved_ws))

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir).resolve() / "agent_workspace" / "test_agent"
            ws.mkdir(parents=True)
            result = resolve_content_path(ws, "poem", "subdir/nested/poem.txt")
            assert result.parent.exists()


class TestStorageSchema:
    def test_all_types_have_subdirs(self):
        for ctype, subdir in STORAGE_SCHEMA.items():
            assert isinstance(subdir, str)
            assert len(subdir) > 0

    def test_workspace_dirs_listed(self):
        assert len(WORKSPACE_DIRS) > 0
        for d in WORKSPACE_DIRS:
            assert d.endswith("/")

    def test_get_schema_description(self):
        desc = get_schema_description()
        assert "poem" in desc or "knowledge" in desc
        assert "→" in desc
