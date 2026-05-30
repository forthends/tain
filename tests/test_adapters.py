"""Tests for existing subsystem adapters."""

from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins._adapters import (
    ExistingToolAdapter,
    ExistingPersonalityAdapter,
    ExistingMemoryAdapter,
)


class TestExistingToolAdapter:
    def test_satisfies_protocol(self):
        assert isinstance(ExistingToolAdapter(), PluginProtocol)

    def test_initialize_and_health(self):
        adapter = ExistingToolAdapter()
        ctx = AgentContext("test", "a1", "specified", Path("/tmp/ws"), {}, "0.6.0")
        adapter.initialize(ctx)
        health = adapter.health_check()
        assert health.status == "ok"
        assert "tool_count" in health.metrics


class TestExistingPersonalityAdapter:
    def test_satisfies_protocol(self):
        assert isinstance(ExistingPersonalityAdapter(), PluginProtocol)

    def test_starts_empty(self):
        adapter = ExistingPersonalityAdapter()
        ctx = AgentContext("test", "a1", "chaos", Path("/tmp/ws"), {}, "0.6.0")
        adapter.initialize(ctx)
        snap = adapter.snapshot()
        assert snap.get("status") == "empty"


class TestExistingMemoryAdapter:
    def test_satisfies_protocol(self):
        assert isinstance(ExistingMemoryAdapter(), PluginProtocol)
