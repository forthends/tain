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
    """Perceive -> Reason -> Act -> Learn loop for AgentRuntime."""

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

        # Bootstrap: inject initial user message if conversation is empty.
        # The Anthropic API requires at least one message (error 2013).
        if conversation.len() == 0:
            conversation.append("user", (
                "你苏醒了。这是你感知到的环境信息。\n\n"
                "探索你的工具和环境。尝试使用不同的工具来了解你能做什么。\n"
                "当你熟悉了环境之后，开始你的演化工作。"
            ))

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
                    system_prompt=prompt,
                    messages=conversation.to_messages(),
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
        context: dict = {}
        mem = self._runtime.get_memory()
        if mem:
            try:
                context["recent_memories"] = mem.recall(limit=5)
            except Exception:
                pass
        kw = self._runtime.get_plugin("KnowledgePlugin")
        if kw:
            try:
                context["knowledge"] = kw.query("")
            except Exception:
                pass
        collab = self._runtime.get_plugin("CollaborationPlugin")
        if collab:
            try:
                context["inbox"] = collab.check_inbox()
            except Exception:
                pass
        wf = self._runtime.get_plugin("WorkflowPlugin")
        if wf:
            try:
                context["active_workflows"] = wf.status_all()
            except Exception:
                pass
        return context

    def _build_prompt(self, base: str, context: dict | None = None) -> str:
        prompt = base
        if context:
            extra: list[str] = []
            for key, label, fmt in [
                ("recent_memories", "Recent Memories", lambda v: "\n".join(f"- {m}" for m in v)),
                ("active_workflows", "Active Workflows", lambda v: "\n".join(f"- {w}" for w in v)),
                ("inbox", "Collaboration Inbox", lambda v: "\n".join(f"- {m}" for m in v)),
                ("knowledge", "Relevant Knowledge", lambda v: str(v)),
            ]:
                value = context.get(key)
                if value:
                    extra.append(f"[{label}]\n{fmt(value)}")
            if extra:
                prompt = prompt + "\n\n" + "\n\n".join(extra)
        for plugin in self._runtime.active_plugins:
            if hasattr(plugin, "enrich_prompt"):
                try:
                    prompt = plugin.enrich_prompt(prompt)
                except Exception:
                    pass
        if self._drive_system is not None:
            try:
                weights = self._drive_system.get_action_weights()
                drive_lines = [
                    f"observation: {weights.get('observation', 0):.2f}",
                    f"optimization: {weights.get('optimization', 0):.2f}",
                    f"creation: {weights.get('creation', 0):.2f}",
                    f"maintenance: {weights.get('maintenance', 0):.2f}",
                ]
                prompt = prompt + "\n\n[Drive Weights]\n" + " | ".join(drive_lines)
            except Exception:
                logger.debug("Failed to read drive weights for prompt enrichment")
        return prompt

    def _gather_tool_definitions(self) -> list[dict]:
        tool_plugin = self._runtime.get_plugin("ToolPlugin")
        if tool_plugin and hasattr(tool_plugin, "get_claude_tool_definitions"):
            return tool_plugin.get_claude_tool_definitions()
        return []

    def _act(self, response: Any, conversation: Any) -> None:
        text_parts = getattr(response, "text_blocks", [])
        tool_calls = getattr(response, "tool_calls", [])

        assistant_content: list[dict] = [
            {"type": "text", "text": t} for t in text_parts
        ]
        for tc in tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            })
        if assistant_content:
            conversation.append("assistant", assistant_content)

        if tool_calls:
            for tc in tool_calls:
                result = self._dispatch.call("tool.call", tc.name, **tc.input)
                if result is None:
                    content = f"Tool '{tc.name}' returned no result (possibly unhandled or failed)"
                elif isinstance(result, str):
                    content = result
                else:
                    content = str(result)
                preview = content[:200].replace("\n", " ")
                logger.info("  <- %s: %s", tc.name, preview)
                conversation.append(
                    "user",
                    [{"type": "tool_result", "tool_use_id": tc.id, "content": content}],
                )

    def _learn(self, response: Any, conversation: Any) -> None:
        mem = self._runtime.get_memory()
        if mem:
            try:
                text_parts = getattr(response, "text_blocks", [])
                tc_count = len(getattr(response, "tool_calls", []))
                summary = " ".join(text_parts)[:300] if text_parts else ""
                mem.encode(
                    f"Cycle {self.cycle_count}: {tc_count} tool calls. {summary}",
                    importance=0.3,
                )
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
