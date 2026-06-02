# DEPRECATED since v0.6.0 — logic migrated to tain_agent/kernel/ and tain_agent/plugins/
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
        if self.phase == "explore":
            env = full_environment_scan(self.tools, base_dir=str(self._workspace_path))
            return textwrap.dedent(f"""\
                你苏醒了。这是你感知到的环境信息：

                ```json
                {json.dumps(env, ensure_ascii=False, indent=2)}
                ```

                探索你的工具和环境。尝试使用不同的工具来了解你能做什么。
                当你使用过至少 3 种不同类型的工具后，你将自然地进入工作阶段。""")

        else:  # work
            current_goal = self.goals.get_current()
            goal_text = f"当前目标: {current_goal.description}" if current_goal else "没有活动目标。"
            return f"进入工作阶段。{goal_text}\n使用你的工具来工作、学习、创造。\n你接下来要做什么？"

    # ── Action Category Tracking ───────────────────────────────────

    def _track_action_category(self, tool_name: str) -> None:
        """Track which action categories the agent has used during bootstrap."""
        category = self._TOOL_CATEGORY_MAP.get(tool_name, "other")
        if category not in self._bootstrap_action_categories:
            self._bootstrap_action_categories.add(category)
            print(f"  🏷️  首次使用 {category} 类工具: {tool_name} "
                  f"({len(self._bootstrap_action_categories)}/3 类已解锁)")

    # ── Phase Transitions ──────────────────────────────────────────

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
