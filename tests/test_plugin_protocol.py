"""Tests for PluginProtocol, AgentContext, HealthStatus."""

from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol


class TestHealthStatus:
    def test_default_status_is_ok(self):
        hs = HealthStatus()
        assert hs.status == "ok"
        assert hs.metrics == {}
        assert hs.alerts == []

    def test_warning_status_with_alerts(self):
        hs = HealthStatus(status="warning", alerts=["low memory"])
        assert hs.status == "warning"
        assert len(hs.alerts) == 1


class TestAgentContext:
    def test_required_fields(self):
        ctx = AgentContext(
            agent_name="test",
            agent_id="agent-001",
            evolution_mode="specified",
            workspace_path=Path("/tmp/ws"),
            config={"llm": {"model": "test"}},
            kernel_version="0.6.0",
        )
        assert ctx.agent_name == "test"
        assert ctx.evolution_mode == "specified"
        assert ctx.kernel_version == "0.6.0"


class TestPluginProtocol:
    def test_minimal_plugin_isinstance_check(self):
        class MinimalPlugin:
            def initialize(self, ctx): pass
            def shutdown(self): pass
            def health_check(self): return HealthStatus()
            def snapshot(self): return {}
            def restore(self, data): pass
            def on_cycle_start(self, cycle): pass
            def on_cycle_end(self, cycle): pass
            def enrich_prompt(self, base): return base
            def on_llm_response(self, response): pass

        plugin = MinimalPlugin()
        assert isinstance(plugin, PluginProtocol)

    def test_missing_method_fails_check(self):
        class BadPlugin:
            pass

        assert not isinstance(BadPlugin(), PluginProtocol)
