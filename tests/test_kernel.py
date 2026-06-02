"""Tests for AgentKernel, LifecycleManager, PRALLoop, Dispatch."""

from pathlib import Path
from tain_agent.kernel import AgentKernel, AgentContext, HealthStatus
from tain_agent.kernel.lifecycle import LifecycleManager
from tain_agent.kernel.dispatch import Dispatch


class TestDispatch:
    def test_register_and_call(self):
        d = Dispatch()
        d.register("test.event", lambda x: x * 2)
        assert d.call("test.event", 3) == 6

    def test_missing_event_returns_none(self):
        d = Dispatch()
        assert d.call("nonexistent") is None

    def test_handler_exception_returns_error_string(self):
        d = Dispatch()
        d.register("failing", lambda: 1 / 0)
        result = d.call("failing")
        assert result is not None
        assert "[Dispatch Error]" in result


class TestLifecycleManager:
    def _make_ctx(self):
        return AgentContext(
            agent_name="test", agent_id="a1", evolution_mode="chaos",
            workspace_path=Path("/tmp/ws"), config={}, kernel_version="0.6.0",
        )

    def _make_factory(self):
        class FakePlugin:
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
        lm = LifecycleManager()
        lm.load(self._make_ctx(), self._make_factory())
        assert list(lm.plugins.keys()) == ["identity", "memory", "tool"]

    def test_get_returns_none_for_unloaded(self):
        lm = LifecycleManager()
        lm.load(self._make_ctx(), self._make_factory())
        assert lm.get("collaboration") is None

    def test_shutdown_clears_all(self):
        lm = LifecycleManager()
        lm.load(self._make_ctx(), self._make_factory())
        lm.shutdown_all()
        assert len(lm.plugins) == 0
