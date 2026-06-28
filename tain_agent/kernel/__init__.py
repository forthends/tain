# tain_agent/kernel/__init__.py — re-export shim
"""Kernel module — now re-exports from runtime and protocol.

Provides a backward-compatible AgentKernel wrapper that internally
delegates to AgentRuntime, keeping existing consumers working while
the underlying infrastructure has moved to runtime/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tain_agent.kernel.protocol import PluginProtocol, AgentContext, HealthStatus
from tain_agent.kernel.dispatch import Dispatch
from tain_agent.runtime.plugin_loader import PluginLoader

# Backward-compatible plugin class imports for STANDARD_FACTORIES
from tain_agent.plugins.identity import IdentityPlugin
from tain_agent.plugins.memory import MemoryPlugin
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.skill import SkillPlugin
from tain_agent.plugins.knowledge import KnowledgePlugin
from tain_agent.plugins.workflow import WorkflowPlugin
from tain_agent.plugins.collaboration import CollaborationPlugin
from tain_agent.plugins.evaluation import EvaluationPlugin

# Standard factory mapping (can be used to override plugin selection)
STANDARD_FACTORIES = {
    "identity": IdentityPlugin,
    "memory": MemoryPlugin,
    "tool": ToolPlugin,
    "skill": SkillPlugin,
    "knowledge": KnowledgePlugin,
    "workflow": WorkflowPlugin,
    "collaboration": CollaborationPlugin,
    "evaluation": EvaluationPlugin,
}

# Re-export prompts for backward compatibility
from tain_agent.runtime.prompts import (
    BOOTSTRAP_SYSTEM_PROMPT,
    SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT,
    EVOLVE_SYSTEM_PROMPT,
)

# Plugin layout by evolution mode (moved from deleted lifecycle.py)
PLUGIN_LAYOUT = {
    "specified": [
        "identity", "memory", "skill", "tool",
        "knowledge", "workflow", "collaboration",
    ],
    "chaos": ["identity", "memory", "tool"],
    "ide": ["identity", "tool", "skill", "knowledge", "memory"],
}


class _LifecycleAdapter:
    """Backward-compatible adapter that mirrors LifecycleManager API
    but delegates to AgentRuntime's active plugins."""

    def __init__(self, runtime: Any):
        self._runtime = runtime
        self._registry_map: dict[str, Any] = {}

    def _set_registry_map(self, mapping: dict[str, Any]) -> None:
        """Update the registry-key-to-plugin-instance mapping."""
        self._registry_map.update(mapping)

    def get(self, name: str) -> Any | None:
        """Get a plugin by registry key name (e.g. 'tool', 'identity').

        First tries AgentRuntime.get_plugin (class-name-based lookup),
        then falls back to the registry-key mapping for plugins loaded
        via load_plugins (which may use custom class names in tests).
        """
        result = self._runtime.get_plugin(name)
        if result is not None:
            return result
        return self._registry_map.get(name)

    @property
    def plugins(self) -> dict[str, Any]:
        """Plugin dict keyed by class name for backward compat."""
        return {p.__class__.__name__: p for p in self._runtime.active_plugins}

    def all_health_checks(self) -> dict[str, Any]:
        return self._runtime.health_check()

    def shutdown_all(self) -> None:
        self._runtime.shutdown()

    def load(self, ctx: AgentContext, plugin_factories: dict[str, type]) -> None:
        """No-op: plugins loaded via load_plugins on AgentKernel."""
        pass


class _PRALAdapter:
    """Minimal adapter providing cycle_count and stop() for backward compat."""

    def __init__(self):
        self.cycle_count = 0

    def stop(self) -> None:
        pass


def _ensure_package(ctx: AgentContext) -> Any:
    """Create or retrieve an AgentPackage for the given context.

    Creates a manifest that declares only perpetual plugins (identity, memory).
    Additional plugins are loaded by load_plugins() at the AgentKernel level.

    The packages root is derived from the parent of ctx.workspace_path so that
    tests using tmp_path do not write into the real agent_workspace/ on disk.
    """
    from tain_agent.package import PackageRegistry, AgentPackage as AgentPkg, PackageKind
    from tain_agent.package.manifest import create_manifest

    # Derive packages root from the workspace path rather than hardcoding
    # agent_workspace/packages.  For production use (workspace_path ==
    # agent_workspace/<agent>) this yields agent_workspace/packages; for tests
    # (tmp_path/<agent>) this yields tmp_path/packages.
    #
    # Guard against accidental nesting when workspace_path already points
    # inside a packages/ directory (e.g. agent_workspace/packages/<agent>).
    # In that case, use the existing packages/ parent instead of creating a
    # nested packages/packages/ ghost.
    packages_root = ctx.workspace_path.parent / "packages"
    if packages_root.parent.name == "packages":
        # workspace_path was already inside a packages/ dir — back out
        packages_root = packages_root.parent
    packages_root.mkdir(parents=True, exist_ok=True)
    pkg_dir = packages_root / ctx.agent_name
    pkg_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = pkg_dir / "manifest.json"
    if not manifest_path.exists():
        manifest = create_manifest(
            name=ctx.agent_name,
            kind="agent",
            version="0.0.0",
            evolution_mode=ctx.evolution_mode,
        )
        manifest.to_json(manifest_path)

    reg = PackageRegistry(packages_root=packages_root)
    pkg = reg.get_package(ctx.agent_name)
    if pkg is None:
        pkg = AgentPkg(
            name=ctx.agent_name,
            kind=PackageKind.AGENT,
            version="0.0.0",
            packages_root=packages_root,
        )
        pkg.ensure_directories()

    return pkg


def _build_routes_from_plugins(dispatch: Dispatch, plugins: list[Any]) -> None:
    """Register dispatch routes for a list of plugin instances."""
    plugin_map = {p.__class__.__name__: p for p in plugins}

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
        if class_name not in plugin_map:
            continue
        plugin = plugin_map[class_name]
        if not hasattr(plugin, method_name):
            continue
        dispatch.register(event, getattr(plugin, method_name))


class AgentKernel:
    """Backward-compatible entry point that wraps AgentRuntime.

    Existing code that constructs AgentKernel(ctx) and calls
    load_plugins(), run(), shutdown(), etc. continues to work.
    The implementation delegates to AgentRuntime internally.
    """

    def __init__(self, ctx: AgentContext):
        # Lazy import to avoid circular dependency with runtime
        from tain_agent.runtime import AgentRuntime

        self.ctx = ctx
        self.dispatch = Dispatch()

        # Ensure a package exists for this agent
        pkg = _ensure_package(ctx)

        # Build the runtime (loads perpetual plugins: identity, memory)
        self._runtime = AgentRuntime(package=pkg, config=ctx.config)

        # Align the legacy context's workspace_path with the package path
        # so that load_plugins and other legacy paths write into the
        # package directory rather than a separate agent_workspace/<name>.
        self.ctx.workspace_path = pkg.path

        # Reuse the runtime's dispatch (already populated with routes)
        self.dispatch = self._runtime.dispatch

        # Backward-compat adapters
        self.lifecycle = _LifecycleAdapter(self._runtime)
        self.pral = _PRALAdapter()

        # Set up initial registry map for perpetual plugins loaded by AgentRuntime
        perpetual_map: dict[str, Any] = {}
        for plugin in self._runtime.active_plugins:
            name = plugin.__class__.__name__
            # Strip 'Plugin' suffix to get registry key
            if name.endswith("Plugin"):
                key = name[:-6].lower()  # "IdentityPlugin" -> "identity"
                perpetual_map[key] = plugin
        self.lifecycle._set_registry_map(perpetual_map)

    def load_plugins(self, factories: dict[str, type]) -> None:
        """Load plugins using the provided factory mapping.

        Respects evolution mode for plugin selection, matching the
        behaviour of the removed LifecycleManager.load().
        Plugins already loaded by AgentRuntime (perpetual plugins)
        are skipped to avoid double-initialization.

        Plugins are initialized with the runtime's AgentContext
        (workspace_path = package path) so all plugin data lands
        inside the package directory tree.
        """
        layout = PLUGIN_LAYOUT.get(self.ctx.evolution_mode, PLUGIN_LAYOUT["specified"])
        registry_updates: dict[str, Any] = {}
        new_instances: list[Any] = []

        for name in layout:
            # Skip if already loaded (e.g. perpetual plugins from AgentRuntime)
            if self.lifecycle.get(name) is not None:
                continue
            factory = factories.get(name)
            if factory is None:
                continue
            instance = factory()
            # Initialize with the runtime's context so plugin data is written
            # into the package directory (workspace_path = packages/<name>)
            # rather than the legacy agent_workspace/<name> path.
            instance.initialize(self._runtime.ctx)
            self._runtime.active_plugins.append(instance)
            registry_updates[name] = instance
            new_instances.append(instance)

        # Update registry map for backward-compat name lookups
        self.lifecycle._set_registry_map(registry_updates)

        # Register dispatch routes only for newly loaded plugins
        # (perpetual plugins already have routes registered by AgentRuntime)
        _build_routes_from_plugins(self.dispatch, new_instances)

    def run(
        self,
        llm_backend: Any,
        conversation: Any,
        drive_system: Any,
        system_prompt: str,
        max_cycles: int | float = float("inf"),
        stop_signal: callable | None = None,
    ) -> int:
        """Run the PRAL cognitive loop."""
        from tain_agent.runtime.pral import PRALLoop

        pral = PRALLoop(self._runtime)
        result = pral.run(
            llm_backend, conversation, drive_system, system_prompt,
            max_cycles=max_cycles, stop_signal=stop_signal,
        )
        self.pral.cycle_count = pral.cycle_count
        return result

    def shutdown(self) -> None:
        """Shutdown all plugins and stop the runtime."""
        self.pral.stop()
        self._runtime.shutdown()


# Re-export AgentRuntime at module level for direct imports
# (lazy-loaded to avoid circular import)
def __getattr__(name: str) -> Any:
    if name == "AgentRuntime":
        from tain_agent.runtime import AgentRuntime
        return AgentRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AgentKernel", "AgentRuntime", "PluginProtocol", "AgentContext", "HealthStatus",
    "Dispatch", "PluginLoader", "STANDARD_FACTORIES",
    "BOOTSTRAP_SYSTEM_PROMPT", "SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT", "EVOLVE_SYSTEM_PROMPT",
]
