"""Tests for ToolPlugin and ClosedForgeCycle."""

import tempfile
from pathlib import Path

import pytest

from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.tool.forge_cycle import (
    ClosedForgeCycle, ImprovementSpec, CycleStage, ForgeCycleResult,
)


@pytest.fixture
def agent_context(tmp_path):
    """Create an AgentContext for testing."""
    return AgentContext("test", "a1", "specified", tmp_path, {}, "0.6.0")


@pytest.fixture
def tool_plugin():
    """Create a fresh ToolPlugin instance."""
    return ToolPlugin()


class TestToolPlugin:
    def _make_ctx(self, tmpdir):
        return AgentContext("test", "a1", "specified", Path(tmpdir), {}, "0.6.0")

    def test_satisfies_protocol(self):
        assert isinstance(ToolPlugin(), PluginProtocol)

    def test_initializes_with_primal_tools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = ToolPlugin()
            plugin.initialize(self._make_ctx(tmpdir))
            assert plugin._registry is not None
            tools = plugin.list_tools()
            assert len(tools) > 0


class TestClosedForgeCycle:
    def test_cycle_stops_at_generate_without_code_or_llm(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = ToolPlugin()
            plugin.initialize(AgentContext("test", "a1", "specified", Path(tmpdir), {}, "0.6.0"))
            spec = ImprovementSpec("test_cap", "A test capability", function_name="test_tool")
            result = plugin.forge_cycle(spec, code=None, llm_backend=None)
            assert not result.success

    def test_cycle_with_provided_code(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = ToolPlugin()
            plugin.initialize(AgentContext("test", "a1", "specified", Path(tmpdir), {}, "0.6.0"))
            spec = ImprovementSpec("test_cap", "desc", function_name="test_tool")
            code = "def test_tool(**kwargs):\n    return {'success': True}"
            result = plugin.forge_cycle(spec, code=code, llm_backend=None)
            gen_stage = [s for s in result.stages if s.stage == CycleStage.GENERATE]
            assert len(gen_stage) > 0
            assert gen_stage[0].success


class TestToolPluginNewMethods:
    """Tests for list_forged, get_sandbox_allowlist, forge action param, and rollback."""

    def test_list_forged_returns_forged_tools(self, tool_plugin, agent_context):
        """list_forged() returns dict of tools created by forge."""
        tool_plugin.initialize(agent_context)
        result = tool_plugin.list_forged()
        assert isinstance(result, dict)
        # Initially empty — no tools forged yet
        assert result == {}

    def test_get_sandbox_allowlist_returns_list(self, tool_plugin, agent_context):
        """get_sandbox_allowlist() returns the current sandbox allowlist."""
        tool_plugin.initialize(agent_context)
        allowlist = tool_plugin.get_sandbox_allowlist()
        assert isinstance(allowlist, list)

    def test_forge_action_param_supports_update(self, tool_plugin, agent_context, tmp_path):
        """forge() with action='update' updates an existing forged tool."""
        tool_plugin.initialize(agent_context)
        # Forge a tool first
        code = "def hello(): return 'hello'"
        r1 = tool_plugin.forge("test_tool", "A test tool", code, {"action": "create"})
        assert r1.get("success") is True
        # Update it
        code2 = "def hello(): return 'updated'"
        r2 = tool_plugin.forge("test_tool", "Updated test tool", code2, {"action": "update"})
        assert r2.get("success") is True

    def test_rollback_removes_forged_tool(self, tool_plugin, agent_context):
        """rollback() removes a forged tool."""
        tool_plugin.initialize(agent_context)
        code = "def temp_tool(): return 'temp'"
        tool_plugin.forge("temp_tool", "Temporary", code, {"action": "create"})
        assert "temp_tool" in tool_plugin.list_forged()
        result = tool_plugin.rollback("temp_tool")
        assert result.get("success") is True
        assert "temp_tool" not in tool_plugin.list_forged()
