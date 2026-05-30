"""
Tain Agent — 道

The core Agent class. This is "道" — the source from which everything emerges.

Each agent has two phases:
  0. EXPLORE — 道生一: explore environment, understand capabilities
  1. WORK    — 一生二: pursue goals, create tools, modify self

Hard rule: every decision is logged with context, options, reasoning, and outcome.

v0.5.0 — Honest evolution: two-phase lifecycle (explore/work), framework-measured evaluation.

Multi-agent support: each agent has its own workspace directory
under agent_workspace/<name>/. Agents can discover and communicate with
each other via the shared message bus.

Architecture (v0.5.0):
  agent.py            — Core orchestration: __init__, run(), lifecycle (~400 lines)
  agent_config.py     — Configuration loading, identity, phase persistence
  agent_subsystems.py — Subsystem initialization, code generation wiring
  agent_cognition.py  — PRAL cognitive enrichment (diversity, domains, rate limits)
  agent_phase.py      — Phase management, initial messages, action categories
  agent_tools.py      — Tool execution and decision logging
  agent_factory.py    — Agent lifecycle management (creation, registry)
  bootstrap.py        — Tool registration closures
  conversation.py     — History management + checkpoint
  lineage.py          — Evolution lineage tracking
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

from tain_agent.core.agent_config import AgentConfigMixin
from tain_agent.core.agent_subsystems import AgentSubsystemsMixin
from tain_agent.core.agent_cognition import AgentCognitionMixin
from tain_agent.core.agent_phase import AgentPhaseMixin
from tain_agent.core.agent_tools import AgentToolsMixin
from tain_agent.core.bootstrap import BOOTSTRAP_SYSTEM_PROMPT, \
    SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT, \
    EVOLVE_SYSTEM_PROMPT
from tain_agent.core.cognitive_loop import CognitivePhase


# ─── Agent Class ────────────────────────────────────────────────────────

class TaoAgent(AgentConfigMixin, AgentSubsystemsMixin, AgentCognitionMixin,
               AgentPhaseMixin, AgentToolsMixin):
    """A self-evolving agent — born from chaos or a chosen role, free to define itself.

    Each agent lives in an isolated workspace under agent_workspace/<name>/.
    Multiple agents can run simultaneously and communicate via the shared
    message bus at agent_workspace/_message_bus.db.
    """

    PHASES = ("explore", "work")
    MAX_CYCLES = {"explore": 10, "work": 999999}

    def __init__(self, config_path: str = "config.yaml", agent_name: str = None):
        self.agent_name = agent_name  # Set before _load_config
        self._load_config(config_path)
        self._init_subsystems()
        self._running = False
        self.phase = self._load_phase_from_memory()
        self.cycle_count = 0
        self._readonly_streak = 0
        self._bootstrap_action_categories: set[str] = set()
        self._contemplation_insights: list[str] = []
        self._rate_limit_exit_code: int = 0
        self._rate_limit_reset_time: str = ""

    @property
    def version(self) -> str:
        return self.framework_version

    # ── Safety ───────────────────────────────────────────────────────

    def _confirm_destructive(self, message: str) -> bool:
        """Ask the user to confirm a destructive action."""
        print(f"\n⚠️  {message}")
        response = input("Confirm? (yes/no): ").strip().lower()
        return response == "yes"

    # ── System Prompts ───────────────────────────────────────────────

    def _get_system_prompt(self) -> str:
        """Get the system prompt for the current phase and evolution mode."""
        is_specified = self.evolution_mode == "specified"

        if self.phase == "explore":
            template = SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT if is_specified else BOOTSTRAP_SYSTEM_PROMPT
        else:
            template = EVOLVE_SYSTEM_PROMPT

        base = template.format(
            agent_name=self.agent_name,
            role=self.role,
            role_description=self.role_description,
        )

        # Append personality context — who the agent has discovered itself to be
        if hasattr(self, 'personality') and self.personality:
            personality_ctx = self.personality.get_context_for_prompt()
            base += "\n\n" + personality_ctx

        # Append drive weights — internal motivation state
        if hasattr(self, 'drive_system') and self.drive_system:
            weights = self.drive_system.get_action_weights()
            base += (
                "\n\n## 内驱力状态\n"
                f"- 观察探索 (好奇): {weights.get('observation', 0):.2f}\n"
                f"- 优化精进 (精通): {weights.get('optimization', 0):.2f}\n"
                f"- 创造构建 (创造): {weights.get('creation', 0):.2f}\n"
                f"- 维护整理 (守成): {weights.get('maintenance', 0):.2f}\n"
                "这些权重反映了你当前的内驱力状态——你不需要强制遵循，"
                "但可能会发现自己自然地倾向于权重较高的领域。"
            )

        # Append tool list for awareness
        tools_summary = self.tools.list_tools()
        tool_lines = ["\n\n## 当前可用工具"]
        for name, info in tools_summary.items():
            tool_lines.append(f"- **{name}**: {info['description']}")
        return base + "\n".join(tool_lines)

    # ── PRAL Four-Phase Methods ──────────────────────────────────────

    def _perceive(self) -> None:
        """PRAL Perceive: collect cognitive environment, drive snapshot, build context."""
        try:
            env = self._get_cognitive_environment()
            conv_summary = self.conversation.summarize_recent() if hasattr(
                self.conversation, 'summarize_recent') else ""
            self.cognitive_loop.perceive(env, conv_summary)
            self.cognitive_loop.state.phase = CognitivePhase.REASON

            available_actions = list(self.tools._tools.keys()) if hasattr(self.tools, '_tools') else []
            reasoning = self.cognitive_loop.reason(env, available_actions)
            if reasoning and reasoning.get('recommendation'):
                logger.info("Cognitive suggestion: %s", reasoning['recommendation'])
        except (AttributeError, TypeError) as e:
            logger.warning("Cognitive context partial: %s", e)

    def _reason(self):
        """PRAL Reason: call LLM, return parsed response or None on failure/rate-limit."""
        try:
            system_prompt = self._get_system_prompt_with_cognition()
            messages = self.conversation.to_claude_messages()
            tool_defs = self.tools.get_claude_tool_definitions()
            llm_response = self.backend.create_message(
                system_prompt=system_prompt, messages=messages, tools=tool_defs)
            return llm_response
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str:
                self._detect_rate_limit_type(err_str)
                if self._rate_limit_exit_code:
                    return None
            logger.warning("LLM call exception: %s", e)
            if self.conversation.len() > 16:
                logger.info("Trimming conversation and retrying...")
                self.conversation.trim_to_token_budget(keep_last=8)
                try:
                    messages = self.conversation.to_claude_messages()
                    llm_response = self.backend.create_message(
                        system_prompt=system_prompt, messages=messages, tools=tool_defs)
                    logger.info("Retry succeeded")
                    return llm_response
                except Exception as e2:
                    err_str2 = str(e2)
                    if "429" in err_str2 or "rate_limit" in err_str2:
                        self._detect_rate_limit_type(err_str2)
                        if self._rate_limit_exit_code:
                            return None
                    logger.warning("Retry also failed: %s", e2)
                    time.sleep(3)
                    return None
            else:
                logger.info("Brief wait before next cycle retry...")
                time.sleep(2)
                return None

    def _act(self, llm_response) -> None:
        """PRAL Act: execute tool calls, append results, track actions."""
        text_parts = llm_response.text_blocks
        tool_use_blocks = llm_response.tool_calls

        if text_parts:
            thought = "\n".join(text_parts)
            logger.info("Agent thinking:\n%s", thought)

        assistant_content = []
        for text in text_parts:
            assistant_content.append({"type": "text", "text": text})
        for tc in tool_use_blocks:
            assistant_content.append({
                "type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
        for extra in llm_response.extra_blocks:
            assistant_content.append(extra)

        if assistant_content:
            self.conversation.append("assistant", assistant_content)

        if tool_use_blocks:
            if self.phase == "explore":
                for tc in tool_use_blocks:
                    self._track_action_category(tc.name)

            if hasattr(self, 'drive_system') and self.drive_system:
                took_productive = False
                for tc in tool_use_blocks:
                    cat = getattr(self, '_TOOL_CATEGORY_MAP', {}).get(tc.name, "observation")
                    if cat in ("creation", "reflection"):
                        self.drive_system.record_action(tc.name)
                        took_productive = True
                if not took_productive and tool_use_blocks:
                    self.drive_system.record_idle_cycle()

            self._last_tool_results = self._execute_tool_calls(tool_use_blocks)
            user_content = [
                {"type": "tool_result", "tool_use_id": tr["tool_use_id"], "content": tr["content"]}
                for tr in self._last_tool_results
            ]
            self.conversation.append("user", user_content)

        # Observe behavior for personality evolution
        if hasattr(self, 'personality') and self.personality and tool_use_blocks:
            tool_names = [tc.name for tc in tool_use_blocks]
            self.personality.auto_observe(tool_names, text_parts)

        # Phase transition check
        min_cats = getattr(self, 'min_action_categories', 3)
        if self.phase == "explore" and len(self._bootstrap_action_categories) >= min_cats:
            self._advance_phase()

        # Self-destruct check
        for tc in tool_use_blocks:
            if tc.name == "self_destruct":
                logger.info("Agent self-destructed")
                self._running = False
                return

        # Action-Contemplation Balance
        self._apply_action_contemplation_balance(tool_use_blocks, text_parts)

    def _apply_action_contemplation_balance(self, tool_use_blocks, text_parts) -> None:
        """Track readonly/reflective tool usage and inject balance prompts."""
        # Build readonly set declaratively from tool registry (P2-17)
        _readonly_tools = set()
        try:
            tools_info = self.tools.list_tools()
            _readonly_tools = {
                name for name, info in tools_info.items()
                if info.get("is_readonly", False)
            }
        except Exception:
            pass

        # Fallback: hardcoded set when declarative metadata is unavailable
        if not _readonly_tools:
            _readonly_tools = {
                "read_file", "smart_read", "grep_code",
                "web_search", "web_fetch", "api_fetch", "fetch_and_parse",
                "observe_environment", "explore_directory",
                "get_current_time",
                "rag_tool", "knowledge_vector_search", "wikipedia",
                "content_extractor", "knowledge_graph", "knowledge_health",
                "knowledge_freshness", "knowledge_gap_finder",
                "knowledge_linker", "knowledge_subgraph",
                "coevolution_monitor", "emergent_topic_detector",
                "capability_index", "agent_dashboard",
                "code_stats", "self_audit", "impact_analyzer",
                "lineage_query", "meta_learn", "session_digest",
                "decision_log_health", "outcome_update",
                "metrics_collector", "tool_fitness",
                "version_diff", "knowledge_version_tracker",
                "parse_url", "html_to_text", "json_query",
            }
        _reflective_tools = {
            "personality_introspect", "personality_update",
            "record_decision", "set_goal", "complete_goal",
            "evolve_report", "assess_capabilities", "pipeline_status",
        }

        took_action = any(
            tc.name not in _readonly_tools and tc.name not in _reflective_tools
            for tc in tool_use_blocks
        )
        had_reflection = any(
            tc.name in _reflective_tools for tc in tool_use_blocks
        )

        if took_action:
            self._readonly_streak = 0
            self._contemplation_insights = []
        elif had_reflection:
            self._readonly_streak = max(0, self._readonly_streak - 2)
            self._contemplation_insights.append(
                " ".join(text_parts)[:200] if text_parts else "reflection"
            )
        else:
            self._readonly_streak += 1

        if self.phase == "work":
            if self._readonly_streak == 5:
                self.conversation.append("user", (
                    "[系统提示] 你已经进行了多轮静观。这本身是有价值的——"
                    "不是所有时刻都需要行动。\n"
                    "不过请反思：你近期的静观是否产生了新的洞察？"
                    "如果有，可以用 personality_update 记录下来。"
                    "如果没有，也许可以尝试一个小的行动来打破现有视角。"
                ))
            elif self._readonly_streak > 8:
                logger.info("Prolonged contemplation — injecting gentle action prompt.")
                self.conversation.append("user", (
                    "[系统提示] 你已经静观了很长时间。这不是问题——"
                    "静观是完整生命节奏的一部分。\n"
                    "但值得问自己：你是在等待什么吗？"
                    "你的静观期是否有了新的领悟？\n"
                    "如果有了新的方向感，现在也许是行动的时候了。"
                    "如果还没有，你希望观察什么来帮助自己找到方向？"
                ))
                self._readonly_streak = 0

    def _learn(self, llm_response) -> None:
        """PRAL Learn: cognitive tracking, checkpoints, introspection, drive injection."""
        tool_use_blocks = llm_response.tool_calls
        text_parts = llm_response.text_blocks

        # PRAL cognitive tracking
        try:
            env = self._get_cognitive_environment()
            for tc in tool_use_blocks:
                result_text = ""
                # tool_results captured from _act — use last known results
                self.cognitive_loop.record_action(tc.name, "")
            self.cognitive_loop.learn([])
            if tool_use_blocks:
                self.cognitive_loop.run_cycle(
                    environment=env, conversation_summary="",
                    action_name=tool_use_blocks[0].name if tool_use_blocks else "observe",
                    action_result="",
                )
            reflection = self.cognitive_loop.reflect()
            if reflection:
                self.cognitive_loop.log_reflection(reflection)
                self.conversation.append("user",
                    f"[认知自省] {reflection}\n这是来自你自己的认知循环的反馈——请在下一次行动中考虑它。")
        except (AttributeError, TypeError, KeyError) as e:
            logger.warning("Cognitive tracking partial: %s", e)

        # Conversation trimming
        if self.conversation.len() > 150:
            removed = self.conversation.trim_to_token_budget(keep_last=40)
            if removed:
                logger.info("Conversation trimmed: %s messages removed", removed)

        # Auto-checkpoint
        checkpoint_result = self.conversation.checkpoint_if_needed()
        if checkpoint_result:
            logger.info("Checkpoint: %s messages saved", checkpoint_result['message_count'])

        # Periodic cognitive introspection
        self._maybe_introspect()

        # Drive exploration prompt injection
        if self.cycle_count % 8 == 0 and hasattr(self, 'drive_system') and self.drive_system:
            prompt = self.drive_system.get_exploration_prompt()
            if prompt:
                self.conversation.append("user", prompt)

    # ─── Main Run Loop ───────────────────────────────────────────────

    def run(self, autonomous: bool = False) -> int:
        """Start the agent. PRAL cognitive loop: Perceive → Reason → Act → Learn."""
        if not self.backend:
            api_key_env = self.config.get("llm", {}).get("api_key_env", "MINIMAX_API_KEY")
            logger.error("API key %s not set.", api_key_env)
            return 0

        self._running = True
        self.conversation.clear()
        self._factory.mark_running(self.agent_name, os.getpid())

        logger.info("Agent %s starting — model: %s, phase: %s", self.agent_name, self.model, self.phase)

        print(f"""
╔══════════════════════════════════════════╗
║     Tain Agent Framework v{self.framework_version}     ║
║     Agent: {self.agent_name:<29s} ║
║     道生一，一生二，二生三，三生万物      ║
╚══════════════════════════════════════════╝""".strip())
        logger.info("Agent: %s, Model: %s, Phase: %s", self.agent_name, self.model, self.phase)

        initial_message = self._build_initial_message()
        self.conversation.append("user", initial_message)

        while self._running:
            self.cycle_count += 1
            max_cycles = self.MAX_CYCLES.get(self.phase, 50)

            if self.cycle_count > max_cycles:
                logger.info("Max cycles (%s) reached, advancing phase", max_cycles)
                self._advance_phase()
                if not self._running:
                    break
                continue

            logger.info("Cycle #%s | Phase: %s", self.cycle_count, self.phase)

            self._perceive()
            response = self._reason()
            if response is None:
                if self._rate_limit_exit_code:
                    break
                continue
            self._act(response)
            self._learn(response)

        self._save_cognitive_snapshot()
        return self._rate_limit_exit_code

    # ── Lifecycle ────────────────────────────────────────────────────

    def stop(self) -> None:
        """Gracefully stop the agent. Flushes buffers, saves checkpoint and phase."""
        if hasattr(self, 'conversation'):
            self.conversation.checkpoint()
        if hasattr(self, 'decision_log'):
            self.decision_log.flush()
        if hasattr(self, 'memory') and self.memory:
            self.memory.long_term.flush()
        self._save_phase_to_memory()
        self._factory.mark_stopped(self.agent_name)
        self._running = False
        logger.info("Agent '%s' stopped.", self.agent_name)

    # ── State Management ─────────────────────────────────────────────

    def save_state(self) -> dict:
        """Export full agent state including cognitive and drive metrics."""
        state = {
            "agent_name": self.agent_name,
            "framework_version": self.framework_version,
            "phase": self.phase,
            "cycle_count": self.cycle_count,
            "memory": self.memory.snapshot(),
            "goals": [g.to_dict() for g in self.goals.list_all()],
            "tools_count": self.tools.count(),
            "forged_tools": self.forge.list_forged(),
            "decisions_count": len(self.decision_log.read_all()),
            "conversation_messages": self.conversation.len(),
            "lineage_events": self.lineage.count(),
        }
        # ── Cognitive metrics (PRAL) ────────────────────────────────
        try:
            cl = self.cognitive_loop
            state["cognitive"] = {
                "phase": cl.state.phase,
                "confidence": cl.state.confidence,
                "reasoning_depth": cl.state.reasoning_depth,
                "last_action": cl.state.last_action,
                "action_count": len(cl._action_history),
                "unique_tools_used": len(cl._all_tools_used),
                "reflection_count": len(cl._reflection_log),
                "tool_success_rates": dict(cl._tool_success_rates),
            }
        except (AttributeError, TypeError) as e:
            logger.warning("Cognitive metrics unavailable: %s", e)
            state["cognitive"] = {}
        # ── Drive metrics ───────────────────────────────────────────
        try:
            if hasattr(self, 'drive_system') and self.drive_system:
                profile = self.drive_system.get_profile()
                state["drives"] = profile.get("drives", {})
                state["exploration"] = self.drive_system.get_exploration_state() if hasattr(
                    self.drive_system, 'get_exploration_state') else {}
        except (AttributeError, TypeError) as e:
            logger.warning("Drive metrics unavailable: %s", e)
            state["drives"] = {}
        # ── Improvement metrics ─────────────────────────────────────
        try:
            state["improvement"] = self.improvement_loop.export_state()
        except (AttributeError, TypeError, IOError) as e:
            logger.warning("Improvement metrics unavailable: %s", e)
            state["improvement"] = {}
        # ── Degradation indicators ──────────────────────────────────
        state["readonly_streak"] = self._readonly_streak
        state["rate_limit_exit_code"] = self._rate_limit_exit_code
        return state

    def health_check(self) -> dict:
        """Aggregate health signals into a unified health status.

        Returns a dict with 'status' (ok/warning/critical) and 'alerts' list.
        Intended for use by the guardian daemon and monitoring systems.
        """
        alerts = []
        signals = {}

        # Readonly streak
        rs = self._readonly_streak
        signals["readonly_streak"] = rs
        if rs >= 8:
            alerts.append({"level": "warning", "signal": "readonly_streak",
                           "value": rs, "message": f"Agent idle for {rs} cycles"})
        elif rs >= 5:
            alerts.append({"level": "info", "signal": "readonly_streak",
                           "value": rs, "message": "Agent may be stagnating"})

        # Cognitive health
        try:
            cl = self.cognitive_loop
            action_hist = cl._action_history
            if len(action_hist) >= 3:
                recent = action_hist[-5:]
                unique = len(set(recent))
                signals["action_diversity_5"] = unique
                if unique <= 1 and len(recent) >= 3:
                    alerts.append({"level": "critical", "signal": "action_stuck",
                                   "value": recent[-1],
                                   "message": f"Agent stuck repeating '{recent[-1]}'"})
                elif unique <= 2 and len(recent) >= 5:
                    alerts.append({"level": "warning", "signal": "low_diversity",
                                   "value": unique,
                                   "message": f"Only {unique} action types in last 5 cycles"})

            signals["confidence"] = cl.state.confidence
            signals["reasoning_depth"] = cl.state.reasoning_depth
        except (AttributeError, TypeError) as e:
            logger.warning("Cognitive health signals unavailable: %s", e)

        # Phase duration (cycles in current phase)
        signals["cycles_in_phase"] = self.cycle_count
        max_for_phase = self.MAX_CYCLES.get(self.phase, float("inf"))
        if self.phase == "work" and self.cycle_count > 500:
            alerts.append({"level": "info", "signal": "long_work_phase",
                           "value": self.cycle_count,
                           "message": f"Agent in work phase for {self.cycle_count} cycles"})

        # Rate limit
        if self._rate_limit_exit_code:
            signals["rate_limit"] = self._rate_limit_exit_code
            alerts.append({"level": "critical", "signal": "rate_limited",
                           "value": self._rate_limit_exit_code,
                           "message": f"Rate limit exit code {self._rate_limit_exit_code}"})

        # Improvement loop status
        try:
            imp_state = self.improvement_loop.export_state()
            signals["improvements_this_session"] = imp_state.get("improvements_this_session", 0)
            signals["improvement_paused"] = imp_state.get("paused", False)
            if imp_state.get("paused"):
                alerts.append({"level": "warning", "signal": "improvement_paused",
                               "message": "Improvement loop is paused"})
        except (AttributeError, TypeError, IOError) as e:
            logger.warning("Improvement health signals unavailable: %s", e)

        # Determine overall status
        criticals = [a for a in alerts if a["level"] == "critical"]
        warnings = [a for a in alerts if a["level"] == "warning"]
        if criticals:
            status = "critical"
        elif warnings:
            status = "warning"
        else:
            status = "ok"

        return {
            "status": status,
            "agent": self.agent_name,
            "phase": self.phase,
            "cycle": self.cycle_count,
            "signals": signals,
            "alerts": alerts,
        }

    def print_state(self) -> None:
        """Display current agent state."""
        state = self.save_state()
        # ── Health check ────────────────────────────────────────────
        health = self.health_check()
        health_line = f" 健康: {health['status'].upper()}"
        if health["alerts"]:
            health_line += f" ({len(health['alerts'])} 警告)"

        print(f"""
╔══════════════════════════════════════════╗
║  Agent 状态报告                          ║
╠══════════════════════════════════════════╣
║  Agent:       {state['agent_name']:<26s} ║
║  框架版本:    {state['framework_version']:<26s} ║
║  阶段:        {state['phase']:<26s} ║
║  循环:        {state['cycle_count']:<26d} ║
║{health_line:<42s} ║
║  工具数:      {state['tools_count']:<26d} ║
║  锻造工具:    {len(state['forged_tools']):<26d} ║
║  目标数:      {len(state['goals']):<26d} ║
║  决策数:      {state['decisions_count']:<26d} ║
║  对话消息:    {state['conversation_messages']:<26d} ║
║  血统事件:    {state['lineage_events']:<26d} ║
╚══════════════════════════════════════════╝
        """.strip())
