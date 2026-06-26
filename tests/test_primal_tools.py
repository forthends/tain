"""Tests for primal tool discovery functions."""
import pytest
from tain_agent.tools.primal import list_available_tools, describe_tool, remember_note


class FakeRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name, fn, description, params=None):
        self._tools[name] = {
            "name": name, "description": description,
            "parameters": params or {}, "is_readonly": True,
        }

    def list_tools(self):
        return dict(self._tools)


class TestListAvailableTools:
    def test_returns_tool_list(self):
        reg = FakeRegistry()
        reg.register("read_file", lambda: None, "Read a file")
        reg.register("write_file", lambda: None, "Write a file")
        result = list_available_tools(reg)
        assert "read_file" in result
        assert "write_file" in result
        assert "Read a file" in result

    def test_handles_empty_registry(self):
        reg = FakeRegistry()
        result = list_available_tools(reg)
        assert len(result) > 0


class TestRememberNote:
    def test_saves_with_flat_params(self):
        result = remember_note(category="test", content="hello world")
        assert result["status"] == "saved"
        assert result["note"]["category"] == "test"
        assert result["note"]["content"] == "hello world"

    def test_saves_with_nested_note_key(self):
        result = remember_note(note={"category": "discovery", "content": "found something"})
        assert result["status"] == "saved"
        assert result["note"]["category"] == "discovery"
        assert result["note"]["content"] == "found something"

    def test_saves_with_kwargs(self):
        result = remember_note(category="idea", content="bright idea")
        assert result["status"] == "saved"

    def test_rejects_missing_category(self):
        result = remember_note(content="no category")
        assert result["status"] == "error"
        assert "category" in result["error"]

    def test_rejects_missing_content(self):
        result = remember_note(category="test")
        assert result["status"] == "error"
        assert "content" in result["error"]

    def test_rejects_empty_input(self):
        result = remember_note()
        assert result["status"] == "error"


class TestDescribeTool:
    def test_describes_existing_tool(self):
        reg = FakeRegistry()
        reg.register("read_file", lambda: None, "Read a file",
                     {"path": {"type": "string", "required": True}})
        result = describe_tool(reg, "read_file")
        assert "read_file" in result
        assert "Read a file" in result
        assert "path" in result
        assert "Read-only" in result

    def test_returns_error_for_unknown_tool(self):
        reg = FakeRegistry()
        result = describe_tool(reg, "nonexistent")
        assert "not found" in result.lower() or "未找到" in result
