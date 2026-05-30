"""PRAL cognitive loop — Perceive → Reason → Act → Learn."""

from __future__ import annotations
import logging
from tain_agent.kernel.lifecycle import LifecycleManager
from tain_agent.kernel.dispatch import Dispatch

logger = logging.getLogger(__name__)


class PRALLoop:
    """Drives the main cognitive cycle. Plugins enrich each phase via hooks."""

    def __init__(self, lifecycle: LifecycleManager, dispatch: Dispatch):
        self._lm = lifecycle
        self._dispatch = dispatch
        self._running = False
        self.cycle_count = 0

    def run(self, llm_backend, conversation, drive_system, system_prompt_template: str,
            max_cycles: int = float("inf"), stop_signal: callable = None) -> int:
        """Execute PRAL cycles until stop."""
        self._running = True
        while self._running:
            self.cycle_count += 1
            if self.cycle_count > max_cycles:
                break
            if stop_signal and stop_signal():
                break

            logger.info("Cycle #%s", self.cycle_count)
            self._notify_plugins("on_cycle_start", self.cycle_count)

            # 1. PERCEIVE
            context = self._perceive()

            # 2. REASON
            system_prompt = self._build_prompt(system_prompt_template)
            response = llm_backend.create_message(
                system_prompt=system_prompt,
                messages=conversation.to_claude_messages(),
                tools=self._gather_tool_definitions(),
            )
            if response is None:
                continue
            self._notify_plugins("on_llm_response", response)

            # 3. ACT
            self._act(response, conversation)

            # 4. LEARN
            self._learn(response, conversation)
            self._notify_plugins("on_cycle_end", self.cycle_count)

            conversation.trim_to_token_budget(keep_last=40)

        return 0

    def _perceive(self) -> dict:
        ctx: dict = {}
        mem = self._lm.get("memory")
        if mem:
            ctx["memories"] = mem.recall("recent context", k=5)
        kw = self._lm.get("knowledge")
        if kw:
            ctx["knowledge"] = kw.query("recent topic")
        collab = self._lm.get("collaboration")
        if collab:
            ctx["inbox"] = collab.check_inbox()
        wf = self._lm.get("workflow")
        if wf:
            ctx["active_workflows"] = wf.status_all()
        return ctx

    def _build_prompt(self, base: str) -> str:
        prompt = base
        for name in ["identity", "memory", "knowledge", "skill"]:
            plugin = self._lm.get(name)
            if plugin:
                prompt = plugin.enrich_prompt(prompt)
        # Drive system enriches the prompt too (not a plugin)
        return prompt

    def _gather_tool_definitions(self):
        tool_plugin = self._lm.get("tool")
        if tool_plugin:
            return tool_plugin.list_tools()
        return []

    def _act(self, response, conversation) -> None:
        text_parts = response.text_blocks
        tool_calls = response.tool_calls

        assistant_content = [{"type": "text", "text": t} for t in text_parts]
        for tc in tool_calls:
            assistant_content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
        if assistant_content:
            conversation.append("assistant", assistant_content)

        if tool_calls:
            for tc in tool_calls:
                result = self._dispatch.call("tool.call", tc.name, **tc.input)
                content = result if isinstance(result, str) else str(result)
                conversation.append("user", [{"type": "tool_result", "tool_use_id": tc.id, "content": content}])

    def _learn(self, response, conversation) -> None:
        mem = self._lm.get("memory")
        if mem:
            mem.encode(f"Cycle {self.cycle_count}: {len(response.tool_calls)} tool calls", importance=0.3)

    def _notify_plugins(self, method: str, *args) -> None:
        for plugin in self._lm.plugins.values():
            try:
                fn = getattr(plugin, method, None)
                if fn:
                    fn(*args)
            except Exception:
                logger.exception("Plugin hook %s failed", method)

    def stop(self) -> None:
        self._running = False
