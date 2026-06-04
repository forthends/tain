"""Tests for primal tool discovery functions."""
import pytest
from tain_agent.tools.primal import list_available_tools, describe_tool


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
