"""
AgentRunner — the main run loop extracted from TaoAgent.

Operates on an AgentContext, breaking the monolithic run() method
into clean, testable sub-methods.
"""

import os
import time
from typing import Optional

from tain_agent.core.agent_context import AgentContext
from tain_agent.core.cognitive_loop import CognitivePhase
from tain_agent.core.environment import print_diversity_profile


class AgentRunner:
    """Executes the agent's main run loop on an AgentContext."""

    PHASES = ("explore", "work")
    MAX_CYCLES = {"explore": 10, "work": 999999}

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    def run(self, autonomous: bool = False) -> int:
        """Start the agent. This is the moment of awakening."""
        ctx = self.ctx

        if not ctx.backend:
            api_key_env = ctx.config.get("llm", {}).get("api_key_env", "MINIMAX_API_KEY")
            print(f"无法设置 {api_key_env} 环境变量。")
            return 0

        ctx._running = True
        ctx.conversation.clear()

        ctx.factory.mark_running(ctx.agent_name, os.getpid())

        print(f"""
╔══════════════════════════════════════════╗
║     Tain Agent Framework v{ctx.framework_version}     ║
║     Agent: {ctx.agent_name:<29s} ║
║     道生一，一生二，二生三，三生万物      ║
╚══════════════════════════════════════════╝
        """.strip())
        print(f"Agent: {ctx.agent_name}")
        print(f"模型: {ctx.backend.model}")
        print(f"阶段: {ctx.phase.upper()}")
        print_diversity_profile(ctx.diversity)
        print(f"保护路径: {ctx.protected_paths}")
        print(f"决策日志: {ctx.decision_log.log_path}")
        print()

        initial_message = self._build_initial_message()
        ctx.conversation.append("user", initial_message)

        while ctx._running:
            ctx.cycle_count += 1
            max_cycles = self.MAX_CYCLES.get(ctx.phase, 50)

            if ctx.cycle_count > max_cycles:
                print(f"\n达到最大循环数 ({max_cycles})，进入下一阶段。")
                self._advance_phase()
                if not ctx._running:
                    break
                continue

            print(f"\n{'='*50}")
            current_goal = ctx.goals.get_current()
            goal_desc = current_goal.description if current_goal else '无'
            print(f"循环 #{ctx.cycle_count} | 阶段: {ctx.phase} | 目标: {goal_desc}")
            print(f"{'='*50}")

            # ── PRAL: Perceive + Reason ─────────────────────────────────
            env = self._get_cognitive_environment()
            try:
                ctx.cognitive_loop.perceive(env, "")
                ctx.cognitive_loop.state.phase = CognitivePhase.REASON
                available_actions = list(ctx.tools._tools.keys()) if hasattr(ctx.tools, '_tools') else []
                reasoning = ctx.cognitive_loop.reason(env, available_actions)
                if reasoning and reasoning.get('recommendation'):
                    print(f"  认知建议: {reasoning['recommendation']}")
            except Exception:
                pass

            # ── LLM Call ────────────────────────────────────────────────
            llm_response = self._call_llm()
            if llm_response is None:
                continue

            text_parts = llm_response.text_blocks
            tool_use_blocks = llm_response.tool_calls

            if text_parts:
                thought = "\n".join(text_parts)
                print(f"\nAgent 思考:\n{thought}")

            # ── Build assistant content ─────────────────────────────────
            assistant_content = []
            for text in text_parts:
                assistant_content.append({"type": "text", "text": text})
            for tc in tool_use_blocks:
                assistant_content.append({
                    "type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input,
                })
            for extra in llm_response.extra_blocks:
                assistant_content.append(extra)
            if assistant_content:
                ctx.conversation.append("assistant", assistant_content)

            # ── Execute tools ───────────────────────────────────────────
            if tool_use_blocks:
                self._track_actions(tool_use_blocks, text_parts)
                tool_results = self._execute_tools(tool_use_blocks)
                user_content = [
                    {"type": "tool_result", "tool_use_id": tr["tool_use_id"], "content": tr["content"]}
                    for tr in tool_results
                ]
                ctx.conversation.append("user", user_content)

            # ── Phase transition ────────────────────────────────────────
            if ctx.phase == "explore" and len(ctx._bootstrap_action_categories) >= 3:
                self._advance_phase()

            # ── Self-destruct check ─────────────────────────────────────
            for tc in tool_use_blocks:
                if tc.name == "self_destruct":
                    print("\nAgent 已自我毁灭。")
                    ctx._running = False
                    break

            # ── PRAL: Act + Learn ───────────────────────────────────────
            try:
                for tc in tool_use_blocks:
                    result_text = ""
                    for r in tool_results:
                        if r.get('tool_name') == tc.name:
                            result_text = str(r.get('content', ''))[:500]
                            break
                    ctx.cognitive_loop.record_action(tc.name, result_text)
                ctx.cognitive_loop.learn(tool_results)
                ctx.cognitive_loop.run_cycle(
                    environment=env,
                    conversation_summary="",
                    action_name=tool_use_blocks[0].name if tool_use_blocks else "observe",
                    action_result=str(tool_results[0].get('content', '')[:200]) if tool_results else "",
                )
                reflection = ctx.cognitive_loop.reflect()
                if reflection:
                    ctx.cognitive_loop.log_reflection(reflection)
                    ctx.conversation.append("user",
                        f"[认知自省] {reflection}\n这是来自你自己的认知循环的反馈——请在下一次行动中考虑它。")
            except Exception:
                pass

            # ── Maintenance ─────────────────────────────────────────────
            self._trim_and_checkpoint()
            self._check_readonly_streak(text_parts, tool_use_blocks)
            self._maybe_inject_prompts()

        self._save_cognitive_snapshot()
        return ctx._rate_limit_exit_code

    # ── Sub-methods ────────────────────────────────────────────────────

    def _call_llm(self):
        ctx = self.ctx
        try:
            system_prompt = self._get_system_prompt()
            messages = ctx.conversation.to_claude_messages()
            tool_defs = ctx.tools.get_claude_tool_definitions()
            return ctx.backend.create_message(
                system_prompt=system_prompt,
                messages=messages,
                tools=tool_defs,
            )
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str:
                self._detect_rate_limit_type(err_str)
                if ctx._rate_limit_exit_code:
                    return None
            print(f"\nLLM 调用异常: {e}")
            if ctx.conversation.len() > 16:
                print("  裁剪对话历史后重试...")
                ctx.conversation.trim_to_token_budget(keep_last=8)
                try:
                    messages = ctx.conversation.to_claude_messages()
                    return ctx.backend.create_message(
                        system_prompt=self._get_system_prompt(),
                        messages=messages,
                        tools=ctx.tools.get_claude_tool_definitions(),
                    )
                except Exception as e2:
                    err_str2 = str(e2)
                    if "429" in err_str2 or "rate_limit" in err_str2:
                        self._detect_rate_limit_type(err_str2)
                        if ctx._rate_limit_exit_code:
                            return None
                    print(f"  重试仍失败: {e2}")
                    time.sleep(3)
                    return None
            else:
                print("  短暂等待后重试下一循环...")
                time.sleep(2)
                return None

    def _track_actions(self, tool_use_blocks, text_parts):
        ctx = self.ctx
        from tain_agent.core.agent_phase import AgentPhaseMixin
        tool_category_map = AgentPhaseMixin._TOOL_CATEGORY_MAP

        if ctx.phase == "explore":
            for tc in tool_use_blocks:
                category = tool_category_map.get(tc.name, "other")
                if category not in ctx._bootstrap_action_categories:
                    ctx._bootstrap_action_categories.add(category)
                    print(f"  首次使用 {category} 类工具: {tc.name} "
                          f"({len(ctx._bootstrap_action_categories)}/3 类已解锁)")

        if ctx.drive_system:
            took_productive = False
            for tc in tool_use_blocks:
                cat = tool_category_map.get(tc.name, "observation")
                if cat in ("creation", "reflection"):
                    ctx.drive_system.record_action(tc.name)
                    took_productive = True
            if not took_productive and tool_use_blocks:
                ctx.drive_system.record_idle_cycle()

        if ctx.personality and tool_use_blocks:
            tool_names = [tc.name for tc in tool_use_blocks]
            ctx.personality.auto_observe(tool_names, text_parts)

    def _execute_tools(self, tool_use_blocks):
        ctx = self.ctx
        import time as _time
        tool_results = []
        for tc in tool_use_blocks:
            t0 = _time.monotonic()
            raw = ctx.tools.call(tc.name, **tc.input)
            elapsed = (_time.monotonic() - t0) * 1000
            is_error = not raw.get("success", False)
            content = raw.get("result", raw.get("error", str(raw)))
            if isinstance(content, (dict, list)):
                import json as _json
                content = _json.dumps(content, ensure_ascii=False)
            tool_results.append({
                "tool_name": tc.name,
                "tool_use_id": tc.id,
                "content": str(content),
                "is_error": is_error,
                "elapsed_ms": round(elapsed, 2),
            })
            ctx.decision_log.record(
                context={"tool": tc.name, "input": tc.input},
                decision_type="tool_call",
                options_considered=[{"option": tc.name, "input": tc.input}],
                chosen_option=tc.name,
                reasoning=f"执行工具 {tc.name}",
                expected_outcome=f"工具 {tc.name} 返回结果",
                actual_outcome=str(content)[:500],
                phase=ctx.phase,
            )
        return tool_results

    def _get_cognitive_environment(self) -> dict:
        ctx = self.ctx
        return {
            "tools_count": ctx.tools.count() if ctx.tools else 0,
            "phase": ctx.phase,
            "cycle": ctx.cycle_count,
        }

    def _get_system_prompt(self) -> str:
        ctx = self.ctx
        from tain_agent.core.bootstrap import (
            BOOTSTRAP_SYSTEM_PROMPT, SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT,
            EVOLVE_SYSTEM_PROMPT,
        )
        is_specified = ctx.evolution_mode == "specified"

        if ctx.phase == "explore":
            template = SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT if is_specified else BOOTSTRAP_SYSTEM_PROMPT
        else:
            template = EVOLVE_SYSTEM_PROMPT

        base = template.format(
            agent_name=ctx.agent_name,
            role=ctx.role,
            role_description=ctx.role_description,
        )

        if ctx.personality:
            base += "\n\n" + ctx.personality.get_context_for_prompt()

        if ctx.drive_system:
            weights = ctx.drive_system.get_action_weights()
            base += (
                "\n\n## 内驱力状态\n"
                f"- 观察探索 (好奇): {weights.get('observation', 0):.2f}\n"
                f"- 优化精进 (精通): {weights.get('optimization', 0):.2f}\n"
                f"- 创造构建 (创造): {weights.get('creation', 0):.2f}\n"
                f"- 维护整理 (守成): {weights.get('maintenance', 0):.2f}\n"
                "这些权重反映了你当前的内驱力状态。"
            )

        # Cognitive enrichment
        try:
            cognitive = ctx.cognitive_loop
            if cognitive and hasattr(cognitive, '_action_history'):
                history = cognitive._action_history
                if history:
                    last_3 = history[-3:]
                    unique = len(set(last_3))
                    if unique == 1 and len(last_3) >= 3:
                        base += f"\n\n[认知提示] 你最近重复使用了 '{last_3[0]}'。考虑尝试不同的行动。"
        except Exception:
            pass

        tools_summary = ctx.tools.list_tools()
        tool_lines = ["\n\n## 当前可用工具"]
        for name, info in tools_summary.items():
            tool_lines.append(f"- **{name}**: {info['description']}")
        return base + "\n".join(tool_lines)

    def _build_initial_message(self) -> str:
        ctx = self.ctx
        import json as _json, textwrap as _textwrap
        if ctx.phase == "explore":
            env = {
                "tools_available": ctx.tools.count(),
                "workspace": str(ctx._workspace_path) if ctx._workspace_path else "",
            }
            return _textwrap.dedent(f"""\
                你苏醒了。这是你感知到的环境信息：

                ```json
                {_json.dumps(env, ensure_ascii=False, indent=2)}
                ```

                探索你的工具和环境。尝试使用不同的工具来了解你能做什么。
                当你使用过至少 3 种不同类型的工具后，你将自然地进入工作阶段。""")
        else:
            current_goal = ctx.goals.get_current()
            goal_text = f"当前目标: {current_goal.description}" if current_goal else "没有活动目标。"
            return f"进入工作阶段。{goal_text}\n使用你的工具来工作、学习、创造。\n你接下来要做什么？"

    def _advance_phase(self) -> None:
        ctx = self.ctx
        phases = list(self.PHASES)
        current_idx = phases.index(ctx.phase) if ctx.phase in phases else 0
        next_idx = current_idx + 1
        if next_idx >= len(phases):
            return
        ctx.phase = phases[next_idx]
        ctx.cycle_count = 0
        print(f"\n进入新阶段: {ctx.phase.upper()}")
        ctx.decision_log.record(
            context={"previous_phase": phases[current_idx]},
            decision_type="phase_transition",
            options_considered=[{"option": p} for p in phases[next_idx:]],
            chosen_option=ctx.phase,
            reasoning=f"Agent completed phase '{phases[current_idx]}'.",
            expected_outcome=f"Entering {ctx.phase} phase.",
            phase=ctx.phase,
        )
        ctx.conversation.clear()

    def _detect_rate_limit_type(self, err_str: str) -> None:
        ctx = self.ctx
        if "exceeded your current quota" in err_str or "quota" in err_str.lower():
            ctx._rate_limit_exit_code = 6
            print(f"\nAPI 配额已用尽。退出循环。")
        elif "billing" in err_str.lower() or "payment" in err_str.lower():
            ctx._rate_limit_exit_code = 5
            print(f"\nAPI 计费问题。退出循环。")

    def _trim_and_checkpoint(self) -> None:
        ctx = self.ctx
        if ctx.conversation.len() > 150:
            removed = ctx.conversation.trim_to_token_budget(keep_last=40)
            if removed:
                print(f"  对话历史已裁剪: 移除 {removed} 条旧消息。")
        checkpoint = ctx.conversation.checkpoint_if_needed()
        if checkpoint:
            print(f"  Checkpoint: {checkpoint['message_count']} 条消息已保存。")

    def _check_readonly_streak(self, text_parts, tool_use_blocks) -> None:
        ctx = self.ctx
        _readonly_tools = {
            "read_file", "smart_read", "grep_code", "web_search", "web_fetch",
            "observe_environment", "explore_directory", "get_current_time",
        }
        _reflective_tools = {
            "personality_introspect", "personality_update",
            "record_decision", "set_goal", "complete_goal",
        }
        took_action = any(
            tc.name not in _readonly_tools and tc.name not in _reflective_tools
            for tc in tool_use_blocks
        )
        had_reflection = any(tc.name in _reflective_tools for tc in tool_use_blocks)

        if took_action:
            ctx._readonly_streak = 0
        elif had_reflection:
            ctx._readonly_streak = max(0, ctx._readonly_streak - 2)
        else:
            ctx._readonly_streak += 1

        if ctx.phase == "work":
            if ctx._readonly_streak == 5:
                ctx.conversation.append("user", (
                    "[系统提示] 你已经进行了多轮静观。"
                    "请反思：你近期的静观是否产生了新的洞察？"
                ))
            elif ctx._readonly_streak > 8:
                ctx.conversation.append("user", (
                    "[系统提示] 你已经静观了很长时间。"
                    "如果有了新的方向感，现在也许是行动的时候了。"
                ))
                ctx._readonly_streak = 0

    def _maybe_inject_prompts(self) -> None:
        ctx = self.ctx
        if ctx.cycle_count % 8 == 0 and ctx.drive_system:
            prompt = ctx.drive_system.get_exploration_prompt()
            if prompt:
                ctx.conversation.append("user", prompt)

    def _save_cognitive_snapshot(self) -> None:
        pass  # Placeholder for future implementation

    def stop(self) -> None:
        ctx = self.ctx
        if ctx.conversation:
            ctx.conversation.checkpoint()
        if ctx.decision_log:
            ctx.decision_log.flush()
        if ctx.memory:
            ctx.memory.long_term.flush()
        ctx.factory.mark_stopped(ctx.agent_name)
        ctx._running = False
        print(f"\nAgent '{ctx.agent_name}' 已停止。")
