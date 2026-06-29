"""Tests for AgentKernel, Dispatch, and backward-compat wrapper."""

import pytest
from pathlib import Path
from tain_agent.kernel import AgentKernel, AgentContext, HealthStatus
from tain_agent.kernel.dispatch import Dispatch, RouteNotFound


class TestDispatch:
    def test_register_and_call(self):
        d = Dispatch()
        d.register("test.event", lambda x: x * 2)
        assert d.call("test.event", 3) == 6

    def test_missing_event_returns_none(self):
        d = Dispatch()
        # RouteNotFound is raised for unregistered routes; use call_or_none for old semantics
        assert d.call_or_none("nonexistent") is None
        with pytest.raises(RouteNotFound):
            d.call("nonexistent")

    def test_handler_exception_returns_error_string(self):
        d = Dispatch()
        d.register("failing", lambda: 1 / 0)
        result = d.call("failing")
        assert result is not None
        assert "[Dispatch Error]" in result


class TestAgentKernelBackwardCompat:
    """Tests for the backward-compatible AgentKernel wrapper."""

    def _make_ctx(self):
        return AgentContext(
            agent_name="test", agent_id="a1", evolution_mode="chaos",
            workspace_path=Path("/tmp/ws"), config={}, kernel_version="0.6.0",
        )

    def _make_factory(self):
        class FakePlugin:
            version = "1.0.0"
            def initialize(self, ctx): self.ctx = ctx
            def shutdown(self): pass
            def health_check(self): return HealthStatus(status="ok")
            def snapshot(self): return {}
            def restore(self, data): pass
            def on_cycle_start(self, cycle): pass
            def on_cycle_end(self, cycle): pass
            def enrich_prompt(self, base): return base
            def on_llm_response(self, response): pass
        return {"identity": FakePlugin, "memory": FakePlugin, "tool": FakePlugin}

    def test_chaos_mode_loads_three_plugins(self):
        kernel = AgentKernel(self._make_ctx())
        kernel.load_plugins(self._make_factory())
        # Check that all three chaos-mode plugins are accessible
        assert kernel.lifecycle.get("identity") is not None
        assert kernel.lifecycle.get("memory") is not None
        assert kernel.lifecycle.get("tool") is not None

    def test_get_returns_none_for_unloaded(self):
        kernel = AgentKernel(self._make_ctx())
        kernel.load_plugins(self._make_factory())
        assert kernel.lifecycle.get("collaboration") is None

    def test_shutdown_clears_all(self):
        kernel = AgentKernel(self._make_ctx())
        kernel.load_plugins(self._make_factory())
        kernel.shutdown()
        assert len(kernel._runtime.active_plugins) == 0
