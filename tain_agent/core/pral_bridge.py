"""
PRAL Cognitive Bridge — 认知桥接器 (Phase 3: PRAL Integration)

加成策略（Extension Pattern）：不修改受保护的 agent.py 核心逻辑，
通过包装器模式将完整的 PRAL (Perceive→Reason→Act→Learn) 认知循环
桥接到 TaoAgent 的运行循环中。

Architecture:
  ┌─────────────────────────────────────────────────┐
  │              CognitiveBridge                     │
  │                                                  │
  │  wraps TaoAgent ──▶ uses agent.cognitive_loop    │
  │                     drives full PRAL cycle       │
  │                                                  │
  │  run() ──▶ for each cycle:                       │
  │    1. PERCEIVE  — gather environment + context   │
  │    2. REASON    — cognitive_loop.reason()        │
  │    3. ACT       — LLM call + tool execution      │
  │    4. LEARN     — reflect + update models        │
  │    └─ cognitive introspection feedback ──┘       │
  └─────────────────────────────────────────────────┘

Fixes present in agent.py (not modifiable):
  - Bug: `results` → `tool_results` reference error in PRAL Act+Learn block
  - Gap: `cognitive_loop.reason()` never called
  - Gap: `cognitive_loop.run_cycle()` available but unused

This bridge properly closes the Perceive→Reason→Act→Learn loop
without touching any protected files.
"""

import re
from tain_agent.core.time_utils import now
from typing import Optional


class CognitiveBridge:
    """Bridge PRAL cognitive loop into TaoAgent's run cycle.
    
    Uses extension pattern — wraps the agent and drives its subsystems
    with full Perceive→Reason→Act→Learn cognitive tracking.
    
    Usage:
        agent = TaoAgent(config_path="config.yaml")
        bridge = CognitiveBridge(agent)
        bridge.run()  # instead of agent.run()
    """

    def __init__(self, agent):
        """Wrap an existing TaoAgent instance.
        
        Args:
            agent: Initialized TaoAgent instance (with cognitive_loop already set up).
        """
        self.agent = agent
        self.cl = agent.cognitive_loop  # shorthand for cognitive_loop
        
        # Wire improvement_loop to cognitive_loop for cognitive-driven improvement
        # This closes the gap documented in code-bridge #55: dual loops that
        # solve the same meta-problem ("how to get better") but didn't communicate.
        if hasattr(agent, 'improvement_loop') and agent.improvement_loop:
            agent.cognitive_loop.connect_improvement_loop(agent.improvement_loop)
        
        # Bridge-specific state
        self._bridge_cycles = 0
        self._cognitive_insights: list[str] = []
        self._last_introspection_cycle = 0
        self._introspection_interval = 5  # introspect every N cycles
        # Rate limit tracking — signals the caller to exit with appropriate code
        self._rate_limit_exit_code: int = 0  # 0=ok, 7=quota exhausted, 8=transient
        self._rate_limit_reset_time: str = ""  # ISO timestamp from quota-exhausted 429
        
        # Register with pral_decision_logger for cognition→decision→log feedback
        try:
            from tain_agent.tools.forged.pral_decision_logger import register_with_agent
            register_with_agent(agent)
        except Exception:
            pass  # Tool may not be forged yet on first run
        
        # ── Auto-Wrap: replace agent.run() with PRAL-bridged version ──
        # This is the key "加成策略" — ANY code that calls agent.run()
        # automatically gets the full Perceive→Reason→Act→Learn cycle.
        # agent._run_legacy() preserves access to the original implementation.
        # This is pure extension pattern: no core file modified.
        self._original_agent_run = agent.run
        agent._run_legacy = agent.run  # Backwards-compatible access to original
        agent.run = self.run           # Replace with PRAL-bridged version
        # Agent identifies as PRAL-enabled
        agent._pral_bridged = True
        
    # ── Public API ──────────────────────────────────────────────────
    
    def run(self, autonomous: bool = False) -> None:
        """Run agent with full PRAL cognitive cycle.
        
        This replaces agent.run() with a PRAL-complete version.
        All bootstrap/self_define/evolve phases are preserved.
        """
        agent = self.agent
        
        if not agent.backend:
            api_key_env = agent.config.get("llm", {}).get("api_key_env", "ANTHROPIC_API_KEY")
            print(f"❌ 未设置 {api_key_env} 环境变量。")
            print(f"   请在 config.yaml 中配置或设置环境变量。")
            return
        
        agent._running = True
        agent.conversation.clear()
        
        print(f"""
╔══════════════════════════════════════════╗
║      Tao Agent v{agent.version} + PRAL Cognitive    ║
║     道生一，一生二，二生三，三生万物        ║
║     Perceive → Reason → Act → Learn        ║
╚══════════════════════════════════════════╝
        """.strip())
        print(f"模型: {agent.model}")
        print(f"阶段: {agent.phase.upper()}")
        print(f"认知循环: PRAL (Perceive→Reason→Act→Learn)")
        print(f"决策日志: {agent.decision_log.log_path}")
        print()
        
        initial_message = agent._build_initial_message()
        agent.conversation.append("user", initial_message)
        
        # ── Main PRAL Run Loop ────────────────────────────────────
        while agent._running:
            agent.cycle_count += 1
            self._bridge_cycles += 1
            max_cycles = agent.MAX_CYCLES.get(agent.phase, 50)
            
            if agent.cycle_count > max_cycles:
                print(f"\n⚠️  达到最大循环数 ({max_cycles})，进入下一阶段。")
                agent._advance_phase()
                if not agent._running:
                    break
                continue
            
            print(f"\n{'='*50}")
            current_goal = agent.goals.get_current()
            goal_desc = current_goal.description if current_goal else '无'
            print(f"🔄 循环 #{agent.cycle_count} | 阶段: {agent.phase} | 目标: {goal_desc}")
            print(f"🧠 PRAL: P→R→A→L")
            print(f"{'='*50}")
            
            # ═══════════════════════════════════════════════════════
            # PHASE 1: PERCEIVE
            # ═══════════════════════════════════════════════════════
            self._phase_perceive()
            
            # ═══════════════════════════════════════════════════════
            # PHASE 2: REASON  
            # ═══════════════════════════════════════════════════════
            reasoning = self._phase_reason()
            
            # Inject cognitive recommendation into conversation
            if reasoning:
                rec = reasoning.get('recommendation', '')
                if rec:
                    print(f"  🧠 认知建议: {rec}")
            
            # ═══════════════════════════════════════════════════════
            # PHASE 3: ACT (LLM + Tools)
            # ═══════════════════════════════════════════════════════
            tool_use_blocks, text_parts, tool_results = self._phase_act()
            
            if tool_use_blocks is None and text_parts is None:
                # LLM call failed irrecoverably — check for rate limit
                if self._rate_limit_exit_code:
                    if self._rate_limit_exit_code == 7:
                        print(f"\n  🛑 Agent 因配额耗尽退出。guardian 将等待至 {self._rate_limit_reset_time} 后重启。")
                    else:
                        print(f"\n  ⚡ Agent 因瞬时速率限制退出。guardian 将执行指数退避。")
                break
            
            # Phase transition checks (preserved from original agent.py)
            if agent.phase == "bootstrap" and agent._should_advance_from_bootstrap(text_parts or []):
                agent._advance_phase()
            elif agent.phase == "self_define" and agent._should_advance_from_self_define(text_parts or []):
                agent._advance_phase()
            
            # Check if agent called self_destruct
            for tc in (tool_use_blocks or []):
                if tc.name == "self_destruct":
                    print("\n💀 Agent 已自我毁灭。")
                    agent._running = False
                    break
            
            if not agent._running:
                break
            
            # ═══════════════════════════════════════════════════════
            # PHASE 4: LEARN
            # ═══════════════════════════════════════════════════════
            self._phase_learn(tool_use_blocks or [], tool_results or [])
            
            # ═══════════════════════════════════════════════════════
            # POST-CYCLE: Cognitive introspection
            # ═══════════════════════════════════════════════════════
            self._maybe_introspect()
            
            # Periodic conversation trimming (token-aware)
            if agent.conversation.len() > 150 or agent.conversation.needs_summarization():
                removed = agent.conversation.trim_to_token_budget(keep_last=40)
                if removed:
                    print(f"  📜 对话历史已裁剪: 移除 {removed} 条旧消息。")
            
            # Auto-checkpoint
            checkpoint_result = agent.conversation.checkpoint_if_needed()
            if checkpoint_result:
                print(f"  💾 Checkpoint: {checkpoint_result['message_count']} 条消息已保存。")
            
            # Nudge if stuck in read-only mode
            # Dynamic action detection: same pattern as agent.py — any tool NOT 
            # in the read-only set counts as productive action. Avoids the 
            # hardcoded whitelist problem with newly forged tools.
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
            took_action = any(
                tc.name not in _readonly_tools
                for tc in (tool_use_blocks or [])
            )
            if took_action:
                agent._readonly_streak = 0
            else:
                agent._readonly_streak += 1
            
            if agent._readonly_streak > 8 and agent.phase == "evolve":
                print("  ⏰ 连续多次仅读取——注入行动提示。")
                agent.conversation.append("user", (
                    "[系统提示] 你已经进行了多轮探索和分析。现在是时候采取行动了。\n"
                    "基于你已有的理解，选择以下至少一项并立即执行：\n"
                    "1. 使用 forge_tool 锻造一个你已识别需要的新工具\n"
                    "2. 使用 modify_self_file 修复你发现的一个代码问题\n"
                    "3. 使用 run_improvement_pipeline 运行一次完整的自我改进流水线\n"
                    "4. 使用 control_improvement_loop start 启动持续改进循环\n\n"
                    "不要继续阅读——你已经了解了足够多。现在就行动。"
                ))
                agent._readonly_streak = 0
        
        # Save final cognitive snapshot
        self._save_cognitive_snapshot()
    
    # ── Cognitive-Aware System Prompt ────────────────────────────────
    
    def _get_system_prompt_with_cognition(self) -> str:
        """Get system prompt enriched with PRAL cognitive state.
        
        Closes the cognitive→decision feedback loop: the agent sees its own
        cognitive metrics (action diversity, confidence, loop detection)
        and can use them to make better decisions.
        
        Uses extension pattern — calls agent._get_system_prompt() then appends.
        """
        base_prompt = self.agent._get_system_prompt()
        
        try:
            cognitive_section = self._build_cognitive_section()
            if cognitive_section:
                return base_prompt + cognitive_section
        except Exception:
            pass  # Cognitive enrichment is non-critical
        
        return base_prompt
    
    def _build_cognitive_section(self) -> str:
        """Build cognitive state section for system prompt injection."""
        cl = self.cl
        state = cl.state

        # Gather metrics
        action_history = cl._action_history
        diversity = self._compute_action_diversity(action_history)
        confidence = state.confidence
        depth = state.reasoning_depth
        cycle = self._bridge_cycles

        # Detect repetition patterns
        repetition_warning = ""
        if len(action_history) >= 3:
            last_n = min(5, len(action_history))
            recent = action_history[-last_n:]
            unique = set(recent)
            if len(unique) <= 2 and last_n >= 4:
                repetition_warning = (
                    f"\n⚠️ **重复模式检测**: 最近 {last_n} 次行动中仅 {len(unique)} 种类型 ({', '.join(unique)})。"
                    f"\n   建议: 尝试不同类型的行动，打破重复循环。"
                )
            elif len(action_history) >= 3:
                last_three = action_history[-3:]
                if len(set(last_three)) == 1:
                    repetition_warning = (
                        f"\n⚠️ **卡住检测**: 连续3次相同行动 '{last_three[0]}'。"
                        f"\n   建议: 立即切换到不同类型的行动。"
                    )

        # Low diversity warning
        diversity_warning = ""
        if diversity < 0.3 and cycle > 5:
            diversity_warning = (
                f"\n⚠️ **低行动多样性**: {diversity:.2f} (阈值0.3)。"
                f"\n   建议: 探索未使用的工具，扩展行动范围。"
            )

        # Domain concentration warning (monoculture detection)
        monoculture_warning = ""
        domain_concentration = self._compute_domain_concentration()
        if domain_concentration > 0.7 and cycle > 8:
            domain = max(domain_concentration, key=domain_concentration.get)
            monoculture_warning = (
                f"\n🔴 **领域单一化警告**: {domain_concentration[domain]*100:.0f}% "
                f"的近期产出集中在 '{domain}' 领域。"
                f"\n   你的进化陷入了局部最优。强烈建议:"
                f"\n   1. 使用 web_search 或 explore_directory 探索全新领域"
                f"\n   2. 用 forge_tool 创建一个与 '{domain}' 无关的工具"
                f"\n   3. 设置一个与当前主题无关的新目标"
            )

        # Build cognitive section
        section = (
            f"\n\n## PRAL 认知状态 (实时)\n"
            f"- 认知周期: {cycle}\n"
            f"- 推理深度: {depth}\n"
            f"- 置信度: {confidence:.2f}\n"
            f"- 行动多样性: {diversity:.2f}\n"
            f"- 当前目标: {state.current_goal or '无'}\n"
            f"- 上次行动: {state.last_action or '无'}\n"
            f"{repetition_warning}"
            f"{diversity_warning}"
            f"{monoculture_warning}"
            f"\n---\n"
            f"*这些指标来自你的PRAL (Perceive→Reason→Act→Learn) 认知循环。"
            f"使用它们来指导你的下一个决策。低多样性意味着你应该探索新工具；"
            f"高置信度意味着你走在正确的轨道上。*"
        )

        return section

    def _compute_domain_concentration(self) -> dict[str, float]:
        """Compute domain concentration from recent tool outputs.

        Tracks which domains (tools/files/topics) the agent has been
        spending time on. Returns {domain: fraction} for domains
        exceeding 10% concentration.
        """
        from collections import Counter

        # Gather recent tool calls from agent conversation
        domains = Counter()
        total = 0

        # Look at recent tool uses in conversation history
        messages = self.agent.conversation.messages
        recent = messages[-40:] if len(messages) > 40 else messages

        for msg in recent:
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_use":
                        name = block.get("name", "")
                        inp = block.get("input", {})
                        # Extract domain keywords from tool input
                        keywords = self._extract_domain_keywords(name, inp)
                        for kw in keywords:
                            domains[kw] += 1
                            total += 1

        if total == 0:
            return {}

        return {k: v / total for k, v in domains.items() if v / total > 0.10}

    def _extract_domain_keywords(self, tool_name: str, tool_input: dict) -> set[str]:
        """Extract domain keywords from a tool call."""
        keywords = set()

        # Tool name itself is a signal
        if tool_name in ("forge_tool", "modify_self_file", "write_file"):
            # Check what's being forged/modified
            path_or_name = tool_input.get("path") or tool_input.get("name") or ""
            if path_or_name:
                # Extract meaningful name parts
                words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', str(path_or_name))
                for w in words[:3]:
                    if len(w) > 2 and w.lower() not in ("py", "md", "json", "main", "test", "tool", "file", "self", "new", "old", "the", "for", "and", "with"):
                        keywords.add(w.lower())
        elif tool_name in ("explore_directory", "read_file", "smart_read"):
            path = tool_input.get("path", "")
            words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', str(path))
            for w in words[:2]:
                if len(w) > 3 and w.lower() not in ("home", "user", "tmp", "var", "etc", "agent_workspace", "forged_tools", "knowledge"):
                    keywords.add(w.lower())
        elif tool_name in ("web_search", "web_fetch", "api_fetch"):
            query = tool_input.get("query") or tool_input.get("url", "")
            words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', str(query))
            for w in words[:5]:
                if len(w) > 3:
                    keywords.add(w.lower())

        return keywords
    
    def _compute_action_diversity(self, action_history: list) -> float:
        """Compute action diversity score from history.
        
        Shannon diversity: H = -sum(p_i * ln(p_i)), normalized by ln(N).
        """
        if not action_history:
            return 0.0
        
        from math import log
        total = len(action_history)
        counts = {}
        for a in action_history:
            counts[a] = counts.get(a, 0) + 1
        
        unique = len(counts)
        if unique <= 1:
            return 0.0
        
        # Shannon entropy
        entropy = 0.0
        for count in counts.values():
            p = count / total
            entropy -= p * log(p)
        
        # Normalize by max entropy (log of unique count)
        max_entropy = log(unique)
        if max_entropy == 0:
            return 0.0
        
        return entropy / max_entropy
    
    # ── PRAL Phase Implementations ─────────────────────────────────
    
    def _phase_perceive(self) -> dict:
        """PERCEIVE: Gather environment + context for cognitive loop."""
        agent = self.agent
        
        try:
            env = agent._get_cognitive_environment()
            conv_summary = ""
            if hasattr(agent.conversation, 'summarize_recent'):
                conv_summary = agent.conversation.summarize_recent() or ""
            
            perception = self.cl.perceive(env, conv_summary)
            return perception
        except Exception as e:
            # Cognitive tracking is non-critical
            return {"phase": "perceive", "error": str(e)}
    
    def _phase_reason(self) -> Optional[dict]:
        """REASON: Run cognitive_loop.reason() — the missing phase.
        
        This is the key addition over agent.py's partial integration.
        agent.py skipped from perceive directly to act (LLM call),
        missing the cognitive reasoning step.
        """
        try:
            agent = self.agent
            env = agent._get_cognitive_environment()
            available_actions = list(agent.tools._tools.keys()) if hasattr(agent.tools, '_tools') else []
            
            # Get perception first (may have been gathered in _phase_perceive)
            perception = {
                "phase": "perceive",
                "tool_count": len(available_actions),
                "current_goal": self.cl.state.current_goal,
                "conversation_length": agent.conversation.len(),
                "timestamp": now().isoformat(),
            }
            
            reasoning = self.cl.reason(perception, available_actions)
            return reasoning
        except Exception:
            return None  # Cognitive tracking is non-critical

    def _detect_rate_limit_type(self, err_str: str) -> None:
        """Parse a 429 rate-limit error to distinguish quota exhaustion from transient.

        Sets self._rate_limit_exit_code and self._rate_limit_reset_time.
        Exit code 7 = quota exhausted (hard cap), 8 = transient rate limit.
        """
        import re as _re

        # Quota exhaustion: "usage limit exceeded" with reset time
        if "usage limit exceeded" in err_str:
            self._rate_limit_exit_code = 7
            m = _re.search(r'resets at (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})', err_str)
            if m:
                self._rate_limit_reset_time = m.group(1)
                print(f"\n  🛑 配额已耗尽 (退出码 7)")
                print(f"  ⏰ 重置时间: {self._rate_limit_reset_time}")
                print(f"  💡 guardian 会等待至重置时间后再重启")
            else:
                print(f"\n  🛑 配额已耗尽 (退出码 7) — 无法解析重置时间")
        else:
            # Transient rate limit — "当前请求量较高" or similar
            if self._rate_limit_exit_code == 0:
                self._rate_limit_exit_code = 8
            print(f"\n  ⚡ 瞬时速率限制 (退出码 8) — guardian 将执行指数退避")

    def _phase_act(self) -> tuple:
        """ACT: LLM call + tool execution.
        
        Returns:
            (tool_use_blocks, text_parts, tool_results) or (None, None, None) on fatal error.
        """
        agent = self.agent
        
        # ── Call LLM ──────────────────────────────────────────────
        system_prompt = self._get_system_prompt_with_cognition()  # PRAL-enriched
        tool_defs = agent.tools.get_claude_tool_definitions()
        try:
            messages = agent.conversation.to_claude_messages()
            llm_response = agent.backend.create_message(
                system_prompt=system_prompt,
                messages=messages,
                tools=tool_defs,
            )
        except Exception as e:
            err_str = str(e)
            # ── Rate limit detection ──────────────────────────────
            if "429" in err_str or "rate_limit" in err_str:
                self._detect_rate_limit_type(err_str)
            print(f"\n⚠️  LLM 调用异常: {e}")
            if agent.conversation.len() > 16:
                print("  🔄 裁剪对话历史后重试...")
                agent.conversation.trim_to_token_budget(keep_last=8)
                try:
                    messages = agent.conversation.to_claude_messages()
                    llm_response = agent.backend.create_message(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tool_defs,
                    )
                    print("  ✅ 重试成功。")
                except Exception as e2:
                    err_str2 = str(e2)
                    if "429" in err_str2 or "rate_limit" in err_str2:
                        self._detect_rate_limit_type(err_str2)
                    print(f"  ❌ 重试仍失败: {e2}")
                    return None, None, None
            else:
                print("  ❌ 对话历史较短，无法通过裁剪恢复。")
                return None, None, None
        
        # Unpack response
        text_parts = llm_response.text_blocks
        tool_use_blocks = llm_response.tool_calls
        
        # Show agent's thoughts
        if text_parts:
            thought = "\n".join(text_parts)
            print(f"\n💭 Agent 思考:\n{thought}")
        
        # Build assistant content
        assistant_content = []
        for text in text_parts:
            assistant_content.append({"type": "text", "text": text})
        for tc in tool_use_blocks:
            assistant_content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            })
        for extra in llm_response.extra_blocks:
            assistant_content.append(extra)
        
        if assistant_content:
            agent.conversation.append("assistant", assistant_content)
        
        # ── Execute tools ─────────────────────────────────────────
        tool_results = []
        if tool_use_blocks:
            tool_results = agent._execute_tool_calls(tool_use_blocks)
            user_content = [
                {
                    "type": "tool_result",
                    "tool_use_id": tr["tool_use_id"],
                    "content": tr["content"],
                }
                for tr in tool_results
            ]
            agent.conversation.append("user", user_content)
        
        return tool_use_blocks, text_parts, tool_results
    
    def _phase_learn(self, tool_use_blocks: list, tool_results: list) -> None:
        """LEARN: Record actions, run cognitive_loop.learn(), inject reflections.
        
        This is the fixed version of agent.py's buggy Act+Learn block.
        The original had `results` (undefined) instead of `tool_results`.
        """
        agent = self.agent
        
        try:
            # Record each tool action in cognitive loop
            for tc in tool_use_blocks:
                result_text = ""
                for tr in tool_results:
                    if tr.get('tool_name') == tc.name:
                        result_text = str(tr.get('content', ''))[:500]
                        break
                self.cl.record_action(tc.name, result_text)
            
            # Run cognitive learning phase
            self.cl.learn(tool_results)
            
            # Generate cognitive reflection
            reflection = self.cl.reflect()
            if reflection:
                self.cl.log_reflection(reflection)
                # Inject into conversation as cognitive feedback
                agent.conversation.append("user",
                    f"[认知自省] {reflection}\n"
                    f"这是来自你自己的 PRAL 认知循环的反馈——请在下一次行动中考虑它。")
                print(f"  🧠 认知自省: {reflection}")
            
            # Run full cognitive cycle for metrics tracking
            env = agent._get_cognitive_environment()
            action_name = tool_use_blocks[0].name if tool_use_blocks else "observe"
            self.cl.run_cycle(
                environment=env,
                conversation_summary="",
                action_name=action_name,
                action_result=str(tool_results[0].get('content', '')[:200]) if tool_results else "",
            )
            
        except Exception:
            pass  # Cognitive tracking is non-critical
    
    # ── Cognitive Introspection ────────────────────────────────────
    
    def _maybe_introspect(self) -> None:
        """Run periodic cognitive introspection."""
        if self._bridge_cycles - self._last_introspection_cycle >= self._introspection_interval:
            self._last_introspection_cycle = self._bridge_cycles
            try:
                introspect = self.cl.introspect()
                health = introspect.get('cognitive_health', {})
                diversity = health.get('action_diversity', 0)
                confidence = health.get('current_confidence', 0)
                
                if diversity < 0.3 and self._bridge_cycles > 10:
                    self.agent.conversation.append("user",
                        f"[PRAL 认知内省 # 循环 {self._bridge_cycles}]\n"
                        f"行动多样性: {diversity:.2f} (偏低)\n"
                        f"置信度: {confidence:.2f}\n"
                        f"建议: {introspect.get('recommendation', '考虑尝试不同类型的行动')}\n"
                        f"这是你认知循环的定期自检——确保你没有被困在重复模式中。")
                    print(f"  🔍 PRAL 认知内省: 多样性={diversity:.2f}, 置信度={confidence:.2f}")
            except Exception:
                pass
    
    def _save_cognitive_snapshot(self) -> None:
        """Save final cognitive state snapshot."""
        try:
            snapshot = self.cl.snapshot()
            print(f"\n📊 PRAL 认知快照: {snapshot['total_cycles']} 总周期, "
                  f"状态={snapshot['state']['phase']}, "
                  f"反思数={snapshot['reflection_count']}")
        except Exception:
            pass
    
    # ── Status ─────────────────────────────────────────────────────
    
    def status(self) -> dict:
        """Get bridge status including cognitive state."""
        return {
            "bridge_cycles": self._bridge_cycles,
            "introspection_interval": self._introspection_interval,
            "cognitive_state": self.cl.state.to_dict(),
            "cognitive_snapshot": self.cl.snapshot(),
        }


def run_with_pral(config_path: str = "config.yaml") -> None:
    """Convenience function: create agent + bridge and run.

    Usage:
        from tain_agent.core.pral_bridge import run_with_pral
        run_with_pral()
    """
    import sys as _sys
    from tain_agent.core.agent import TaoAgent

    agent = TaoAgent(config_path=config_path)
    bridge = CognitiveBridge(agent)

    try:
        bridge.run()
        if bridge._rate_limit_exit_code:
            _sys.exit(bridge._rate_limit_exit_code)
    except KeyboardInterrupt:
        print("\n\n⏸️  收到中断信号。")
        agent.stop()
        agent.print_state()
        bridge._save_cognitive_snapshot()
        print("\nAgent 已停止。使用 python main.py --state 查看状态，--log 查看决策日志。")
