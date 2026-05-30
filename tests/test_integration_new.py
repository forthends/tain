"""Integration test: new AgentKernel runs with all plugins loaded."""

import tempfile
from pathlib import Path
from tain_agent.kernel import AgentKernel, AgentContext
from tain_agent.plugins.identity import IdentityPlugin
from tain_agent.plugins.memory import MemoryPlugin
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.skill import SkillPlugin
from tain_agent.plugins.knowledge import KnowledgePlugin
from tain_agent.plugins.workflow import WorkflowPlugin
from tain_agent.plugins.collaboration import CollaborationPlugin


_FACTORIES = {
    "identity": IdentityPlugin, "memory": MemoryPlugin,
    "tool": ToolPlugin, "skill": SkillPlugin,
    "knowledge": KnowledgePlugin, "workflow": WorkflowPlugin,
    "collaboration": CollaborationPlugin,
}


class TestKernelIntegration:
    def test_all_plugins_initialize_and_health_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext(
                agent_name="integration_test", agent_id="it-001",
                evolution_mode="specified", workspace_path=Path(tmpdir),
                config={}, kernel_version="0.6.0",
            )
            kernel = AgentKernel(ctx)
            kernel.load_plugins(_FACTORIES)

            # All plugins loaded
            for name in _FACTORIES:
                assert kernel.lifecycle.get(name) is not None, f"{name} not loaded"

            # All health checks pass
            for name, health in kernel.lifecycle.all_health_checks().items():
                assert health.status != "critical", f"{name} health critical: {health.alerts}"

            kernel.shutdown()

    def test_kernel_dispatch_routes_registered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext(
                agent_name="it2", agent_id="it-002",
                evolution_mode="specified", workspace_path=Path(tmpdir),
                config={}, kernel_version="0.6.0",
            )
            kernel = AgentKernel(ctx)
            kernel.load_plugins(_FACTORIES)

            # Verify key dispatch routes are registered (don't crash)
            # tool.call returns error dict for missing tools
            result = kernel.dispatch.call("tool.call", "nonexistent")
            assert isinstance(result, dict), "tool.call should return a dict"
            # memory.recall requires limit=int kwarg, returns list
            result = kernel.dispatch.call("memory.recall", limit=5)
            assert isinstance(result, list), "memory.recall should return a list"
            # Unregistered routes (skill.execute) return None
            assert kernel.dispatch.call("skill.execute", "test") is None
            result = kernel.dispatch.call("knowledge.query", "test")
            assert isinstance(result, dict), "knowledge.query should return a dict"

            kernel.shutdown()

    def test_chaos_mode_loads_only_three_plugins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext(
                agent_name="chaos_test", agent_id="ct-001",
                evolution_mode="chaos", workspace_path=Path(tmpdir),
                config={}, kernel_version="0.6.0",
            )
            kernel = AgentKernel(ctx)
            kernel.load_plugins(_FACTORIES)

            assert kernel.lifecycle.get("identity") is not None
            assert kernel.lifecycle.get("memory") is not None
            assert kernel.lifecycle.get("tool") is not None
            assert kernel.lifecycle.get("collaboration") is None  # not loaded in chaos

            kernel.shutdown()
