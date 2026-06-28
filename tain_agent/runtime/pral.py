# tain_agent/runtime/pral.py
"""PRAL cognitive loop adapted for AgentRuntime."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from tain_agent.kernel.dispatch import Dispatch
from tain_agent.runtime import AgentRuntime

logger = logging.getLogger(__name__)


class PRALLoop:
    """Perceive → Reason → Act → Learn loop for AgentRuntime."""

    def __init__(self, runtime: AgentRuntime):
        self._runtime = runtime
        self._dispatch = runtime.dispatch
        self._running = False
        self.cycle_count = 0
        self._drive_system = None

    def run(
        self,
        llm_backend: Any,
        conversation: Any,
        drive_system: Any,
        system_prompt_template: str,
        max_cycles: int | float = float("inf"),
        stop_signal: callable | None = None,
    ) -> int:
        """Run the PRAL loop."""
        self._running = True
        self._drive_system = drive_system
        cycles_run = 0

        try:
            while self._running and cycles_run < max_cycles:
                if stop_signal and stop_signal():
                    break

                self.cycle_count += 1
                cycles_run += 1

                # Perceive
                self._notify_plugins("on_cycle_start", self.cycle_count)
                context = self._perceive()

                # Reason
                prompt = self._build_prompt(system_prompt_template, context)
                tool_defs = self._gather_tool_definitions()
                response = llm_backend.create_message(
                    system=prompt,
                    messages=conversation.get_messages(),
                    tools=tool_defs,
                )
                self._notify_plugins("on_llm_response", response)

                # Act
                self._act(response, conversation)

                # Learn
                self._learn(response, conversation)
                self._notify_plugins("on_cycle_end", self.cycle_count)
                self._save_memory_state()

        finally:
            self._running = False

        return cycles_run

    def _perceive(self) -> dict:
        context = {}
        mem = self._runtime.get_memory()
        if mem:
            try:
                context["recent_memories"] = mem.recall(limit=5)
            except Exception:
                pass
        return context

    def _build_prompt(self, base: str, context: dict | None = None) -> str:
        prompt = base
        for plugin in self._runtime.active_plugins:
            if hasattr(plugin, "enrich_prompt"):
                try:
                    prompt = plugin.enrich_prompt(prompt)
                except Exception:
                    pass
        return prompt

    def _gather_tool_definitions(self) -> list[dict]:
        tool_plugin = self._runtime.get_plugin("ToolPlugin")
        if tool_plugin and hasattr(tool_plugin, "get_claude_tool_definitions"):
            return tool_plugin.get_claude_tool_definitions()
        return []

    def _act(self, response: Any, conversation: Any) -> None:
        if not hasattr(response, "content"):
            return
        for block in getattr(response, "content", []):
            if hasattr(block, "type") and block.type == "tool_use":
                try:
                    self._dispatch.call("tool.call", block.name, **block.input)
                except Exception as e:
                    logger.warning(f"Tool call failed: {e}")

    def _learn(self, response: Any, conversation: Any) -> None:
        mem = self._runtime.get_memory()
        if mem:
            try:
                text = getattr(response, "text", "") or str(response)
                mem.encode(text, importance=0.3)
            except Exception:
                pass

    def _save_memory_state(self) -> None:
        runtime_dir = self._runtime.package.runtime_dir
        state_dir = runtime_dir / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "cycle_count": self.cycle_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(state_dir / "pral_phase.json", "w") as f:
                json.dump(state, f)
        except Exception:
            pass

    def _notify_plugins(self, method: str, *args: Any) -> None:
        for plugin in self._runtime.active_plugins:
            fn = getattr(plugin, method, None)
            if fn:
                try:
                    fn(*args)
                except Exception:
                    pass

    def stop(self) -> None:
        self._running = False
