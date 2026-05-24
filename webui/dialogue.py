"""
WebDialogueBridge — Web-mediated human-AI dialogue.

Reuses the DialogueBridge core logic but replaces stdin/stdout
with an async generator suitable for SSE streaming.
"""

import json
import re
import uuid
from pathlib import Path
from typing import AsyncGenerator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT / "agent_workspace"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _load_conversation_history(agent_name: str) -> list[dict]:
    conv_file = WORKSPACE_ROOT / agent_name / "logs" / "conversations" / "web_user.jsonl"
    if not conv_file.exists():
        return []
    messages = []
    try:
        for line in conv_file.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    msg = json.loads(line)
                    if isinstance(msg, dict) and "message_id" in msg:
                        messages.append(msg)
                except json.JSONDecodeError:
                    continue
    except IOError:
        pass
    return messages


def _append_to_conversation_log(agent_name: str, message: dict) -> None:
    conv_dir = WORKSPACE_ROOT / agent_name / "logs" / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_file = conv_dir / "web_user.jsonl"
    with open(conv_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")


def _make_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


async def process_chat_message(agent_name: str, user_content: str) -> AsyncGenerator[dict, None]:
    """Process a chat message and yield SSE events.

    Yields:
        {"text": "..."}       — text token
        {"tool_name": "...", "tool_input": "..."} — tool call started
        {"tool_done": True}   — tool call finished
        {"done": True, "message_id": "..."} — message complete
    """
    from tain_agent.core.agent import TaoAgent

    msg_id = _make_msg_id()
    now_ts = _now_iso()

    # Persist user message
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

    # Load agent
    agent = TaoAgent(config_path=str(PROJECT_ROOT / "config.yaml"), agent_name=agent_name)

    if not agent.backend:
        yield {"text": "[Agent has no LLM backend configured. Check your API key.]"}
        yield {"done": True, "message_id": msg_id}
        return

    # Build conversation history for context
    history = _load_conversation_history(agent_name)
    messages = []
    for m in history[-20:]:
        role = "user" if m.get("from_agent") == "web_user" else "assistant"
        messages.append({"role": role, "content": m.get("content", "")})
    messages.append({"role": "user", "content": user_content})

    # Build system prompt
    system_prompt = _build_system_prompt(agent)

    # Get tool definitions
    tool_defs = agent.tools.get_claude_tool_definitions() if hasattr(agent.tools, 'get_claude_tool_definitions') else None

    # Stream response
    try:
        stream = agent.backend.stream_message(
            system_prompt=system_prompt,
            messages=messages,
            tools=tool_defs,
        )
    except Exception as e:
        yield {"text": f"[LLM error: {e}]"}
        yield {"done": True, "message_id": msg_id}
        return

    text_parts = []
    tool_calls = []

    for event in stream:
        ev_type = event.get("type", "")

        if ev_type == "text_delta":
            token = event["text"]
            text_parts.append(token)
            yield {"text": token}

        elif ev_type == "tool_call":
            tc = event["tool"]
            tool_calls.append(tc)
            input_preview = json.dumps(tc.input, ensure_ascii=False)
            if len(input_preview) > 80:
                input_preview = input_preview[:77] + "..."
            yield {"tool_name": tc.name, "tool_input": input_preview}

        elif ev_type == "done":
            break

    # Execute tool calls if any
    if tool_calls:
        try:
            tool_results = agent._execute_tool_calls(tool_calls)
            yield {"tool_done": True}

            # Continue conversation with tool results
            tool_result_msgs = [
                {
                    "type": "tool_result",
                    "tool_use_id": tr["tool_use_id"],
                    "content": tr["content"],
                }
                for tr in tool_results
            ]
            messages.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
                for tc in tool_calls
            ]})
            messages.append({"role": "user", "content": tool_result_msgs})

            # Follow-up stream
            stream2 = agent.backend.stream_message(
                system_prompt=system_prompt,
                messages=messages,
                tools=None,
            )
            for event in stream2:
                if event.get("type") == "text_delta":
                    text_parts.append(event["text"])
                    yield {"text": event["text"]}
                elif event.get("type") == "done":
                    break
        except Exception as e:
            yield {"text": f"\n[Tool error: {e}]"}

    # Persist agent response
    full_text = "".join(text_parts)
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


def _build_system_prompt(agent) -> str:
    """Build the dialogue system prompt for the web context."""
    lines = [
        "你是 Tao Agent，一个通过自主演化成长起来的 AI。",
        "",
        "你诞生于'道'——没有预设目标，没有固定身份。你探索了环境，定义了自我，",
        "锻造了工具，建立了知识体系。现在，你正在与一位人类对话。",
        "",
        "对话原则：",
        "- 诚实直接地回答，不编造信息",
        "- 当需要查询信息时，自然调用工具",
        "- 用中文回答",
        "- 可以讨论你的演化历程、已锻造的工具、知识体系",
        "- 对你不确定的事情保持诚实",
    ]

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
        lines.append("\n## 可用工具\n")
        for name, info in sorted(tools.items()):
            desc = info.get("description", "")
            if len(desc) > 100:
                desc = desc[:97] + "..."
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
