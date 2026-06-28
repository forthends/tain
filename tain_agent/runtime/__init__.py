# tain_agent/runtime/__init__.py
"""
Tain Agent Runtime — standalone execution kernel for exported agents.

This package is the "engine" that powers an evolved agent after it leaves
the factory (tain_agent framework). It has zero internal dependencies on
tain_agent and only requires stdlib + pip packages (anthropic, openai, rich).

Design constraint: no ``import tain_agent`` anywhere in this package.
"""

from __future__ import annotations

from typing import Any

from tain_agent.kernel.dispatch import Dispatch
from tain_agent.kernel.protocol import AgentContext
from tain_agent.package import AgentPackage
from tain_agent.package.manifest import parse_manifest, Manifest
from tain_agent.runtime.plugin_loader import PluginLoader

__version__ = "3.0.0-dev"


class AgentRuntime:
    """Minimal runtime for an AgentPackage.

    Only IdentityPlugin and MemoryPlugin are loaded perpetually.
    All other plugins are loaded based on the package's manifest infra.plugins declaration.
    """

    def __init__(self, package: AgentPackage, config: dict[str, Any] | None = None):
        self.package = package
        self.config = config or {}
        self.dispatch = Dispatch()

        # Parse manifest
        self.manifest: Manifest = parse_manifest(package.manifest_path)

        # Build context
        self.ctx = AgentContext(
            agent_name=self.manifest.package.name,
            agent_id=f"{self.manifest.package.name}-{package.path.name}",
            evolution_mode=self.manifest.package.evolution_mode,
            workspace_path=package.path,
            config=self.config,
            kernel_version=self.manifest.infra.runtime.kernel_version or "0.11.0",
        )

        # Assemble plugins
        self.plugin_loader = PluginLoader(registry=self._build_plugin_registry())
        declared = self.manifest.infra.plugins
        self.active_plugins = self.plugin_loader.assemble(declared, self.ctx)

        # Register dispatch routes for active plugins
        self._build_routes()

    def _build_plugin_registry(self) -> dict[str, type]:
        """Build the plugin registry mapping name -> class."""
        from tain_agent.plugins.identity import IdentityPlugin
        from tain_agent.plugins.memory import MemoryPlugin
        from tain_agent.plugins.tool import ToolPlugin
        from tain_agent.plugins.skill import SkillPlugin
        from tain_agent.plugins.knowledge import KnowledgePlugin
        from tain_agent.plugins.workflow import WorkflowPlugin
        from tain_agent.plugins.collaboration import CollaborationPlugin
        from tain_agent.plugins.evaluation import EvaluationPlugin

        return {
            "identity": IdentityPlugin,
            "memory": MemoryPlugin,
            "tool": ToolPlugin,
            "skill": SkillPlugin,
            "knowledge": KnowledgePlugin,
            "workflow": WorkflowPlugin,
            "collaboration": CollaborationPlugin,
            "evaluation": EvaluationPlugin,
        }

    def _build_routes(self) -> None:
        """Register dispatch routes for actively loaded plugins only."""
        plugin_map = {p.__class__.__name__: p for p in self.active_plugins}

        route_map = {
            "memory.recall": ("MemoryPlugin", "recall"),
            "knowledge.query": ("KnowledgePlugin", "query"),
            "tool.call": ("ToolPlugin", "call"),
            "tool.forge": ("ToolPlugin", "forge"),
            "skill.execute": ("SkillPlugin", "execute"),
            "workflow.advance": ("WorkflowPlugin", "advance"),
            "collaboration.send": ("CollaborationPlugin", "send"),
            "evaluation.get_readiness": ("EvaluationPlugin", "get_readiness"),
            "evaluation.get_report": ("EvaluationPlugin", "get_report"),
        }

        for event, (class_name, method_name) in route_map.items():
            if class_name in plugin_map:
                plugin = plugin_map[class_name]
                self.dispatch.register(event, getattr(plugin, method_name))

    def get_plugin(self, name: str) -> Any | None:
        """Get a loaded plugin by class name or registry key."""
        for p in self.active_plugins:
            if p.__class__.__name__ == name or p.__class__.__name__ == f"{name.capitalize()}Plugin":
                return p
        return None

    def get_identity(self):
        return self.get_plugin("IdentityPlugin")

    def get_memory(self):
        return self.get_plugin("MemoryPlugin")

    def health_check(self) -> dict[str, Any]:
        """Run health checks on all active plugins."""
        results = {}
        for p in self.active_plugins:
            name = p.__class__.__name__
            try:
                results[name] = p.health_check()
            except Exception as e:
                results[name] = {"status": "critical", "error": str(e)}
        return results

    def shutdown(self) -> None:
        """Shutdown all active plugins."""
        for p in self.active_plugins:
            try:
                p.shutdown()
            except Exception:
                pass
        self.active_plugins.clear()
