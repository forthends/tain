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

        # Evolution state
        self._llm_backend = None
        self._evolution_count = 0
        self._last_evolution_at: float | None = None

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
        self._llm_backend = llm_backend
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
            except (AttributeError, RuntimeError) as e:
                logger.debug("Memory recall failed: %s", e)
        kw = self._runtime.get_plugin("KnowledgePlugin")
        if kw:
            try:
                context["knowledge"] = kw.query("")
            except (AttributeError, RuntimeError) as e:
                logger.debug("Knowledge query failed: %s", e)
        collab = self._runtime.get_plugin("CollaborationPlugin")
        if collab:
            try:
                context["inbox"] = collab.check_inbox()
            except (AttributeError, RuntimeError) as e:
                logger.debug("Collaboration check_inbox failed: %s", e)
        wf = self._runtime.get_plugin("WorkflowPlugin")
        if wf:
            try:
                context["active_workflows"] = wf.status_all()
            except (AttributeError, RuntimeError) as e:
                logger.debug("Workflow status_all failed: %s", e)
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
                except (AttributeError, RuntimeError) as e:
                    logger.debug("Plugin '%s' enrich_prompt failed: %s", plugin.__class__.__name__, e)
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
                result = self._dispatch.call_or_none("tool.call", tc.name, **tc.input)
                tool_failed = (result is None)
                if result is None:
                    content = f"Tool '{tc.name}' returned no result (possibly unhandled or failed)"
                elif isinstance(result, str):
                    content = result
                else:
                    content = str(result)
                preview = content[:200].replace("\n", " ")
                logger.info("  <- %s: %s", tc.name, preview)
                # Record tool result for evolution task_completion metric
                kw = self._runtime.get_plugin("KnowledgePlugin")
                if kw and hasattr(kw, 'add_dynamic'):
                    try:
                        kw.add_dynamic({
                            "type": "tool_result",
                            "tool_name": tc.name,
                            "success": not tool_failed,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        # Keep only last 100 entries
                        if len(kw._dynamic) > 100:
                            kw._dynamic.pop(0)
                    except Exception:
                        pass
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
            except (AttributeError, RuntimeError) as e:
                logger.debug("Memory encode failed in _learn: %s", e)

        # ── Gated evolution hook ──
        if self._should_evolve():
            self._trigger_evolution(response, conversation)

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
        except OSError as e:
            logger.debug("Failed to save PRAL phase state: %s", e)

    def _notify_plugins(self, method: str, *args: Any) -> None:
        for plugin in self._runtime.active_plugins:
            fn = getattr(plugin, method, None)
            if fn:
                try:
                    fn(*args)
                except (AttributeError, RuntimeError) as e:
                    logger.debug("Plugin '%s' %s hook failed: %s", plugin.__class__.__name__, method, e)

    def stop(self) -> None:
        self._running = False

    def _get_evolution_config(self) -> dict:
        """Get evolution configuration from runtime config with defaults."""
        raw = self._runtime.config.get("evolution", {}) if self._runtime.config else {}
        return {
            "enabled": raw.get("enabled", True),
            "min_interval_seconds": raw.get("min_interval_seconds", 300),
            "max_improvements_per_session": raw.get("max_improvements_per_session", 3),
            "min_trigger_score": raw.get("min_trigger_score", 0.3),
        }

    def _assess_evolution_need(self) -> float:
        """Assess evolution need using tool-call failure rate and goal gaps.

        Mirrors AutonomousEvolutionLoop._assess_need() dimensions so the
        two paths do not diverge.
        """
        tool_plugin = self._runtime.get_plugin("ToolPlugin")
        knowledge_plugin = self._runtime.get_plugin("KnowledgePlugin")

        # ── capability_gap: goal-driven ──
        try:
            tools = tool_plugin.list_tools() if hasattr(tool_plugin, 'list_tools') else {}
            tool_names = set(tools.keys())
        except Exception:
            tool_names = set()

        try:
            active_goals = (
                knowledge_plugin.goals.list_active()
                if knowledge_plugin and hasattr(knowledge_plugin, 'goals')
                else []
            )
        except Exception:
            active_goals = []

        if active_goals:
            gap_count = sum(
                1 for g in active_goals
                if g.get("required_capability", "") and
                g["required_capability"] not in tool_names
            )
            capability_gap = round(gap_count / len(active_goals), 4) if gap_count else 0.0
        else:
            count = len(tool_names)
            capability_gap = round((3 - count) / 3, 4) if count < 3 else 0.0

        # ── task_completion: tool failure rate ──
        try:
            dynamic = getattr(knowledge_plugin, '_dynamic', [])
            log_entries = [
                e for e in dynamic
                if isinstance(e, dict) and e.get("type") == "tool_result"
            ]
            if log_entries:
                recent = log_entries[-20:]
                failures = sum(1 for e in recent if not e.get("success", False))
                task_completion = round(failures / len(recent), 4)
            else:
                task_completion = 0.0
        except Exception:
            task_completion = 0.0

        # ── goal_achievement: uncompleted ratio ──
        goal_achievement = 0.0
        if knowledge_plugin and hasattr(knowledge_plugin, "goals"):
            try:
                goals = knowledge_plugin.goals.list_all()
                if goals:
                    completed = sum(
                        1 for g in goals
                        if g.get("status") == "completed"
                    )
                    goal_achievement = (len(goals) - completed) / len(goals)
            except Exception:
                pass

        total_weight = 0.30 + 0.35 + 0.25  # = 0.90
        raw_score = 0.30 * capability_gap + 0.35 * task_completion + 0.25 * goal_achievement
        return round(raw_score / total_weight, 4)

    def _should_evolve(self) -> bool:
        """Return True if an evolution cycle should be triggered now."""
        cfg = self._get_evolution_config()
        if not cfg.get("enabled", True):
            return False
        if self._evolution_count >= cfg.get("max_improvements_per_session", 3):
            return False
        if self._last_evolution_at is not None:
            import time as _time
            elapsed = _time.time() - self._last_evolution_at
            if elapsed < cfg.get("min_interval_seconds", 300):
                return False
        need_score = self._assess_evolution_need()
        threshold = cfg.get("min_trigger_score", 0.3)
        return need_score >= threshold

    def _trigger_evolution(self, response: Any, conversation: Any) -> None:
        """Run one gated evolution cycle via the package evolution adapter."""
        import time as _time
        self._evolution_count += 1
        self._last_evolution_at = _time.time()
        self._runtime._llm_backend = self._llm_backend

        try:
            from tain_agent.evolution.autonomous_loop import create_package_evolver

            gap_detector, mutation_generator, contract_checker, online_verifier = \
                create_package_evolver(self._runtime)

            result = self._runtime.package.evolve(
                gap_detector, mutation_generator,
                contract_checker, online_verifier,
            )
            logger.info(
                "Evolution cycle #%d: %s",
                self._evolution_count,
                result.summary if hasattr(result, 'summary') else str(result),
            )
            self._notify_plugins("on_evolution_cycle", result)
        except (ImportError, RuntimeError) as e:
            logger.exception("Evolution cycle failed: %s", e)
            self._last_evolution_at = _time.time() + 600
