"""PRAL cognitive loop — Perceive → Reason → Act → Learn."""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
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
        self._drive_system = None

    def run(self, llm_backend, conversation, drive_system, system_prompt_template: str,
            max_cycles: int | float = float("inf"), stop_signal: callable = None) -> int:
        """Execute PRAL cycles until stop."""
        self._drive_system = drive_system
        self._running = True

        # Bootstrap: inject initial user message if conversation is empty.
        # The Anthropic API requires at least one message (error 2013).
        if conversation.len() == 0:
            conversation.append("user", (
                "你苏醒了。这是你感知到的环境信息。\n\n"
                "探索你的工具和环境。尝试使用不同的工具来了解你能做什么。\n"
                "当你熟悉了环境之后，开始你的演化工作。"
            ))

        while self._running:
            self.cycle_count += 1
            if self.cycle_count > max_cycles:
                break
            if stop_signal and stop_signal():
                break

            logger.info("── Cycle #%s ──", self.cycle_count)
            self._notify_plugins("on_cycle_start", self.cycle_count)

            # 1. PERCEIVE
            context = self._perceive()

            # 2. REASON
            system_prompt = self._build_prompt(system_prompt_template, context)
            response = llm_backend.create_message(
                system_prompt=system_prompt,
                messages=conversation.to_claude_messages(),
                tools=self._gather_tool_definitions(),
            )
            if response is None:
                continue

            # Log the LLM's thinking to stdout (visible in Live tab).
            for text in response.text_blocks:
                for line in text.split("\n"):
                    logger.info("  %s", line)
            if response.tool_calls:
                names = [tc.name for tc in response.tool_calls]
                logger.info("  🔧 Tools: %s", ", ".join(names))

            self._notify_plugins("on_llm_response", response)

            # 3. ACT
            self._act(response, conversation)

            # 4. LEARN
            self._learn(response, conversation)
            self._notify_plugins("on_cycle_end", self.cycle_count)
            self._save_memory_state()

            try:
                conversation.trim_to_token_budget(keep_last=40)
            except AttributeError:
                logger.debug("Conversation object does not support token budget trimming; skipping")

        return 0

    def _perceive(self) -> dict:
        ctx: dict = {}
        mem = self._lm.get("memory")
        if mem:
            ctx["memories"] = mem.recall(limit=5)
        kw = self._lm.get("knowledge")
        if kw:
            ctx["knowledge"] = kw.query("")
        collab = self._lm.get("collaboration")
        if collab:
            ctx["inbox"] = collab.check_inbox()
        wf = self._lm.get("workflow")
        if wf:
            ctx["active_workflows"] = wf.status_all()
        return ctx

    def _build_prompt(self, base: str, context: dict | None = None) -> str:
        prompt = base
        if context:
            extra: list[str] = []
            for key, label, fmt in [
                ("memories", "Recent Memories", lambda v: "\n".join(f"- {m}" for m in v)),
                ("active_workflows", "Active Workflows", lambda v: "\n".join(f"- {w}" for w in v)),
                ("inbox", "Collaboration Inbox", lambda v: "\n".join(f"- {m}" for m in v)),
                ("knowledge", "Relevant Knowledge", lambda v: str(v)),
            ]:
                value = context.get(key)
                if value:
                    extra.append(f"[{label}]\n{fmt(value)}")
            if extra:
                prompt = prompt + "\n\n" + "\n\n".join(extra)
        for name in ["identity", "memory", "knowledge", "skill"]:
            plugin = self._lm.get(name)
            if plugin:
                prompt = plugin.enrich_prompt(prompt)
        # Drive system enriches the prompt too (not a plugin)
        if self._drive_system is not None:
            try:
                weights = self._drive_system.get_action_weights()
                drive_lines = [f"observation: {weights.get('observation', 0):.2f}",
                               f"optimization: {weights.get('optimization', 0):.2f}",
                               f"creation: {weights.get('creation', 0):.2f}",
                               f"maintenance: {weights.get('maintenance', 0):.2f}"]
                prompt = prompt + "\n\n[Drive Weights]\n" + " | ".join(drive_lines)
            except Exception:
                logger.debug("Failed to read drive weights for prompt enrichment")
        return prompt

    def _gather_tool_definitions(self):
        tool_plugin = self._lm.get("tool")
        if tool_plugin:
            return tool_plugin.get_claude_tool_definitions()
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
                if result is None:
                    content = f"Tool '{tc.name}' returned no result (possibly unhandled or failed)"
                elif isinstance(result, str):
                    content = result
                else:
                    content = str(result)
                # Log tool result summary (visible in Live tab).
                preview = content[:200].replace("\n", " ")
                logger.info("  ← %s: %s", tc.name, preview)
                conversation.append("user", [{"type": "tool_result", "tool_use_id": tc.id, "content": content}])

    def _learn(self, response, conversation) -> None:
        mem = self._lm.get("memory")
        if mem:
            mem.encode(f"Cycle {self.cycle_count}: {len(response.tool_calls)} tool calls", importance=0.3)

    def _save_memory_state(self) -> None:
        """Write cycle_count and phase to workspace logs/memory.json for WebUI."""
        ws = self._lm._ctx.workspace_path
        if ws is None:
            return
        logs_dir = ws / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.now(timezone.utc).isoformat()
        phase = "active" if self.cycle_count > 0 else "unknown"
        state = {
            "cycle_count": {"value": self.cycle_count, "updated_at": now_iso},
            "agent_phase": {"value": phase, "updated_at": now_iso},
        }
        (logs_dir / "memory.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
