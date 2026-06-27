"""ToolPlugin — wraps ToolRegistry + ToolForge as a PluginProtocol plugin.

Adds ClosedForgeCycle for LLM-driven tool generation, closing the
evolution loop: the agent can both design and create its own tools.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.tool.forge_cycle import (
    ClosedForgeCycle,
    CycleStage,
    ForgeCycleResult,
    ImprovementSpec,
    StageResult,
)

logger = logging.getLogger(__name__)


class ToolPlugin:
    """Plugin that owns ToolRegistry, ToolForge, and ClosedForgeCycle.

    Required PluginProtocol methods: initialize, shutdown, health_check,
    snapshot, restore.

    Optional PRAL hooks: on_cycle_start, on_cycle_end, enrich_prompt,
    on_llm_response.

    Tool-specific API:
      - list_tools() → dict of registered tools and metadata
      - call(name, **kwargs) → tool execution result
      - forge(name, description, code, parameters) → forge a new tool
      - needs_human_approval(action) → True if autonomy_level < 4
      - rollback(tool_name) → remove a forged tool
      - forge_cycle(spec, code, llm_backend) → run ClosedForgeCycle
    """

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._registry = None
        self._forge = None
        self._cycle: ClosedForgeCycle | None = None
        self._autonomy_level: int = 2  # default GUIDED

    # ── PluginProtocol lifecycle ────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx

        from tain_agent.tools.registry import ToolRegistry
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.primal import register_primal_tools

        workspace_str = str(ctx.workspace_path)

        self._registry = ToolRegistry()
        self._forge = ToolForge(self._registry, workspace_dir=workspace_str)
        register_primal_tools(self._registry, workspace_dir=workspace_str)

        # Load previously forged tools
        loaded = self._forge.load_forged_tools()
        if loaded > 0:
            logger.info("Loaded %d previously forged tools.", loaded)

        # Determine autonomy level from config
        autonomy_config = ctx.config.get("autonomy_level", None)
        if autonomy_config is not None:
            self._autonomy_level = int(autonomy_config)
        else:
            # Default: GUIDED (level 2)
            self._autonomy_level = 2

        # Create closed forge cycle (LLM backend can be injected later)
        self._cycle = ClosedForgeCycle(self._registry, self._forge)

        logger.info(
            "ToolPlugin initialized: %d tools registered, autonomy_level=%d",
            self._registry.count(),
            self._autonomy_level,
        )

    def shutdown(self) -> None:
        self._registry = None
        self._forge = None
        self._cycle = None
        self._ctx = None

    def health_check(self) -> HealthStatus:
        if self._registry is None:
            return HealthStatus(status="critical", alerts=["registry not initialized"])
        metrics = {
            "tool_count": float(self._registry.count()),
            "forged_count": float(len(self._forge._forged_tools) if self._forge else 0),
        }
        return HealthStatus(status="ok", metrics=metrics)

    def snapshot(self) -> dict:
        if self._registry is None:
            return {}
        return {
            "tools": list(self._registry.list_tools().keys()),
            "forged": list(self._forge._forged_tools.keys()) if self._forge else [],
            "autonomy_level": self._autonomy_level,
        }

    def restore(self, data: dict) -> None:
        # Tools re-load from disk on initialize; no in-memory restore needed
        pass

    # ── Optional PRAL hooks ─────────────────────────────────────────────

    def on_cycle_start(self, cycle: int) -> None:
        pass

    def on_cycle_end(self, cycle: int) -> None:
        pass

    def on_llm_response(self, response: Any) -> None:
        pass

    def enrich_prompt(self, base: str) -> str:
        """Append the list of available tools to the agent's prompt."""
        if self._registry is None:
            return base

        tools = self._registry.list_tools()
        lines = ["", "## 可用工具 (Available Tools)", ""]
        if not tools:
            lines.append("_(no tools registered)_")
        else:
            for name, info in sorted(tools.items()):
                desc = info.get("description", "")
                is_ro = info.get("is_readonly", False)
                tag = " [read-only]" if is_ro else ""
                lines.append(f"- **{name}**{tag}: {desc}")

        return base + "\n".join(lines)

    # ── Tool-specific API ───────────────────────────────────────────────

    def list_tools(self) -> dict:
        """Return all registered tools and their metadata."""
        if self._registry is None:
            return {}
        return self._registry.list_tools()

    def call(self, name: str, **kwargs) -> dict:
        """Execute a registered tool by name."""
        if self._registry is None:
            return {"success": False, "error": "registry not initialized"}
        return self._registry.call(name, **kwargs)

    def forge(
        self,
        name: str,
        description: str,
        code: str,
        parameters: dict | None = None,
    ) -> dict:
        """Forge a new tool from source code through the safety sandbox.

        Args:
            name: Tool name.
            description: Human-readable description.
            code: Python source code for the tool function.
            parameters: Optional dict with 'action' key:
                - "create" (default): Create a new tool
                - "update": Update an existing forged tool
                - "rollback": Remove a forged tool
        """
        if self._forge is None:
            return {"success": False, "error": "forge not initialized"}

        action = (parameters or {}).get("action", "create")
        if action not in ("create", "update", "rollback"):
            return {
                "success": False,
                "error": (
                    f"Unknown action: {action}. "
                    "Use 'create', 'update', or 'rollback'."
                ),
            }

        if action == "rollback":
            return self._forge.remove_forged(name)

        # Strip action from parameters before passing to ToolForge
        forge_params = dict(parameters) if parameters else None
        if forge_params:
            forge_params.pop("action", None)
            if not forge_params:
                forge_params = None

        # ToolForge.forge overwrites by name — no need to remove first
        return self._forge.forge(
            name=name,
            description=description,
            code=code,
            parameters=forge_params,
            action=action,
        )

    def forge_cycle(
        self,
        spec: ImprovementSpec,
        code: str | None = None,
        llm_backend: Any = None,
    ) -> ForgeCycleResult:
        """Run the full 6-stage closed forge cycle.

        Uses the spec to analyze, design, generate (if needed), forge,
        verify, and register a new tool.
        """
        if self._cycle is None:
            return ForgeCycleResult(
                success=False,
                stages=[
                    StageResult(
                        CycleStage.ANALYZE, False, None,
                        "ClosedForgeCycle not initialized",
                    )
                ],
            )
        return self._cycle.run(spec, code=code, llm_backend=llm_backend)

    def needs_human_approval(self, action: str | None = None) -> bool:
        """Check if this action requires human approval.

        Rules:
          - autonomy_level >= 4 (AUTONOMOUS): no approval needed
          - autonomy_level >= 3 (TRUSTED): only destructive actions need approval
          - autonomy_level <= 2 (GUIDED/SUPERVISED): most actions need approval

        Args:
            action: Optional action name to check. Destructive actions
                    (forge, remove, rollback) always need approval
                    at autonomy_level < 4.
        """
        level = self._autonomy_level

        if level >= 4:
            return False  # AUTONOMOUS or FULL — self-approves

        if level >= 3:
            # TRUSTED: only destructive actions need approval
            destructive = {"forge", "rollback", "remove", "delete"}
            if action and action in destructive:
                return True
            return False

        # level <= 2 (GUIDED or SUPERVISED): most actions need approval
        always_auto = {"list_tools", "call", "enrich_prompt"}
        if action and action in always_auto:
            return False
        return True

    def rollback(self, tool_name: str) -> dict:
        """Remove a forged tool from the registry and disk."""
        if self._forge is None:
            return {"success": False, "error": "forge not initialized"}
        return self._forge.remove_forged(tool_name)

    def list_forged(self) -> dict:
        """Return all forged tools and their metadata."""
        if self._forge is None:
            return {}
        return self._forge.list_forged()

    def get_sandbox_allowlist(self) -> list:
        """Return the current sandbox import/API allowlist."""
        from tain_agent.tools.sandbox_allowlist import get_allowlist
        return get_allowlist()["allowed_modules"]

    # ── Convenience ─────────────────────────────────────────────────────

    @property
    def registry(self):
        """Direct access to the ToolRegistry (for advanced use)."""
        return self._registry

    @property
    def forge_instance(self):
        """Direct access to the ToolForge (for advanced use)."""
        return self._forge

    @property
    def cycle(self) -> ClosedForgeCycle | None:
        """Direct access to the ClosedForgeCycle."""
        return self._cycle

    @property
    def autonomy_level(self) -> int:
        return self._autonomy_level

    @autonomy_level.setter
    def autonomy_level(self, value: int) -> None:
        self._autonomy_level = value

    def set_llm_backend(self, backend: Any) -> None:
        """Inject an LLM backend into the ClosedForgeCycle.

        The backend must be callable: backend(prompt: str) → str
        """
        if self._cycle is not None:
            self._cycle.llm_backend = backend
