"""Agent Kernel — PRAL orchestration with plugin protocol."""

from tain_agent.kernel.protocol import PluginProtocol, AgentContext, HealthStatus
from tain_agent.kernel.lifecycle import LifecycleManager
from tain_agent.kernel.pral import PRALLoop
from tain_agent.kernel.dispatch import Dispatch


class AgentKernel:
    """Top-level entry point for the Core-Plugins architecture."""

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.dispatch = Dispatch()
        self.lifecycle = LifecycleManager()
        self.pral = PRALLoop(self.lifecycle, self.dispatch)

    def load_plugins(self, factories: dict[str, type]) -> None:
        self.lifecycle.load(self.ctx, factories)
        # Register cross-plugin dispatch routes
        for event, handler in self._build_routes().items():
            self.dispatch.register(event, handler)

    def _build_routes(self) -> dict:
        routes = {}
        tp = self.lifecycle.get("tool")
        if tp:
            routes["tool.call"] = tp.call
            routes["tool.forge"] = tp.forge
        sp = self.lifecycle.get("skill")
        if sp:
            routes["skill.execute"] = sp.execute
        kp = self.lifecycle.get("knowledge")
        if kp:
            routes["knowledge.query"] = kp.query
        mp = self.lifecycle.get("memory")
        if mp:
            routes["memory.recall"] = mp.recall
        wp = self.lifecycle.get("workflow")
        if wp:
            routes["workflow.advance"] = wp.advance
        cp = self.lifecycle.get("collaboration")
        if cp:
            routes["collaboration.send"] = cp.send
        return routes

    def run(self, llm_backend, conversation, drive_system, system_prompt: str,
            max_cycles=float("inf"), stop_signal=None) -> int:
        return self.pral.run(llm_backend, conversation, drive_system, system_prompt,
                             max_cycles=max_cycles, stop_signal=stop_signal)

    def shutdown(self) -> None:
        self.pral.stop()
        self.lifecycle.shutdown_all()


__all__ = ["AgentKernel", "PluginProtocol", "AgentContext", "HealthStatus"]
