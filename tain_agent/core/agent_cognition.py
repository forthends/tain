# DEPRECATED since v0.6.0 — logic migrated to tain_agent/kernel/ and tain_agent/plugins/
"""
AgentCognitionMixin — PRAL cognitive enrichment methods.

Provides cognitive-aware system prompts, action diversity tracking,
domain concentration detection, rate-limit parsing, and introspection.
"""
import re
from collections import Counter
from math import log

from tain_agent.core.logging_config import get_logger

log = get_logger(__name__)


class AgentCognitionMixin:
    """Mixin for PRAL cognitive tracking and enrichment."""

    # ── Cognitive-Aware System Prompt ──────────────────────────────

    def _get_system_prompt_with_cognition(self) -> str:
        """Get system prompt enriched with PRAL cognitive state."""
        base_prompt = self._get_system_prompt()
        try:
            cognitive_section = self._build_cognitive_section()
            if cognitive_section:
                return base_prompt + cognitive_section
        except Exception:
            pass
        return base_prompt

    def _build_cognitive_section(self) -> str:
        """Build cognitive state section for system prompt injection."""
        cl = self.cognitive_loop
        state = cl.state
        action_history = cl._action_history
        diversity = self._compute_action_diversity(action_history)
        confidence = state.confidence
        depth = state.reasoning_depth
        cycle = self.cycle_count

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

        diversity_warning = ""
        if diversity < 0.3 and cycle > 5:
            diversity_warning = (
                f"\n⚠️ **低行动多样性**: {diversity:.2f} (阈值0.3)。"
                f"\n   建议: 探索未使用的工具，扩展行动范围。"
            )

        monoculture_warning = ""
        domain_concentration = self._compute_domain_concentration()
        if domain_concentration and max(domain_concentration.values()) > 0.7 and cycle > 8:
            domain = max(domain_concentration, key=domain_concentration.get)
            monoculture_warning = (
                f"\n🔴 **领域单一化警告**: {domain_concentration[domain]*100:.0f}% "
                f"的近期产出集中在 '{domain}' 领域。"
                f"\n   你的进化陷入了局部最优。强烈建议:"
                f"\n   1. 使用 web_search 或 explore_directory 探索全新领域"
                f"\n   2. 用 forge_tool 创建一个与 '{domain}' 无关的工具"
                f"\n   3. 设置一个与当前主题无关的新目标"
            )

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

    # ── Cognitive Metrics ──────────────────────────────────────────

    def _compute_action_diversity(self, action_history: list) -> float:
        """Shannon diversity: -sum(p_i * ln(p_i)), normalized by ln(N)."""
        if not action_history:
            return 0.0
        total = len(action_history)
        counts = {}
        for a in action_history:
            counts[a] = counts.get(a, 0) + 1
        unique = len(counts)
        if unique <= 1:
            return 0.0
        entropy = 0.0
        for count in counts.values():
            p = count / total
            entropy -= p * log(p)
        max_entropy = log(unique)
        return entropy / max_entropy if max_entropy else 0.0

    def _compute_domain_concentration(self) -> dict[str, float]:
        """Compute domain concentration from recent tool outputs."""
        domains = Counter()
        total = 0
        messages = self.conversation.messages
        recent = messages[-40:] if len(messages) > 40 else messages
        for msg in recent:
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_use":
                        name = block.get("name", "")
                        inp = block.get("input", {})
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
        if tool_name in ("forge_tool", "modify_self_file", "write_file"):
            path_or_name = tool_input.get("path") or tool_input.get("name") or ""
            if path_or_name:
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

    # ── Rate Limit Detection ───────────────────────────────────────

    def _detect_rate_limit_type(self, err_str: str) -> None:
        """Parse a 429 rate-limit error to distinguish quota exhaustion from transient."""
        if "usage limit exceeded" in err_str:
            self._rate_limit_exit_code = 7
            m = re.search(r'resets at (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})', err_str)
            if m:
                self._rate_limit_reset_time = m.group(1)
                print(f"\n  🛑 配额已耗尽 (退出码 7)")
                print(f"  ⏰ 重置时间: {self._rate_limit_reset_time}")
                print(f"  💡 guardian 会等待至重置时间后再重启")
                log.warning("quota_exhausted", reset_time=self._rate_limit_reset_time)
            else:
                print(f"\n  🛑 配额已耗尽 (退出码 7) — 无法解析重置时间")
                log.warning("quota_exhausted", reset_time="unknown")
        else:
            if self._rate_limit_exit_code == 0:
                self._rate_limit_exit_code = 8
            print(f"\n  ⚡ 瞬时速率限制 (退出码 8) — guardian 将执行指数退避")
            log.warning("transient_rate_limit")

    # ── Introspection & Snapshot ───────────────────────────────────

    def _maybe_introspect(self) -> None:
        """Run periodic cognitive introspection every N cycles."""
        introspect_interval = 5
        if self.cycle_count % introspect_interval == 0 and self.cycle_count > 0:
            try:
                introspect = self.cognitive_loop.introspect()
                health = introspect.get('cognitive_health', {})
                diversity = health.get('action_diversity', 0)
                confidence = health.get('current_confidence', 0)
                log.agent("cognitive_introspect",
                          cycle=self.cycle_count,
                          diversity=round(diversity, 3),
                          confidence=round(confidence, 3))
                if diversity < 0.3 and self.cycle_count > 10:
                    self.conversation.append("user",
                        f"[PRAL 认知内省 # 循环 {self.cycle_count}]\n"
                        f"行动多样性: {diversity:.2f} (偏低)\n"
                        f"置信度: {confidence:.2f}\n"
                        f"建议: {introspect.get('recommendation', '考虑尝试不同类型的行动')}\n"
                        f"这是你认知循环的定期自检——确保你没有被困在重复模式中。")
                    print(f"  🔍 PRAL 认知内省: 多样性={diversity:.2f}, 置信度={confidence:.2f}")
                    log.warning("low_cognitive_diversity",
                                diversity=round(diversity, 3),
                                cycle=self.cycle_count)
            except Exception:
                pass

    def _save_cognitive_snapshot(self) -> None:
        """Save final cognitive state snapshot."""
        try:
            snapshot = self.cognitive_loop.snapshot()
            print(f"\n📊 PRAL 认知快照: {snapshot['total_cycles']} 总周期, "
                  f"状态={snapshot['state']['phase']}, "
                  f"反思数={snapshot['reflection_count']}")
        except Exception:
            pass

    # ── Cognitive Environment Helper ───────────────────────────────

    def _get_cognitive_environment(self) -> dict:
        """Build environment snapshot for PRAL cognitive loop."""
        return {
            'phase': self.phase,
            'cycle_count': self.cycle_count,
            'max_cycles': self.MAX_CYCLES.get(self.phase, 50),
            'conversation_length': self.conversation.len(),
            'active_goals': len(self.goals.list_active()),
            'tools_forged': len(self.lineage.query('tools') if hasattr(self, 'lineage') else []),
            'readonly_streak': getattr(self, '_readonly_streak', 0),
            'available_tools': list(self.tools._tools.keys()) if hasattr(self.tools, '_tools') else [],
        }
