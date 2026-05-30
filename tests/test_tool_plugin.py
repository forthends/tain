"""Tests for ToolPlugin and ClosedForgeCycle."""

import tempfile
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.tool.forge_cycle import (
    ClosedForgeCycle, ImprovementSpec, CycleStage, ForgeCycleResult,
)


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
