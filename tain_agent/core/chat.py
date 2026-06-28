"""Chat Engine — LLM orchestration shared by Web UI and ACP."""
import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


@dataclass
class ChatTurn:
    text: str
    tool_calls: list
    tool_results: list
    thinking: str = ""


class ChatEngine:
    """Shared engine: LLM call -> parse -> execute tools. No web/SSE knowledge."""

    def __init__(self, agent, backend=None):
        self.agent = agent
        from tain_agent.runtime import AgentRuntime
        if isinstance(agent, AgentRuntime):
            self._kernel = agent
            if backend:
                self._backend = backend
            else:
                from tain_agent.core.llm import create_backend
                self._backend = create_backend(agent.ctx.config)
        else:
            self._kernel = getattr(agent, 'kernel', None)
            self._backend = backend or getattr(agent, 'backend', None)

    async def run_turn(self, messages: list[dict],
                       cancel_event=None,
                       max_tool_turns: int = 5) -> AsyncGenerator[dict, None]:
        system_prompt = self.build_system_prompt()
        tool_defs = self._build_tool_defs()
        text_parts: list[str] = []
        reasoning_text = ""
        total_tool_calls = 0
        all_results: list[dict] = []
        turn_tools: list = []

        yield {"type": "thinking"}

        for turn in range(max_tool_turns):
            if cancel_event and cancel_event.is_set():
                break

            tools_for_turn = tool_defs if total_tool_calls < 3 else None
            try:
                stream = self._backend.stream_message(
                    system_prompt=system_prompt, messages=messages, tools=tools_for_turn)
            except Exception as e:
                logger.warning("LLM stream error: %s", e)
                break

            turn_text, turn_tools, turn_reasoning = [], [], ""
            for event in stream:
                t = event.get("type", "")
                if t == "thinking_delta":
                    turn_reasoning += event.get("text", "")
                elif t == "text_delta":
                    turn_text.append(event["text"])
                elif t == "tool_call":
                    turn_tools.append(event["tool"])
                elif t == "done":
                    if event.get("reasoning_content"):
                        turn_reasoning = event["reasoning_content"]
                    break

            full = "".join(turn_text)
            if not turn_tools and re.search(r'<[^>]*?tool_calls?>', full):
                prefix, xml_tcs = _extract_xml_tool_calls(full)
                turn_text = [prefix] if prefix else []
                turn_tools = xml_tcs

            text_parts.extend(turn_text)
            if turn_reasoning:
                reasoning_text = turn_reasoning
            if not turn_tools:
                break

            yield {"type": "tool_start", "tool_names": [tc.name for tc in turn_tools]}

            total_tool_calls += len(turn_tools)
            try:
                if self._kernel:
                    results = []
                    for tc in turn_tools:
                        result = self._kernel.dispatch.call("tool.call", tc.name, **tc.input)
                        content = str(result) if result is not None else f"Tool '{tc.name}' returned no result"
                        results.append({"tool_use_id": tc.id, "content": content})
                else:
                    results = self.agent._execute_tool_calls(turn_tools)
                all_results.extend(results)
                tool_msgs = [
                    {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]}
                    for r in results
                ]
                assistant_msg = {"role": "assistant", "content": [
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in turn_tools
                ]}
                if turn_reasoning:
                    assistant_msg["reasoning_content"] = turn_reasoning
                messages.append(assistant_msg)
                messages.append({"role": "user", "content": tool_msgs})
            except Exception as e:
                logger.warning("Tool execution error: %s", e)
                break

        clean = re.sub(
            r'<[^>]*?tool_calls>.*?</[^>]*?tool_calls>', '',
            "".join(text_parts), flags=re.DOTALL).strip()

        yield {"type": "done", "turn": ChatTurn(
            text=clean or "[Tool processing — no text response]",
            tool_calls=turn_tools,
            tool_results=all_results,
            thinking=reasoning_text,
        )}

    def build_system_prompt(self) -> str:
        agent = self.agent
        if self._kernel:
            agent_name = agent.ctx.agent_name
        else:
            agent_name = agent.agent_name
        lines = [
            f"你是 {agent_name}，诞生于'道'的演化框架。",
            "现在，你正在与一位人类对话。",
            "",
            "对话原则：",
            "- 诚实直接地回答，不编造信息",
            "- 当需要查询信息时，自然调用工具",
            "- 用中文回答",
            "- 对你不确定的事情保持诚实",
        ]
        personality = None
        if self._kernel:
            ip = self._kernel.lifecycle.get("identity")
            if ip and hasattr(ip, 'personality'):
                personality = ip.personality
        else:
            personality = getattr(agent, 'personality', None)

        if personality:
            try:
                ctx = personality.get_context_for_prompt()
                if ctx:
                    lines.append("\n" + ctx)
            except Exception:
                pass
        tools = {}
        if self._kernel:
            tp = self._kernel.lifecycle.get("tool")
            if tp and hasattr(tp, 'list_tools'):
                tools = tp.list_tools()
        elif hasattr(agent, 'tools') and hasattr(agent.tools, 'list_tools'):
            tools = agent.tools.list_tools()
        if tools:
            from tain_agent.utils.token_utils import estimate_tokens
            lines.append("\n## 可用工具\n")
            total = 0
            for name, info in sorted(tools.items()):
                desc = info.get("description", "")
                dt = estimate_tokens(desc)
                if dt > 80:
                    desc = desc[:160] + "..."
                elif total + dt > 3000:
                    desc = desc[:100] + "..."
                total += estimate_tokens(desc)
                lines.append(f"- **{name}**: {desc}")
        return "\n".join(lines)

    def _get_tool_defs(self):
        if self._kernel:
            tp = self._kernel.lifecycle.get("tool")
            if tp and hasattr(tp, 'get_claude_tool_definitions'):
                return tp.get_claude_tool_definitions()
        if hasattr(self.agent, 'tools') and hasattr(self.agent.tools, 'get_claude_tool_definitions'):
            return self.agent.tools.get_claude_tool_definitions()
        return None

    def _build_tool_defs(self) -> list | None:
        all_tools = self._get_tool_defs()
        if not all_tools:
            return None
        safe = [t for t in all_tools
                if not t["name"].startswith(("test_", "forge_", "_"))]
        priority = [t for t in safe
                    if any(t["name"].startswith(p)
                           for p in ("web_search", "web_fetch", "knowledge_fetch", "wikipedia"))]
        others = [t for t in safe if t not in priority]
        return (priority + others)[:20] if safe else None


def _extract_xml_tool_calls(text: str) -> tuple[str, list]:
    """Parse XML-format tool calls from text. Returns (prefix_text, list_of_ToolCall)."""
    from tain_agent.core.llm import ToolCall
    pattern = r'<[^>]*?tool_calls?>\s*(.*?)\s*</[^>]*?tool_calls?>'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return text, []
    prefix = text[:match.start()].rstrip()
    xml_content = match.group(0)
    clean_xml = re.sub(r'(</?)(?:[\w]+:|[\|｜]+[\w]+[\|｜]+)', r'\1', xml_content)
    try:
        root = ET.fromstring(clean_xml)
    except ET.ParseError:
        tcs = _regex_fallback(xml_content)
        return (prefix, tcs) if tcs else (text, [])
    tool_calls = []
    for invoke in root.findall('invoke'):
        name = invoke.get('name', '')
        params = {}
        for param in invoke.findall('parameter'):
            pname = param.get('name', '')
            pvalue = (param.text or '').strip()
            if pvalue.startswith('{') or pvalue.startswith('['):
                try:
                    pvalue = json.loads(pvalue)
                except json.JSONDecodeError:
                    pass
            params[pname] = pvalue
        if name:
            tool_calls.append(ToolCall(
                id=f"xml_{uuid.uuid4().hex[:8]}", name=name, input=params))
    return prefix, tool_calls


def _regex_fallback(xml_text: str) -> list:
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
                id=f"xml_{uuid.uuid4().hex[:8]}", name=name, input=params))
    return tool_calls
