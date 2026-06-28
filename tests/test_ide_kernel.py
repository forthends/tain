import tempfile
from pathlib import Path
from tain_agent.kernel import AgentKernel, AgentContext
from tain_agent.kernel import PLUGIN_LAYOUT

class TestIdeLayout:
    def test_ide_layout_has_five_plugins(self):
        assert "ide" in PLUGIN_LAYOUT
        assert PLUGIN_LAYOUT["ide"] == ["identity", "tool", "skill", "knowledge", "memory"]

    def test_ide_layout_excludes_evolution_plugins(self):
        ide = PLUGIN_LAYOUT["ide"]
        assert "workflow" not in ide
        assert "collaboration" not in ide
        assert "evaluation" not in ide

    def test_ide_kernel_loads_five_plugins(self):
        from tain_agent.plugins.identity import IdentityPlugin
        from tain_agent.plugins.tool import ToolPlugin
        from tain_agent.plugins.skill import SkillPlugin
        from tain_agent.plugins.knowledge import KnowledgePlugin
        from tain_agent.plugins.memory import MemoryPlugin
        factories = {"identity": IdentityPlugin, "tool": ToolPlugin, "skill": SkillPlugin, "knowledge": KnowledgePlugin, "memory": MemoryPlugin}
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext("ide_test", "ide-1", "ide", Path(tmpdir), {}, "0.6.0")
            kernel = AgentKernel(ctx)
            kernel.load_plugins(factories)
            assert kernel.lifecycle.get("identity") is not None
            assert kernel.lifecycle.get("workflow") is None
            kernel.shutdown()
