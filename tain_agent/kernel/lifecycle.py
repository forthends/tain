"""Agent lifecycle management — create, start, stop, pause, resume, export."""

from __future__ import annotations
import logging
from typing import Optional
from tain_agent.kernel.protocol import AgentContext, PluginProtocol

logger = logging.getLogger(__name__)

PLUGIN_LAYOUT = {
    "specified": ["identity", "memory", "skill", "tool", "knowledge", "workflow", "collaboration"],
    "chaos": ["identity", "memory", "tool"],
    "ide": ["identity", "tool", "skill", "knowledge", "memory"],
}


class LifecycleManager:
    """Owns plugin instances and drives their lifecycle."""

    def __init__(self):
        self._plugins: dict[str, PluginProtocol] = {}
        self._ctx: Optional[AgentContext] = None

    @property
    def plugins(self) -> dict[str, PluginProtocol]:
        return dict(self._plugins)

    def load(self, ctx: AgentContext, plugin_factories: dict[str, type]) -> None:
        """Load plugins according to evolution mode."""
        self._ctx = ctx
        layout = PLUGIN_LAYOUT.get(ctx.evolution_mode, PLUGIN_LAYOUT["specified"])
        for name in layout:
            factory = plugin_factories.get(name)
            if factory is None:
                logger.warning("Plugin %r not found in factories, skipping", name)
                continue
            instance = factory()
            instance.initialize(ctx)
            self._plugins[name] = instance
            logger.info("Plugin %r loaded", name)

    def get(self, name: str) -> Optional[PluginProtocol]:
        return self._plugins.get(name)

    def all_health_checks(self) -> dict[str, dict]:
        return {name: p.health_check() for name, p in self._plugins.items()}

    def shutdown_all(self) -> None:
        for name, plugin in list(self._plugins.items()):
            try:
                plugin.shutdown()
            except Exception:
                logger.exception("Plugin %r shutdown failed", name)
            finally:
                del self._plugins[name]
