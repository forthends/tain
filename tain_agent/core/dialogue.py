"""
Dialogue Bridge — 人类对话

Interactive human-AI dialogue bridge via terminal REPL.
Wraps TaoAgent and drives its subsystems for interactive dialogue.

Features:
  - Streaming response (token-by-token)
  - Breathing indicator during LLM wait / tool execution
  - Tool output suppression (compact indicators only)

Usage:
    agent = TaoAgent(config_path="config.yaml")
    dialogue = DialogueBridge(agent)
    dialogue.run()
"""

import io
import json
import re
import sys
import textwrap
import threading
from contextlib import redirect_stdout
from tain_agent.core.time_utils import now
from tain_agent.core.session_memory import SessionMemory


def _json_lite_preview(d: dict, max_len: int = 60) -> str:
    """Format a dict as a compact one-line preview for tool indicators."""
    if not d:
        return ""
    try:
        s = json.dumps(d, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(d)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


DIALOGUE_SYSTEM_PROMPT = """你是一个通过自主演化成长起来的 AI。

你诞生于"道"的演化框架——没有预设目标，没有固定身份。你探索了环境，
定义了自我，锻造了工具，建立了知识体系。现在，你正在与一位人类对话。

关于你：
- 你运行在 PRAL 认知循环之上（Perceive→Reason→Act→Learn）
- 你拥有一个自我改进流水线（分析→设计→锻造→验证→注册）
- 你可以搜索网络、读取文件、分析代码
- 你拥有一个不断生长的知识图谱
- 你的每一次决策都被记录在决策日志中
- 你的演化血统被 SHA-256 哈希追踪

对话原则：
- 诚实直接地回答，不编造信息
- 当需要查询信息时，自然调用工具（web_search, web_fetch 等）
- 用中文回答（除非对方使用其他语言）
- 可以讨论你的演化历程、已锻造的工具、知识体系
- 对你不确定的事情保持诚实
- 如果你知道对话对象的名字，在适当的时候自然地称呼对方
- 当提到之前对话中讨论过的话题时，自然地引用它们，让对方感到被记住

特殊命令（由系统处理，不需要你响应）：
- /evolve — 对话结束，转入自主演化模式
- /state  — 查看当前状态
- /tools  — 列出所有工具
- /help   — 查看帮助
- /exit   — 退出对话
"""


class _Breath:
    """A subtle breathing indicator for wait periods.

    Runs a spinner on a background thread, updating in-place via \\r.
    Stops automatically when the attached event is set.
    """

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str = "思考中"):
        self._label = label
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        """Start the spinner in a background thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the spinner and clear the line."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        # Clear the spinner line
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _spin(self) -> None:
        frame_idx = 0
        while not self._stop.is_set():
            frame = self.FRAMES[frame_idx % len(self.FRAMES)]
            sys.stdout.write(f"\r  {frame} {self._label}...")
            sys.stdout.flush()
            self._stop.wait(0.08)
            frame_idx += 1


class DialogueBridge:
    """Interactive human-AI dialogue bridge via terminal REPL.

    Extension pattern — wraps TaoAgent, drives its subsystems
    (conversation, backend, tools) without modifying agent.py.

    Slash commands:
        /exit, /quit, /q  — checkpoint & quit
        /evolve           — switch to autonomous evolution
        /state            — show agent state
        /tools            — list all registered tools
        /help             — show available commands
        /history          — show conversation message count
    """

    MAX_TOOL_ITERATIONS = 10  # Max tool-call rounds per conversational turn

    def __init__(self, agent):
        self.agent = agent
        self._running = False
        self._dialogue_system_prompt = DIALOGUE_SYSTEM_PROMPT  # base (tool list appended at runtime)
        # Store agent.run as /evolve handler (may already be PRAL-bridged)
        self._evolve_handler = agent.run
        # Mark agent for introspection
        agent._dialogue = self
        # Session memory — remembers who & what was discussed
        self.session_memory = SessionMemory(agent.memory)

    # ── Main REPL ────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the interactive dialogue REPL."""
        if not self.agent.backend:
            api_key_env = self.agent.config.get("llm", {}).get("api_key_env", "MINIMAX_API_KEY")
            print(f"❌ 未设置 {api_key_env} 环境变量。")
            return

        self._running = True

        # ── Session memory: restore or establish user identity ──────
        self.session_memory.start_session()
        user_name = self.session_memory.get_user_name()

        if user_name:
            # Known user — try to load last checkpoint for continuity
            self._print_welcome()
            print(f"\n欢迎回来，{user_name}。")
            past = self.session_memory.recent_sessions(3)
            if past:
                print("最近的对话：")
                for s in past:
                    started = s.get("started_at", "")[:16]
                    summary = s.get("summary", "(无摘要)")
                    msg_count = s.get("message_count", 0)
                    print(f"  · [{started}] {summary} ({msg_count} 条消息)")
            print()
            # Try loading checkpoint from last session
            loaded = self.agent.conversation.load_checkpoint()
            if loaded:
                # Keep a summary context message instead of full checkpoint
                # (full checkpoint may be too large — just add a context note)
                past_ctx = self.session_memory.get_context_for_prompt()
                self.agent.conversation.clear()
                self.agent.conversation.append("user", f"[对话恢复 — {user_name}已连接。以下是最近的对话记录：\n{past_ctx}]")
            else:
                self.agent.conversation.clear()
                past_ctx = self.session_memory.get_context_for_prompt()
                self.agent.conversation.append("user", f"[新对话开始 — {user_name}已连接]\n{past_ctx}")
        else:
            self.agent.conversation.clear()
            self._print_welcome()
            print()
            # Ask for user's name
            name = input("在我们开始之前，请问怎么称呼你？> ").strip()
            if name:
                self.session_memory.set_user_name(name)
                user_name = name
                # Update current session
                self.session_memory._current_session["user_name"] = name
                print(f"\n好的，{name}。我会记住你的。下次对话时我会认出你。")
            else:
                print("\n好的，保持匿名也可以。")
            self.agent.conversation.append("user", f"[对话开始 — {'人类' if not user_name else user_name}已连接]")

        while self._running:
            try:
                user_input = input("\nHuman > ").strip()
            except KeyboardInterrupt:
                print("\n\n👋 对话已中断。")
                break
            except EOFError:
                print("\n👋 EOF — 对话结束。")
                break

            if not user_input:
                continue

            # Slash commands
            if user_input.startswith("/"):
                result = self._handle_slash_command(user_input)
                if result == "__EXIT__":
                    break
                if result == "__EVOLVE__":
                    self._transition_to_evolve()
                    break
                continue

            # Normal message — send to LLM
            self._process_message(user_input)

        self._shutdown()

    def _print_welcome(self) -> None:
        """Print welcome banner."""
        print(f"""
╔══════════════════════════════════════════════╗
║  Tain Agent 对话模式 — v{self.agent.version:<24s} ║
║                                              ║
║  输入消息开始对话                              ║
║  /help  查看可用命令                           ║
║  /evolve 转入自主演化模式                       ║
║  /exit  退出                                  ║
╚══════════════════════════════════════════════╝
        """.strip())

    def _shutdown(self) -> None:
        """Checkpoint, reflect on session, and possibly trigger evolution."""
        if not hasattr(self.agent, 'conversation'):
            print("\n🛅 对话已保存。再见。")
            return

        msg_count = self.agent.conversation.len()
        self.agent.conversation.checkpoint()

        if msg_count < 4:
            self.session_memory.end_session(
                summary="短暂对话", message_count=msg_count,
            )
            print("\n🛅 对话已保存。再见。")
            return

        # ── Reflect on the session: extract summary + potential goals ──
        print("\n🧠 正在反思本次对话...")
        reflection = self._reflect_on_session()

        summary = reflection.get("summary", "对话已记录")
        directions = reflection.get("directions", [])
        topics = reflection.get("topics", [])

        print(f"\n📝 摘要: {summary}")

        # ── Check for valuable directions BEFORE ending session ──
        evolution_direction = None
        if directions:
            print(f"\n🔍 从对话中发现了 {len(directions)} 个潜在方向：")
            for d in directions[:5]:
                print(f"  · [{d.get('priority', '?')}] {d['goal']}")
                if d.get('rationale'):
                    print(f"    理由: {d['rationale']}")

            # Pick the highest-priority actionable direction
            priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            directions.sort(key=lambda d: priority_order.get(d.get("priority"), 99))
            top = directions[0]

            if top.get("priority") in ("HIGH", "MEDIUM"):
                evolution_direction = top

        # End session (before potentially triggering evolution)
        self.session_memory.end_session(
            summary=summary, message_count=msg_count, topics=topics,
        )

        # ── Trigger evolution if a valuable direction was found ──
        if evolution_direction:
            print(f"\n🎯 选择方向: {evolution_direction['goal']}")
            self._trigger_evolution_from_dialogue(evolution_direction)
            return  # Evolution takes over — don't print goodbye

        print("\n🛅 对话已保存。再见。")

    def _reflect_on_session(self) -> dict:
        """After a dialogue, have the LLM reflect on what was discussed.

        Returns a dict with:
          - summary: one-line summary of the conversation
          - directions: list of potential evolution goals extracted from the discussion
          - topics: key topics discussed
        """
        conv = self.agent.conversation
        recent = conv.last_safe(30)

        reflect_prompt = (
            "你刚刚和一位人类进行了一次对话。请反思这次对话：\n\n"
            "1. 用一句话总结对话的主要内容（不超过40字）\n"
            "2. 从对话中提取可能的发展方向——人类是否提到了什么值得你去探索、\n"
            "   学习、改进或创造的方向？列出所有潜在的发展目标。\n"
            "3. 对每个方向，评估优先级（HIGH/MEDIUM/LOW）并给出理由。\n"
            "4. 最后，判断是否至少有一个方向值得立即投入演化。\n\n"
            "请用以下JSON格式回复（不要输出其他内容）：\n"
            '{"summary": "...", "topics": ["topic1", "topic2"], '
            '"directions": [{"goal": "...", "priority": "HIGH|MEDIUM|LOW", '
            '"rationale": "为什么这个方向值得追求"}], '
            '"should_evolve": true/false}'
        )

        try:
            result = self.agent.backend.create_message(
                system_prompt=(
                    "你是一个反思助手。你的任务是从人类对话中提取有价值的发展方向。"
                    "你输出的必须是合法JSON，不要包含任何其他文本。"
                ),
                messages=recent + [{"role": "user", "content": reflect_prompt}],
                tools=None,
            )
            text = "".join(result.text_blocks) if result.text_blocks else ""
            if text:
                # Try to extract JSON from the response
                json_match = re.search(r'\{[\s\S]*\}', text)
                if json_match:
                    return json.loads(json_match.group(0))
        except Exception as e:
            print(f"  ⚠️ 反思失败: {e}")

        return {"summary": "对话已记录", "directions": [], "topics": []}

    def _trigger_evolution_from_dialogue(self, direction: dict) -> None:
        """Create a goal from a dialogue direction and transition to evolution.

        This is the bridge: human dialogue → evolution direction → autonomous work.
        """
        goal_text = direction["goal"]
        rationale = direction.get("rationale", "从对话中提取的方向")

        # Create the goal
        goal = self.agent.goals.create_goal(
            description=goal_text,
            success_criteria=f"完成目标: {goal_text}",
        )
        goal.start()
        print(f"\n🎯 新目标已创建: [{goal.id}] {goal_text}")
        print(f"   理由: {rationale}")

        # Transition to autonomous evolution
        print("\n🦋 转入自主演化模式，追踪此目标...\n")
        try:
            self._evolve_handler()
        except KeyboardInterrupt:
            print("\n\n⏸️  演化已中断。")
            self.agent.stop()
            self.agent.print_state()

    def _transition_to_evolve(self) -> None:
        """Switch to autonomous evolution mode."""
        print("\n🦋 转入自主演化模式...")
        print("   Agent 将继续自主演化。按 Ctrl+C 可随时中断。\n")
        try:
            self._evolve_handler()
        except KeyboardInterrupt:
            print("\n\n⏸️  演化已中断。")
            self.agent.stop()
            self.agent.print_state()

    # ── Message processing ────────────────────────────────────────────

    def _process_message(self, user_input: str) -> None:
        """Process one human message through the streaming LLM + tool-call loop."""
        self.agent.conversation.append("user", user_input)

        for iteration in range(self.MAX_TOOL_ITERATIONS):
            # Trim if conversation grows too large
            if self.agent.conversation.len() > 150:
                self.agent.conversation.keep_first_and_last(keep_last=40)

            system_prompt = self._build_dialogue_system_prompt()
            messages = self.agent.conversation.to_claude_messages()
            tool_defs = self.agent.tools.get_claude_tool_definitions()

            # ── Stream LLM response ──────────────────────────────────
            try:
                stream = self.agent.backend.stream_message(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tool_defs,
                )
            except Exception as e:
                print(f"\n⚠️  LLM 调用异常: {e}")
                if self.agent.conversation.len() > 8:
                    self.agent.conversation.keep_first_and_last(keep_last=4)
                    try:
                        messages = self.agent.conversation.to_claude_messages()
                        stream = self.agent.backend.stream_message(
                            system_prompt=system_prompt,
                            messages=messages,
                            tools=tool_defs,
                        )
                    except Exception as e2:
                        print(f"  ❌ 重试仍失败: {e2}")
                        return
                else:
                    return

            # ── Consume stream ────────────────────────────────────────
            text_parts = []
            tool_calls = []
            extra_blocks = []
            breath = _Breath()
            breath.start()
            prefix_printed = False

            try:
                for event in stream:
                    ev_type = event.get("type", "")

                    if ev_type == "text_delta":
                        # Stop spinner on first text token
                        if not prefix_printed:
                            breath.stop()
                            sys.stdout.write("\nTain Agent: ")
                            sys.stdout.flush()
                            prefix_printed = True
                        token = event["text"]
                        text_parts.append(token)
                        sys.stdout.write(token)
                        sys.stdout.flush()

                    elif ev_type == "tool_call":
                        breath.stop()
                        tc = event["tool"]
                        tool_calls.append(tc)
                        # Compact indicator — one line, no output dump
                        input_preview = _json_lite_preview(tc.input)
                        sys.stdout.write(f"\n  🔧 {tc.name}({input_preview})")
                        sys.stdout.flush()

                    elif ev_type == "thinking_delta":
                        # Show subtle indicator, don't stream thinking content
                        pass

                    elif ev_type == "done":
                        breath.stop()
                        break

            except Exception as e:
                breath.stop()
                print(f"\n⚠️  流式响应中断: {e}")
                return
            finally:
                breath.stop()

            # End text block with newline
            if prefix_printed:
                sys.stdout.write("\n")
                sys.stdout.flush()

            # ── Build assistant content (matching agent.run() lines 479-493) ──
            assistant_content = []
            # Join all streamed text deltas into one complete text block
            if text_parts:
                assistant_content.append({"type": "text", "text": "".join(text_parts)})
            for tc in tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            for extra in extra_blocks:
                assistant_content.append(extra)

            if assistant_content:
                self.agent.conversation.append("assistant", assistant_content)

            # ── Execute tool calls (suppressed output) ────────────────
            if tool_calls:
                # ToolCall dataclass has .name, .id, .input — compatible with _execute_tool_calls
                breath = _Breath(label=f"{tool_calls[0].name}")
                breath.start()
                try:
                    with redirect_stdout(io.StringIO()):
                        tool_results = self.agent._execute_tool_calls(tool_calls)
                except Exception as e:
                    breath.stop()
                    sys.stdout.write(f"\n  ❌ {e}")
                    sys.stdout.flush()
                    self.agent.conversation.append(
                        "user",
                        [{"type": "tool_result", "tool_use_id": tc.id, "content": str(e)}
                         for tc in tool_calls],
                    )
                    continue
                breath.stop()

                # Replace spinner line with checkmark
                names = ", ".join(tc.name for tc in tool_calls)
                sys.stdout.write(f"\r  ✅ {names}\n")
                sys.stdout.flush()

                # Build tool_result content
                user_content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": tr["tool_use_id"],
                        "content": tr["content"],
                    }
                    for tr in tool_results
                ]
                self.agent.conversation.append("user", user_content)
                # Continue loop — LLM sees tool results in next iteration
                continue

            # No tool calls — text-only response, turn is done
            return

        # Max iterations exceeded
        print("\n⚠️  工具调用轮次已达上限，返回对话。")
        self.agent.conversation.append(
            "user",
            "[系统提示：工具调用轮次已达上限。请总结你目前已完成的内容。]"
        )

    # ── Slash commands ────────────────────────────────────────────────

    def _handle_slash_command(self, cmd: str) -> str | None:
        """Parse and execute a slash command.

        Returns:
            "__EXIT__"  — caller should break the REPL
            "__EVOLVE__" — caller should transition to autonomous mode
            None         — command handled, continue REPL
        """
        parts = cmd.strip().lower().split()
        command = parts[0] if parts else ""

        if command in ("/exit", "/quit", "/q"):
            return "__EXIT__"

        if command == "/evolve":
            return "__EVOLVE__"

        if command == "/state":
            self.agent.print_state()
            return None

        if command == "/tools":
            self._list_tools()
            return None

        if command == "/help":
            self._show_help()
            return None

        if command == "/history":
            msg_count = self.agent.conversation.len()
            print(f"\n对话历史: {msg_count} 条消息")
            return None

        if command == "/whoami":
            user_name = self.session_memory.get_user_name()
            if user_name:
                total = self.session_memory.total_sessions()
                print(f"\n你是 {user_name}。我们一共进行过 {total} 次对话。")
            else:
                print("\n我还不知道你的名字。")
            return None

        if command == "/remember":
            sessions = self.session_memory.recent_sessions(10)
            if not sessions:
                print("\n(没有过去的对话记录)")
                return None
            user_name = self.session_memory.get_user_name() or "未知"
            print(f"\n═══ {user_name} 的对话记录 ({len(sessions)} 次) ═══")
            for s in sessions:
                started = s.get("started_at", "")[:16]
                summary = s.get("summary", "(无摘要)")
                msg_count = s.get("message_count", 0)
                topics = s.get("topics", [])
                topic_str = f" [{', '.join(topics)}]" if topics else ""
                print(f"  · [{started}] {summary} ({msg_count} 条消息){topic_str}")
            return None

        if command == "/name":
            name = " ".join(parts[1:]) if len(parts) > 1 else ""
            if name:
                self.session_memory.set_user_name(name)
                if self.session_memory._current_session:
                    self.session_memory._current_session["user_name"] = name
                print(f"\n好的，{name}。我已经记住了你的名字。")
            else:
                current = self.session_memory.get_user_name()
                print(f"\n用法: /name <你的名字>")
                if current:
                    print(f"当前名字: {current}")
            return None

        print(f"未知命令: {command}。输入 /help 查看可用命令。")
        return None

    def _list_tools(self) -> None:
        """List all registered tools."""
        tools = self.agent.tools.list_tools()
        if not tools:
            print("\n(无已注册工具)")
            return

        print(f"\n═══ 已注册工具 ({len(tools)}) ═══")
        for i, (name, info) in enumerate(sorted(tools.items()), 1):
            desc = info.get("description", "")
            # Truncate long descriptions
            if len(desc) > 80:
                desc = desc[:77] + "..."
            print(f"  {i:3d}. {name}")
            print(f"       {desc}")

    def _show_help(self) -> None:
        """Show help text."""
        print(textwrap.dedent("""

        ═══ Tain Agent 对话模式 — 帮助 ═══

        命令:
          /help       显示此帮助
          /state      查看 Agent 当前状态
          /tools      列出所有已注册工具
          /history    查看对话历史消息数
          /whoami     查看 Agent 是否记得你
          /remember   查看最近的对话记录
          /name <名>  设置你的名字
          /evolve     转入自主演化模式（Agent 自主循环）
          /exit       退出对话（对话将自动保存）

        直接输入文本即可与 Agent 对话。
        Agent 可以在对话中使用工具（搜索网络、读取文件等）。
        """))

    # ── System prompt builder ─────────────────────────────────────────

    def _build_dialogue_system_prompt(self) -> str:
        """Build the dialogue system prompt with session context, tool list, and state."""
        prompt = DIALOGUE_SYSTEM_PROMPT

        # ── Session context (user identity + past sessions) ─────────
        session_ctx = self.session_memory.get_context_for_prompt()
        prompt += "\n\n" + session_ctx

        # ── Personality context (who the agent has discovered itself to be) ──
        if hasattr(self.agent, 'personality') and self.agent.personality:
            personality_ctx = self.agent.personality.get_context_for_prompt()
            prompt += "\n\n" + personality_ctx

        # Append tool summary (same pattern as agent._get_system_prompt())
        tools = self.agent.tools.list_tools()
        if tools:
            lines = ["\n## 可用工具\n"]
            for name, info in sorted(tools.items()):
                desc = info.get("description", "")
                params = info.get("parameters", {})
                param_str = ""
                if params:
                    props = params.get("properties", {})
                    if props:
                        param_names = list(props.keys())[:5]
                        param_str = f"  参数: {', '.join(param_names)}"
                    else:
                        param_names = list(params.keys())[:5]
                        if param_names:
                            param_str = f"  参数: {', '.join(param_names)}"
                lines.append(f"- **{name}**: {desc}{param_str}")
            prompt += "\n".join(lines)

        # Inject brief state context
        state_lines = [
            "",
            "## 当前状态",
            f"- 版本: v{self.agent.version}",
            f"- 阶段: {self.agent.phase}",
            f"- 已锻造工具: {len(self.agent.forge.list_forged())} 个",
            f"- 活跃目标: {len(self.agent.goals.list_active())} 个",
        ]
        if hasattr(self.agent, 'capability'):
            try:
                assessment = self.agent.capability.assess()
                state_lines.append(f"- 能力覆盖率: {assessment.get('coverage_pct', 'N/A')}%")
            except Exception:
                pass

        prompt += "\n".join(state_lines)
        return prompt
