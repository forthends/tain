"""Adapters that wrap existing TaoAgent subsystems as PluginProtocol instances.

These provide backward-compatible bridges so the new Kernel can drive
old subsystems without modifying them. Each adapter will be removed
once its corresponding native plugin is built and validated.
"""

from __future__ import annotations
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol


class ExistingToolAdapter:
    """Wraps the current ToolRegistry + ToolForge as a ToolPlugin stand-in."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._registry = None   # set during initialize
        self._forge = None      # set during initialize

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        from tain_agent.tools.registry import ToolRegistry
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.primal import register_primal_tools
        self._registry = ToolRegistry()
        self._forge = ToolForge(self._registry, workspace_dir=str(ctx.workspace_path))
        register_primal_tools(self._registry, workspace_dir=str(ctx.workspace_path))

    def shutdown(self) -> None:
        self._registry = None
        self._forge = None

    def health_check(self) -> HealthStatus:
        if self._registry is None:
            return HealthStatus(status="critical", alerts=["registry not initialized"])
        return HealthStatus(status="ok", metrics={"tool_count": float(self._registry.count())})

    def snapshot(self) -> dict:
        if self._registry:
            return {"tools": list(self._registry.list_tools().keys())}
        return {}

    def restore(self, data: dict) -> None:
        pass  # Existing registry re-initializes from disk

    # Optional PRAL hooks
    def on_cycle_start(self, cycle: int) -> None: pass
    def on_cycle_end(self, cycle: int) -> None: pass
    def on_llm_response(self, response) -> None: pass

    def enrich_prompt(self, base: str) -> str:
        if self._registry is None:
            return base
        tools = self._registry.list_tools()
        lines = ["\n\n## Current Available Tools"]
        for name, info in tools.items():
            lines.append(f"- **{name}**: {info.get('description', '')}")
        return base + "\n".join(lines)

    def list_tools(self):
        if self._registry:
            return self._registry.list_tools()
        return {}

    def call(self, name: str, **kwargs):
        if self._registry:
            return self._registry.call(name, **kwargs)
        return {"error": "registry not initialized"}

    def forge(self, name: str, description: str, code: str):
        if self._forge:
            return self._forge.forge(name=name, description=description, code=code, parameters={})
        return {"success": False, "error": "forge not initialized"}


class ExistingPersonalityAdapter:
    """Wraps the current Personality + DriveSystem as an IdentityPlugin stand-in."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._personality = None

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        from tain_agent.core.personality import Personality
        self._personality = Personality()

    def shutdown(self) -> None:
        self._personality = None

    def health_check(self) -> HealthStatus:
        if self._personality is None:
            return HealthStatus(status="critical")
        return HealthStatus(
            status="ok",
            metrics={"total_traits": float(self._personality.total_traits())},
        )

    def snapshot(self) -> dict:
        if self._personality:
            return self._personality.introspect()
        return {}

    def restore(self, data: dict) -> None:
        pass

    # Optional PRAL hooks
    def on_cycle_start(self, cycle: int) -> None: pass
    def on_cycle_end(self, cycle: int) -> None: pass

    def enrich_prompt(self, base: str) -> str:
        if self._personality and not self._personality.is_empty():
            return base + "\n\n" + self._personality.get_context_for_prompt()
        return base

    def on_llm_response(self, response) -> None:
        if self._personality and response.tool_calls:
            tool_names = [tc.name for tc in response.tool_calls]
            self._personality.auto_observe(tool_names, response.text_blocks)


class ExistingMemoryAdapter:
    """Wraps the current Memory system as a MemoryPlugin stand-in."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._memory = None

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        from tain_agent.core.memory import Memory
        memory_path = Path(ctx.workspace_path) / "memory.json"
        self._memory = Memory(long_term_path=str(memory_path))

    def shutdown(self) -> None:
        if self._memory:
            self._memory.long_term.flush()
        self._memory = None

    def health_check(self) -> HealthStatus:
        if self._memory is None:
            return HealthStatus(status="critical")
        return HealthStatus(status="ok")

    def snapshot(self) -> dict:
        if self._memory:
            return self._memory.snapshot()
        return {}

    def restore(self, data: dict) -> None:
        pass

    # Optional PRAL hooks
    def on_cycle_start(self, cycle: int) -> None: pass
    def on_cycle_end(self, cycle: int) -> None: pass
    def on_llm_response(self, response) -> None: pass

    def enrich_prompt(self, base: str) -> str:
        return base  # Existing memory doesn't inject into prompt

    def recall(self, query: str, k: int = 5):
        return []  # Existing memory has no vector recall — native plugin will add this

    def encode(self, content: str, importance: float = 0.5):
        pass  # Existing memory uses different API — native plugin will add this
