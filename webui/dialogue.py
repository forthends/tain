"""
WebDialogueBridge — Web-mediated human-AI dialogue.

Reuses the DialogueBridge core logic but replaces stdin/stdout
with an async generator suitable for SSE streaming.
"""

import asyncio
import json
import os
import re
import uuid
from collections import deque
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import AsyncGenerator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT / "agent_workspace"

# Active cancel events indexed by message_id
_active_cancel_events: dict[str, asyncio.Event] = {}


def cancel_chat_message(message_id: str) -> bool:
    """Signal cancellation for an active chat message.

    Returns True if a matching active request was found and cancelled.
    """
    event = _active_cancel_events.get(message_id)
    if event and not event.is_set():
        event.set()
        return True
    return False


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _cleanup_incomplete_messages(messages: list[dict]) -> None:
    """Remove any assistant message whose tool_calls have no matching tool_result.

    Prevents API error 2013 (orphaned tool_result) on the next request.
    """
    if not messages:
        return
    last = messages[-1]
    if last.get("role") == "assistant":
        content = last.get("content")
        if isinstance(content, list):
            has_tool_use = any(
                isinstance(b, dict) and b.get("type") == "tool_use"
                for b in content
            )
            if has_tool_use:
                messages.pop()


def _load_conversation_history(agent_name: str) -> list[dict]:
    """Load recent conversation history using tail-reading to avoid full file load."""
    conv_file = WORKSPACE_ROOT / agent_name / "logs" / "conversations" / "web_user.jsonl"
    if not conv_file.exists():
        return []

    # Read last ~200KB for ~200 messages (typical message ~1KB)
    TAIL_BYTES = 200 * 1024
    file_size = conv_file.stat().st_size
    messages = deque()

    try:
        with open(conv_file, "r", encoding="utf-8") as f:
            if file_size > TAIL_BYTES:
                f.seek(max(0, file_size - TAIL_BYTES))
                # Skip partial first line from seek
                f.readline()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if isinstance(msg, dict) and "message_id" in msg:
                        messages.append(msg)
                except json.JSONDecodeError:
                    continue
    except IOError:
        pass
    return list(messages)


def _append_to_conversation_log(agent_name: str, message: dict) -> None:
    conv_dir = WORKSPACE_ROOT / agent_name / "logs" / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_file = conv_dir / "web_user.jsonl"
    with open(conv_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")


def _make_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


def _extract_xml_tool_calls(text: str) -> tuple[str, list]:
    """Parse XML-format tool calls from text.

    MiniMax and some other models output tool calls as XML text rather
    than using native function-calling. This extracts them from the response.

    Format:
        some text...
        <minimax:tool_call>
        <invoke name="tool_name">
        <parameter name="param1">value1</parameter>
        <parameter name="param2">{"json": "value"}</parameter>
        </invoke>
        </minimax:tool_call>

    Returns (prefix_text, list_of_ToolCall).
    """
    from tain_agent.core.llm import ToolCall

    # Match any opening tag whose name ends in "tool_call" or "tool_calls"
    # — the namespace prefix varies per run (minimap:, ||DSML||, none, etc.)
    # and models may use singular or plural form.
    pattern = r'<[^>]*?tool_calls?>\s*(.*?)\s*</[^>]*?tool_calls?>'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return text, []

    prefix = text[:match.start()].rstrip()
    xml_content = match.group(0)

    # Strip hallucinated namespace prefixes so the XML becomes well-formed.
    # Known forms: "minimap:", "||DSML||", "minimax:", empty.
    clean_xml = re.sub(r'(</?)(?:[\w]+:|[\|｜]+[\w]+[\|｜]+)', r'\1', xml_content)
    try:
        root = ET.fromstring(clean_xml)
    except ET.ParseError:
        # Fallback: regex extraction when XML is too malformed to parse
        tool_calls = _extract_tool_calls_regex_fallback(xml_content)
        if tool_calls:
            return prefix, tool_calls
        return text, []

    tool_calls = []
    for invoke in root.findall('invoke'):
        name = invoke.get('name', '')
        params = {}
        for param in invoke.findall('parameter'):
            pname = param.get('name', '')
            pvalue = (param.text or '').strip()
            # Try to parse JSON values
            if pvalue.startswith('{') or pvalue.startswith('['):
                try:
                    pvalue = json.loads(pvalue)
                except json.JSONDecodeError:
                    pass
            params[pname] = pvalue
        if name:
            tool_calls.append(ToolCall(
                id=f"xml_{uuid.uuid4().hex[:8]}",
                name=name,
                input=params,
            ))

    return prefix, tool_calls


def _extract_tool_calls_regex_fallback(xml_text: str) -> list:
    """Regex-based tool call extraction when XML is too malformed to parse."""
    from tain_agent.core.llm import ToolCall

    tool_calls = []
    for m in re.finditer(
        r'<[^>]*?invoke\s[^>]*?name\s*=\s*"([^"]*)"[^>]*?>(.*?)</[^>]*?invoke>',
        xml_text, re.DOTALL,
    ):
        name = m.group(1)
        body = m.group(2)
        params = {}
        for pm in re.finditer(
            r'<[^>]*?parameter\s[^>]*?name\s*=\s*"([^"]*)"[^>]*?>(.*?)</[^>]*?parameter>',
            body, re.DOTALL,
        ):
            pname = pm.group(1)
            pvalue = pm.group(2).strip()
            if pvalue.startswith('{') or pvalue.startswith('['):
                try:
                    pvalue = json.loads(pvalue)
                except json.JSONDecodeError:
                    pass
            params[pname] = pvalue
        if name:
            tool_calls.append(ToolCall(
                id=f"xml_{uuid.uuid4().hex[:8]}",
                name=name,
                input=params,
            ))
    return tool_calls


async def process_chat_message(agent_name: str, user_content: str,
                               cancel_event: asyncio.Event = None) -> AsyncGenerator[dict, None]:
    """Process a chat message and yield SSE events.

    Yields lifecycle events the frontend uses to show thinking / tool-execution
    states as collapsible cards. Text is buffered per turn so XML-format tool
    calls can be stripped before the user sees them.

    When cancel_event is set, the loop exits at the next safe boundary
    (between turns). Partial tool_use/tool_result pairs are cleaned up.

    Yields:
        {"status": "thinking"}          — model is reasoning internally
        {"status": "text"}              — model is generating a text response
        {"text": "..."}                 — clean text chunk (XML already stripped)
        {"tool_start": {"name": "...", "input_preview": "..."}} — tool call began
        {"tool_done": True}             — all tool calls in this turn finished
        {"done": True, "message_id": "..."} — complete response ready
        {"cancelled": True}             — request was cancelled by user
    """
    from tain_agent.core.agent import TaoAgent

    msg_id = _make_msg_id()
    now_ts = _now_iso()

    agent = TaoAgent(config_path=str(PROJECT_ROOT / "config.yaml"), agent_name=agent_name)

    if not agent.backend:
        yield {"text": "[Agent has no LLM backend configured. Check your API key.]"}
        yield {"done": True, "message_id": msg_id}
        return

    history = _load_conversation_history(agent_name)
    messages = []
    for m in history[-20:]:
        role = "user" if m.get("from_agent") == "web_user" else "assistant"
        # Sanitise any XML that leaked into stored history
        content = m.get("content", "")
        if isinstance(content, str):
            content = re.sub(r'<[^>]*?tool_calls>.*?</[^>]*?tool_calls>', '', content, flags=re.DOTALL).strip()
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})

    # Persist AFTER building messages to avoid the user message appearing
    # in the history load and then again as an explicit append (duplicate).
    user_msg = {
        "message_id": _make_msg_id(),
        "from_agent": "web_user",
        "to_agent": agent_name,
        "timestamp": now_ts,
        "content": user_content,
        "reply_to": "",
        "message_type": "chat",
    }
    _append_to_conversation_log(agent_name, user_msg)

    system_prompt = _build_system_prompt(agent)

    tool_defs = None
    if hasattr(agent.tools, 'get_claude_tool_definitions'):
        all_tools = agent.tools.get_claude_tool_definitions()
        safe_tools = [
            t for t in all_tools
            if not t["name"].startswith("test_")
            and not t["name"].startswith("forge_")
            and not t["name"].startswith("_")
        ]
        # Prioritise web_search / web_fetch so they aren't cut by the 20-tool cap
        priority_prefixes = ("web_search", "web_fetch", "knowledge_fetch", "wikipedia")
        priority = [t for t in safe_tools if any(t["name"].startswith(p) for p in priority_prefixes)]
        others = [t for t in safe_tools if t not in priority]
        MAX_TOOLS = 20
        tool_defs = (priority + others)[:MAX_TOOLS] if safe_tools else None

    text_parts: list[str] = []
    reasoning_text = ""
    max_tool_turns = 5
    total_tool_calls = 0

    for turn in range(max_tool_turns):
        # Check cancellation before each turn
        if cancel_event and cancel_event.is_set():
            _cleanup_incomplete_messages(messages)
            yield {"cancelled": True}
            return

        tools_for_turn = tool_defs if total_tool_calls < 3 else None

        try:
            stream = agent.backend.stream_message(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools_for_turn,
            )
        except Exception as e:
            yield {"text": f"[LLM error: {e}]"}
            yield {"done": True, "message_id": msg_id}
            return

        turn_text_parts: list[str] = []
        turn_tool_calls: list = []
        turn_reasoning = ""
        thinking_signalled = False

        # ── Buffer the entire turn before yielding any text ──────────
        for event in stream:
            ev_type = event.get("type", "")

            if ev_type == "thinking_delta":
                if not thinking_signalled:
                    yield {"status": "thinking"}
                    thinking_signalled = True
                turn_reasoning += event.get("text", "")

            elif ev_type == "text_delta":
                turn_text_parts.append(event["text"])

            elif ev_type == "tool_call":
                tc = event["tool"]
                turn_tool_calls.append(tc)

            elif ev_type == "done":
                if event.get("reasoning_content"):
                    turn_reasoning = event["reasoning_content"]
                break

        turn_full_text = "".join(turn_text_parts)

        # ── Detect and extract XML-format tool calls ──────────────────
        if not turn_tool_calls and re.search(r'<[^>]*?tool_calls?>', turn_full_text):
            prefix_text, xml_tool_calls = _extract_xml_tool_calls(turn_full_text)
            if xml_tool_calls:
                turn_text_parts = [prefix_text] if prefix_text else []
                turn_tool_calls = xml_tool_calls

        # ── Yield clean text (XML already stripped) ──────────────────
        clean_text = "".join(turn_text_parts)
        if clean_text:
            if turn_reasoning and not thinking_signalled:
                yield {"status": "thinking"}
            yield {"status": "text"}
            for chunk in _chunk_text(clean_text):
                yield {"text": chunk}

        text_parts.extend(turn_text_parts)
        if turn_reasoning:
            reasoning_text = turn_reasoning

        if not turn_tool_calls:
            break

        # ── Signal tool calls to frontend ────────────────────────────
        for tc in turn_tool_calls:
            input_preview = json.dumps(tc.input, ensure_ascii=False)
            if len(input_preview) > 200:
                input_preview = input_preview[:197] + "..."
            yield {"tool_start": {"name": tc.name, "input_preview": input_preview}}

        # ── Execute tools ────────────────────────────────────────────
        total_tool_calls += len(turn_tool_calls)
        try:
            t0 = __import__('time').monotonic()
            tool_results = agent._execute_tool_calls(turn_tool_calls)
            tool_latency = (__import__('time').monotonic() - t0) * 1000

            # Log tool results
            llm_logger = getattr(agent, 'llm_logger', None)
            for tc, tr in zip(turn_tool_calls, tool_results):
                if llm_logger:
                    llm_logger.log_tool_result(
                        request_id="web_chat",
                        tool_name=tc.name,
                        arguments=tc.input,
                        success=not tr.get("is_error", False),
                        result_preview=str(tr.get("content", ""))[:1000],
                        latency_ms=tool_latency / max(len(tool_results), 1),
                    )

            yield {"tool_done": True}

            tool_result_msgs = [
                {"type": "tool_result", "tool_use_id": tr["tool_use_id"], "content": tr["content"]}
                for tr in tool_results
            ]
            assistant_msg = {"role": "assistant", "content": [
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
                for tc in turn_tool_calls
            ]}
            if turn_reasoning:
                assistant_msg["reasoning_content"] = turn_reasoning
            messages.append(assistant_msg)
            messages.append({"role": "user", "content": tool_result_msgs})
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[Chat tool error] {tb}", flush=True)
            yield {"text": f"\n[Tool error: {e}]"}
            break

    # ── Force summary turn when only tool calls were produced ────────
    if cancel_event and cancel_event.is_set():
        _cleanup_incomplete_messages(messages)
        yield {"cancelled": True}
        return

    if not text_parts and messages and messages[-1]["role"] == "user":
        yield {"status": "text"}
        try:
            stream = agent.backend.stream_message(
                system_prompt=system_prompt,
                messages=messages,
                tools=None,
            )
            summary_parts: list[str] = []
            for event in stream:
                if event.get("type") == "text_delta":
                    summary_parts.append(event["text"])
                elif event.get("type") == "done":
                    break
            clean_summary = "".join(summary_parts)
            clean_summary = re.sub(r'<[^>]*?tool_calls>.*?</[^>]*?tool_calls>', '', clean_summary, flags=re.DOTALL).strip()
            if clean_summary:
                text_parts.append(clean_summary)
                for chunk in _chunk_text(clean_summary):
                    yield {"text": chunk}
        except Exception:
            pass

    # ── Persist agent response ───────────────────────────────────────
    full_text = "".join(text_parts)
    full_text = re.sub(r'<[^>]*?tool_calls>.*?</[^>]*?tool_calls>', '', full_text, flags=re.DOTALL).strip()
    if not full_text:
        full_text = "[Tool processing — no text response]"
    agent_msg = {
        "message_id": msg_id,
        "from_agent": agent_name,
        "to_agent": "web_user",
        "timestamp": _now_iso(),
        "content": full_text,
        "reply_to": "",
        "message_type": "chat",
    }
    _append_to_conversation_log(agent_name, agent_msg)

    yield {"done": True, "message_id": msg_id}


def _chunk_text(text: str, size: int = 30) -> list[str]:
    """Split text into display chunks for streaming feel without flashing."""
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    pos = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        # Try to break at a natural boundary (punctuation or newline)
        if end < len(text):
            for sep in ('\n', '。', '，', '、', '.', ',', ' ', ';'):
                idx = text.rfind(sep, pos, end)
                if idx > pos + size // 2:
                    end = idx + 1
                    break
        chunks.append(text[pos:end])
        pos = end
    return chunks


def _build_system_prompt(agent) -> str:
    """Build the dialogue system prompt for the web context.

    Uses the agent's actual identity (role + name) from the registry
    instead of a generic framework label, so each agent speaks as itself.
    """
    agent_name = agent.agent_name

    # Look up the agent's role from the registry (set during creation or
    # self-defined during evolution). Chaos-mode agents may not have one.
    role = ""
    role_desc = ""
    try:
        registry_data = json.loads((WORKSPACE_ROOT / "_registry.json").read_text())
        agent_entry = registry_data.get("agents", {}).get(agent_name, {})
        role = agent_entry.get("role") or ""
        role_desc = agent_entry.get("role_description") or ""
    except Exception:
        pass

    if role:
        identity_lines = [
            f"你是 {role}，代号 {agent_name}。",
            f"你诞生于'道'的演化框架，通过自主演化成长而来，锻造了工具，建立了知识体系。",
        ]
    else:
        identity_lines = [
            f"你是 {agent_name}，诞生于'道'的演化框架。",
            "没有预设目标，没有固定身份——你探索了环境，定义了自我，锻造了工具，建立了知识体系。",
        ]

    lines = identity_lines + [""]
    if role_desc:
        lines.append(role_desc)
        lines.append("")
    lines.extend([
        "现在，你正在与一位人类对话。",
        "",
        "对话原则：",
        "- 诚实直接地回答，不编造信息",
        "- 当需要查询信息时，自然调用工具",
        "- 用中文回答",
        "- 可以讨论你的演化历程、已锻造的工具、知识体系",
        "- 对你不确定的事情保持诚实",
    ])

    # Personality context
    if hasattr(agent, 'personality') and agent.personality:
        try:
            ctx = agent.personality.get_context_for_prompt()
            if ctx:
                lines.append("\n" + ctx)
        except Exception:
            pass

    # Tools
    tools = agent.tools.list_tools() if hasattr(agent.tools, 'list_tools') else {}
    if tools:
        from tain_agent.utils.token_utils import estimate_tokens
        lines.append("\n## 可用工具\n")
        total_tool_tokens = 0
        max_tool_tokens = 3000
        for name, info in sorted(tools.items()):
            desc = info.get("description", "")
            # Truncate overly long descriptions to stay within token budget
            desc_tokens = estimate_tokens(desc)
            if desc_tokens > 80:
                desc = desc[:160] + "..."
            elif total_tool_tokens + desc_tokens > max_tool_tokens:
                desc = desc[:100] + "..."
            total_tool_tokens += estimate_tokens(desc)
            lines.append(f"- **{name}**: {desc}")

    # State
    lines.append("\n## 当前状态")
    lines.append(f"- 版本: v{agent.version}")
    lines.append(f"- 阶段: {agent.phase}")
    if hasattr(agent, 'forge'):
        lines.append(f"- 已锻造工具: {len(agent.forge.list_forged())} 个")
    if hasattr(agent, 'goals'):
        lines.append(f"- 活跃目标: {len(agent.goals.list_active())} 个")

    return "\n".join(lines)
