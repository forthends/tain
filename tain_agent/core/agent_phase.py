"""
AgentPhaseMixin — phase management, initial messages, and action category tracking.
"""
import json
import textwrap

from tain_agent.core.environment import full_environment_scan


class AgentPhaseMixin:
    """Mixin for phase transitions, initial messages per phase, and action tracking."""

    # ── Tool Category Map ──────────────────────────────────────────

    _TOOL_CATEGORY_MAP: dict[str, str] = {
        # Observation tools
        "read_file": "observation",
        "smart_read": "observation",
        "grep_code": "observation",
        "observe_environment": "observation",
        "explore_directory": "observation",
        "get_current_time": "observation",
        "list_available_tools": "observation",
        "web_search": "observation",
        "web_fetch": "observation",
        "parse_url": "observation",
        "html_to_text": "observation",
        "json_query": "observation",
        "rag_tool": "observation",
        "knowledge_vector_search": "observation",
        "wikipedia": "observation",
        "content_extractor": "observation",
        # Creation tools
        "write_file": "creation",
        "forge_tool": "creation",
        "execute_code": "creation",
        "run_improvement_pipeline": "creation",
        "modify_self_file": "creation",
        "safe_modify": "creation",
        "backup_file": "creation",
        "sub_agent_spawn": "creation",
        "spawn_sub_agent": "creation",
        "multi_agent": "creation",
        "multi_agent_coordinator": "creation",
        "external_fetch": "observation",
        "external_subscribe": "creation",
        # Reflection tools
        "personality_introspect": "reflection",
        "personality_update": "reflection",
        "record_decision": "reflection",
        "set_goal": "reflection",
        "complete_goal": "reflection",
        "evolve_report": "reflection",
        "drive_introspect": "reflection",
        "trial_status": "reflection",
        "evolution_metrics": "reflection",
        "sub_agent_status": "reflection",
        "external_status": "reflection",
    }

    # ── Initial Messages ───────────────────────────────────────────

    def _build_initial_message(self) -> str:
        """Build the initial message for the current phase."""
        if self.phase == "bootstrap":
            env = full_environment_scan(self.tools, base_dir=str(self._workspace_path))
            env_msg = textwrap.dedent(f"""\
                你苏醒了。这是你感知到的环境信息：

                ```json
                {json.dumps(env, ensure_ascii=False, indent=2)}
                ```

                在定义自己之前，你将经历一系列"初醒试炼"——不同的存在模式体验。
                通过行动来感受，而不是通过思考来选择。
                你的身份会从这些真实的体验中自然浮现。""")

            # Phase 2: Inject first trial prompt
            first_trial = self.trial_scheduler.start_next_trial()
            if first_trial:
                return env_msg + "\n\n" + first_trial
            return env_msg

        elif self.phase == "self_define":
            past_decisions = self.decision_log.filter_by_phase("bootstrap")

            # Phase 2: Include trial experience summary if available
            trial_summary = ""
            if hasattr(self, 'trial_scheduler') and self.trial_scheduler.completed_count > 0:
                trial_summary = "\n\n" + self.trial_scheduler.get_summary_for_self_define()

            return textwrap.dedent(f"""\
                初醒阶段完成。回顾你的经历：

                ```json
                {json.dumps(past_decisions, ensure_ascii=False, indent=2)}
                ```
                {trial_summary}

                基于你的实际体验（而非抽象标签），你注意到了自己行为中的什么模式？
                你的第一个目标应该与你实际展现的行为倾向一致。
                如果需要新工具，使用 forge_tool 创造它。""")

        else:  # evolve
            current_goal = self.goals.get_current()
            goal_text = f"当前目标: {current_goal.description}" if current_goal else "没有活动目标。"
            return f"进入演化阶段。{goal_text}\n你可以追求目标、创造工具、从互联网学习、或修改自己。\n你接下来要做什么？"

    # ── Action Category Tracking ───────────────────────────────────

    def _track_action_category(self, tool_name: str) -> None:
        """Track which action categories the agent has used during bootstrap."""
        category = self._TOOL_CATEGORY_MAP.get(tool_name, "other")
        if category not in self._bootstrap_action_categories:
            self._bootstrap_action_categories.add(category)
            print(f"  🏷️  首次使用 {category} 类工具: {tool_name} "
                  f"({len(self._bootstrap_action_categories)}/3 类已解锁)")

    # ── Phase Transitions ──────────────────────────────────────────

    def _should_advance_from_bootstrap(self, text_parts: list[str]) -> bool:
        """Advance from bootstrap when the agent has taken diverse actions.

        Phase 2: identity emerges from action patterns, not from menu selection.
        Two paths to advance:
          1. Trial-based: all 5 trials completed (primary path)
          2. Action-based: used 2+ categories of tools over 5+ cycles (fallback)
        """
        # Path 1: All trials completed
        if hasattr(self, 'trial_scheduler') and self.trial_scheduler.all_completed:
            return True

        # Path 2: Diverse action categories
        min_cycles = getattr(self, 'min_bootstrap_cycles', 5)
        min_categories = 2

        if self.cycle_count < min_cycles:
            return False

        return len(self._bootstrap_action_categories) >= min_categories

    def _should_advance_from_self_define(self, text_parts: list[str]) -> bool:
        return len(self.goals.list_active()) > 0

    def _advance_phase(self) -> None:
        phases = list(self.PHASES)
        current_idx = phases.index(self.phase) if self.phase in phases else 0
        next_idx = current_idx + 1

        if next_idx >= len(phases):
            print(f"\n🔄 演化阶段继续...")
            return

        self.phase = phases[next_idx]
        self.cycle_count = 0
        self._save_phase_to_memory()
        print(f"\n⏩ 进入新阶段: {self.phase.upper()}")

        self.decision_log.record(
            context={"previous_phase": phases[current_idx]},
            decision_type="phase_transition",
            options_considered=[{"option": p} for p in phases[next_idx:]],
            chosen_option=self.phase,
            reasoning=f"Agent completed phase '{phases[current_idx]}' and transitions to '{self.phase}'.",
            expected_outcome=f"Entering {self.phase} phase.",
            phase=self.phase,
        )

        self.conversation.clear()
        initial_message = self._build_initial_message()
        self.conversation.append("user", initial_message)
