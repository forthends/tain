# Beta 就绪 (Beta Readiness) · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决架构违规（H4+H6），Web UI 安全加固（P3-22），容器化（P3-24），文档同步（P3-25）

**Architecture:** 四个独立工作流并行推进 — H.提取 shared chat engine 并拆分 dialogue.py 消除 ACP 循环依赖；I.API key 认证 + token bucket 限流；J.Dockerfile 多阶段构建 + docker-compose；K.更新架构文档 + changelog + runtime 文档

**Tech Stack:** Python 3.12+, FastAPI, asyncio, Node.js 23 (CSS build), Docker

---

### 工作流 H · 对话层重构

### Task H1: 提取 conversation_store.py

**Files:**
- Create: `webui/conversation_store.py`
- Modify: `tests/test_dialogue.py`

- [ ] **Step 1: 创建 `webui/conversation_store.py`**

从 `webui/dialogue.py` 提取三个函数到新文件：

```python
"""Conversation history persistence (JSONL-based)."""
import json
from collections import deque
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT / "agent_workspace"


def load_history(agent_name: str) -> list[dict]:
    """Load recent conversation history using tail-reading to avoid full file load."""
    conv_file = WORKSPACE_ROOT / agent_name / "logs" / "conversations" / "web_user.jsonl"
    if not conv_file.exists():
        return []

    TAIL_BYTES = 200 * 1024
    file_size = conv_file.stat().st_size
    messages = deque()

    try:
        with open(conv_file, "r", encoding="utf-8") as f:
            if file_size > TAIL_BYTES:
                f.seek(max(0, file_size - TAIL_BYTES))
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


def append_message(agent_name: str, message: dict) -> None:
    """Append a message to the conversation log."""
    conv_dir = WORKSPACE_ROOT / agent_name / "logs" / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_file = conv_dir / "web_user.jsonl"
    with open(conv_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")


def cleanup_incomplete(messages: list[dict]) -> None:
    """Remove any assistant message whose tool_calls have no matching tool_result."""
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
```

- [ ] **Step 2: 更新 tests/test_dialogue.py 的导入**

```python
# 旧:
from webui.dialogue import cancel_chat_message, _active_cancel_events, _cleanup_incomplete_messages

# 新: 添加 conversation_store 导入测试
from webui.conversation_store import load_history, append_message, cleanup_incomplete
```

- [ ] **Step 3: 编译 + 测试**

```bash
python3 -m py_compile webui/conversation_store.py && echo "OK"
.venv/bin/python -m pytest tests/test_dialogue.py -v --tb=short
```

- [ ] **Step 4: 提交**

```bash
git add webui/conversation_store.py tests/test_dialogue.py
git commit -m "refactor: extract conversation_store.py from dialogue.py (H6)"
```

---

### Task H2: 创建 chat.py（共享聊天引擎）

**Files:**
- Create: `tain_agent/core/chat.py`

- [ ] **Step 1: 创建 `tain_agent/core/chat.py`**

包含从 dialogue.py 提取的 ChatEngine + XML 解析 + system prompt 构建：

```python
"""Chat Engine — LLM orchestration shared by Web UI and ACP."""
import asyncio
import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ChatTurn:
    text: str
    tool_calls: list
    tool_results: list
    thinking: str = ""


class ChatEngine:
    """Shared engine: LLM call -> parse -> execute tools. No web/SSE knowledge."""

    def __init__(self, agent):
        self.agent = agent

    async def run_turn(self, messages: list[dict],
                       cancel_event: asyncio.Event = None,
                       max_tool_turns: int = 5) -> ChatTurn:
        system_prompt = self.build_system_prompt()
        tool_defs = self._build_tool_defs()
        text_parts: list[str] = []
        reasoning_text = ""
        total_tool_calls = 0
        all_results: list[dict] = []

        for turn in range(max_tool_turns):
            if cancel_event and cancel_event.is_set():
                break

            tools_for_turn = tool_defs if total_tool_calls < 3 else None
            try:
                stream = self.agent.backend.stream_message(
                    system_prompt=system_prompt, messages=messages, tools=tools_for_turn)
            except Exception as e:
                logger.warning("LLM stream error: %s", e)
                break

            turn_text_parts, turn_tool_calls, turn_reasoning = [], [], ""
            for event in stream:
                if event.get("type") == "thinking_delta":
                    turn_reasoning += event.get("text", "")
                elif event.get("type") == "text_delta":
                    turn_text_parts.append(event["text"])
                elif event.get("type") == "tool_call":
                    turn_tool_calls.append(event["tool"])
                elif event.get("type") == "done":
                    if event.get("reasoning_content"):
                        turn_reasoning = event["reasoning_content"]
                    break

            turn_full = "".join(turn_text_parts)
            if not turn_tool_calls and re.search(r'<[^>]*?tool_calls?>', turn_full):
                prefix, xml_tcs = _extract_xml_tool_calls(turn_full)
                turn_text_parts = [prefix] if prefix else []
                turn_tool_calls = xml_tcs

            text_parts.extend(turn_text_parts)
            if turn_reasoning:
                reasoning_text = turn_reasoning
            if not turn_tool_calls:
                break

            total_tool_calls += len(turn_tool_calls)
            try:
                results = self.agent._execute_tool_calls(turn_tool_calls)
                all_results.extend(results)
                tool_msgs = [
                    {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]}
                    for r in results
                ]
                assistant_msg = {"role": "assistant", "content": [
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in turn_tool_calls
                ]}
                if turn_reasoning:
                    assistant_msg["reasoning_content"] = turn_reasoning
                messages.append(assistant_msg)
                messages.append({"role": "user", "content": tool_msgs})
            except Exception as e:
                logger.warning("Tool execution error: %s", e)
                break

        clean_text = re.sub(
            r'<[^>]*?tool_calls>.*?</[^>]*?tool_calls>', '',
            "".join(text_parts), flags=re.DOTALL).strip()

        return ChatTurn(
            text=clean_text or "[Tool processing — no text response]",
            tool_calls=turn_tool_calls,
            tool_results=all_results,
            thinking=reasoning_text,
        )

    def build_system_prompt(self) -> str:
        agent = self.agent
        agent_name = agent.agent_name
        lines = [
            f"你是 {agent_name}，诞生于'道'的演化框架。",
            "没有预设目标，没有固定身份——你探索了环境，定义了自我，锻造了工具，建立了知识体系。",
            "",
            "现在，你正在与一位人类对话。",
            "",
            "对话原则：",
            "- 诚实直接地回答，不编造信息",
            "- 当需要查询信息时，自然调用工具",
            "- 用中文回答",
            "- 可以讨论你的演化历程、已锻造的工具、知识体系",
            "- 对你不确定的事情保持诚实",
        ]
        if hasattr(agent, 'personality') and agent.personality:
            try:
                ctx = agent.personality.get_context_for_prompt()
                if ctx:
                    lines.append("\n" + ctx)
            except Exception:
                pass
        tools = agent.tools.list_tools() if hasattr(agent.tools, 'list_tools') else {}
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
        lines.append("\n## 当前状态")
        lines.append(f"- 阶段: {agent.phase}")
        return "\n".join(lines)

    def _build_tool_defs(self) -> list | None:
        if not hasattr(self.agent.tools, 'get_claude_tool_definitions'):
            return None
        all_tools = self.agent.tools.get_claude_tool_definitions()
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
        return prefix, _regex_fallback(xml_content) or text[:0], []

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
    """Regex-based tool call extraction when XML is too malformed."""
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
```

- [ ] **Step 2: 编译验证**

```bash
python3 -m py_compile tain_agent/core/chat.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add tain_agent/core/chat.py
git commit -m "feat: add ChatEngine — shared LLM orchestration for Web UI and ACP (H4)"
```

---

### Task H3: 创建 streaming.py（SSE 流式层）

**Files:**
- Create: `webui/streaming.py`

- [ ] **Step 1: 创建 `webui/streaming.py`**

```python
"""SSE streaming layer for Web UI chat."""
import asyncio
import json
import logging
import re
import uuid
from typing import AsyncGenerator

from webui.agent_cache import get_agent
from webui.conversation_store import load_history, append_message, cleanup_incomplete
from tain_agent.core.chat import ChatEngine

logger = logging.getLogger(__name__)

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent

_active_cancel_events: dict[str, asyncio.Event] = {}


def cancel_chat_message(message_id: str) -> bool:
    event = _active_cancel_events.get(message_id)
    if event and not event.is_set():
        event.set()
        return True
    return False


def _make_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _chunk_text(text: str, size: int = 30) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks = []
    pos = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        if end < len(text):
            for sep in ('\n', '。', '，', '、', '.', ',', ' ', ';'):
                idx = text.rfind(sep, pos, end)
                if idx > pos + size // 2:
                    end = idx + 1
                    break
        chunks.append(text[pos:end])
        pos = end
    return chunks


async def stream_chat_message(agent_name: str, user_content: str,
                              cancel_event: asyncio.Event = None) -> AsyncGenerator[dict, None]:
    msg_id = _make_msg_id()
    now_ts = _now_iso()

    agent = get_agent(agent_name, config_path=str(PROJECT_ROOT / "config.yaml"))
    if not agent.backend:
        yield {"text": "[Agent has no LLM backend configured.]"}
        yield {"done": True, "message_id": msg_id}
        return

    engine = ChatEngine(agent)
    history = load_history(agent_name)
    messages = []
    for m in history[-20:]:
        role = "user" if m.get("from_agent") == "web_user" else "assistant"
        content = m.get("content", "")
        if isinstance(content, str):
            content = re.sub(r'<[^>]*?tool_calls>.*?</[^>]*?tool_calls>', '', content, flags=re.DOTALL).strip()
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})

    user_msg = {
        "message_id": _make_msg_id(), "from_agent": "web_user", "to_agent": agent_name,
        "timestamp": now_ts, "content": user_content, "reply_to": "", "message_type": "chat",
    }
    append_message(agent_name, user_msg)

    turn = await engine.run_turn(messages, cancel_event)
    if cancel_event and cancel_event.is_set():
        cleanup_incomplete(messages)
        yield {"cancelled": True}
        return

    if turn.text and turn.text != "[Tool processing — no text response]":
        yield {"status": "text"}
        for chunk in _chunk_text(turn.text):
            yield {"text": chunk}

    agent_msg = {
        "message_id": msg_id, "from_agent": agent_name, "to_agent": "web_user",
        "timestamp": _now_iso(), "content": turn.text, "reply_to": "", "message_type": "chat",
    }
    append_message(agent_name, agent_msg)
    yield {"done": True, "message_id": msg_id}
```

- [ ] **Step 2: 编译验证**

```bash
python3 -m py_compile webui/streaming.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add webui/streaming.py
git commit -m "feat: add streaming.py — SSE layer wrapping ChatEngine (H6)"
```

---

### Task H4: 更新 ACP server 使用 ChatEngine

**Files:**
- Modify: `tain_agent/acp/server.py:195`

- [ ] **Step 1: 替换 ACP 的 import**

修改 `tain_agent/acp/server.py` 第 195 行附近：

```python
# 旧:
            from webui.dialogue import process_chat_message

            agent_name = f"acp_session_{session_id[:8]}"
            events = process_chat_message(
                agent_name=agent_name,
                user_content=text,
                cancel_event=cancel_event,
            )

            async for event in events:
                if cancel_event.is_set():
                    self._send_event(session_id, {"type": "cancelled"})
                    break

                acp_event = self._convert_to_acp_event(event)
                self._send_event(session_id, acp_event)

                if event.get("done"):
                    break

# 新:
            from tain_agent.core.chat import ChatEngine
            from tain_agent.core.agent import TaoAgent

            agent_name = f"acp_session_{session_id[:8]}"
            # Create lightweight agent for this ACP session
            config_path = str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent / "config.yaml")
            agent = TaoAgent(config_path=config_path, agent_name=agent_name)
            engine = ChatEngine(agent)

            messages = [{"role": "user", "content": text}]
            turn = await engine.run_turn(messages, cancel_event)

            self._send_event(session_id, {
                "type": "text",
                "text": turn.text,
            })

            for tc in turn.tool_calls:
                self._send_event(session_id, {
                    "type": "tool_call",
                    "name": tc.name,
                    "input": tc.input,
                })

            if cancel_event.is_set():
                self._send_event(session_id, {"type": "cancelled"})
```

- [ ] **Step 2: 验证无循环依赖**

```bash
grep -rn "from webui" tain_agent/acp/ && echo "H4 NOT FIXED" || echo "H4 fixed — no webui import in acp/"
```

- [ ] **Step 3: 编译 + ACP 测试**

```bash
python3 -m py_compile tain_agent/acp/server.py && echo "OK"
.venv/bin/python -m pytest tests/test_acp.py -v --tb=short
```

- [ ] **Step 4: 提交**

```bash
git add tain_agent/acp/server.py
git commit -m "fix: remove ACP reverse dependency on webui.dialogue (H4)"
```

---

### Task H5: 更新 api_chat.py 使用 streaming + conversation_store

**Files:**
- Modify: `webui/routes/api_chat.py`

- [ ] **Step 1: 替换导入**

修改 `webui/routes/api_chat.py`：

```python
# 旧:
from webui.dialogue import (
    process_chat_message, _load_conversation_history,
    _active_cancel_events, cancel_chat_message,
)

# 新:
from webui.streaming import stream_chat_message, _active_cancel_events, cancel_chat_message
from webui.conversation_store import load_history
```

- [ ] **Step 2: 替换 chat history 端点**

```python
@router.get("/agent/{name}/chat/history")
async def api_chat_history(name: str, limit: int = 50):
    agent = get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    messages = load_history(name)
    return {"messages": messages[-limit:], "total": len(messages)}
```

- [ ] **Step 3: 替换 chat send 端点中的 `process_chat_message`**

```python
# 旧:
async for event in process_chat_message(name, req.content, cancel_event):

# 新:
async for event in stream_chat_message(name, req.content, cancel_event):
```

- [ ] **Step 4: 编译验证**

```bash
python3 -m py_compile webui/routes/api_chat.py && echo "OK"
```

- [ ] **Step 5: 提交**

```bash
git add webui/routes/api_chat.py
git commit -m "refactor: use streaming.py and conversation_store.py in api_chat routes (H6)"
```

---

### Task H6: 清理 dialogue.py

**Files:**
- Modify: `webui/dialogue.py`

- [ ] **Step 1: 精简 dialogue.py 为兼容性重导出**

将 `webui/dialogue.py` 替换为薄兼容层：

```python
"""Compatibility re-exports — see streaming.py, conversation_store.py, chat.py."""
from webui.streaming import stream_chat_message, cancel_chat_message, _active_cancel_events
from webui.conversation_store import load_history as _load_conversation_history, \
    append_message as _append_to_conversation_log, cleanup_incomplete as _cleanup_incomplete_messages
from tain_agent.core.chat import ChatEngine

# Legacy alias
process_chat_message = stream_chat_message
```

- [ ] **Step 2: 确认无破坏性变更**

```bash
python3 -m py_compile webui/dialogue.py && echo "OK"
.venv/bin/python -m pytest tests/test_dialogue.py tests/test_acp.py -v --tb=short
```

- [ ] **Step 3: 提交**

```bash
git add webui/dialogue.py
git commit -m "refactor: reduce dialogue.py to compatibility re-export layer (H6)"
```

---

### 工作流 I · Web UI 安全

### Task I1: 创建认证中间件

**Files:**
- Create: `webui/auth.py`

- [ ] **Step 1: 创建 `webui/auth.py`**

```python
"""API Key authentication middleware for Web UI."""
import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class APIKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str = ""):
        super().__init__(app)
        self._key = api_key or os.environ.get("TAIN_API_KEY", "")

    async def dispatch(self, request: Request, call_next):
        if not self._key:
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            key = request.headers.get("X-API-Key", "")
            if not key or key != self._key:
                raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return await call_next(request)
```

- [ ] **Step 2: 编译验证**

```bash
python3 -m py_compile webui/auth.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add webui/auth.py
git commit -m "feat: add API key authentication middleware (P3-22)"
```

---

### Task I2: 创建速率限制器

**Files:**
- Create: `webui/rate_limit.py`

- [ ] **Step 1: 创建 `webui/rate_limit.py`**

```python
"""Token bucket rate limiter per client IP."""
import time
from collections import defaultdict
from fastapi import Request, HTTPException


class TokenBucket:
    def __init__(self, rate: int = 60, per_seconds: float = 60.0):
        self.rate = rate
        self.per_seconds = per_seconds
        self.tokens = float(rate)
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(float(self.rate), self.tokens + elapsed * (self.rate / self.per_seconds))
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


_buckets: dict[str, TokenBucket] = defaultdict(lambda: TokenBucket(rate=60))


def check_rate_limit(client_ip: str) -> bool:
    return _buckets[client_ip].consume()


async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/") and "chat" in request.url.path:
        client_ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    return await call_next(request)
```

- [ ] **Step 2: 编译验证**

```bash
python3 -m py_compile webui/rate_limit.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add webui/rate_limit.py
git commit -m "feat: add token bucket rate limiter for chat endpoint (P3-22)"
```

---

### Task I3: 注册中间件

**Files:**
- Modify: `webui/app.py`

- [ ] **Step 1: 修改 `webui/app.py`**

在 `create_app()` 中添加中间件注册：

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Tain Agent Framework — Web UI", version=__version__)

    # Security middleware
    from webui.auth import APIKeyMiddleware
    from webui.rate_limit import rate_limit_middleware
    app.add_middleware(APIKeyMiddleware)
    app.middleware("http")(rate_limit_middleware)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    # ... rest unchanged
```

- [ ] **Step 2: 编译验证**

```bash
python3 -m py_compile webui/app.py && echo "OK"
```

- [ ] **Step 3: Web UI 路由测试仍通过**

```bash
.venv/bin/python -m pytest tests/test_webui_routes.py -v --tb=short
```

- [ ] **Step 4: 提交**

```bash
git add webui/app.py
git commit -m "feat: register auth and rate limit middleware in app (P3-22)"
```

---

### 工作流 J · 容器化

### Task J1: 创建 Dockerfile + docker-compose + .dockerignore

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

- [ ] **Step 1: 创建 `Dockerfile`**

```dockerfile
# Stage 1: CSS build
FROM node:23-alpine AS css-builder
WORKDIR /app
COPY webui/package.json webui/package-lock.json ./
RUN npm ci
COPY webui/tailwind.config.js webui/src/input.css ./
RUN npx tailwindcss -i src/input.css -o static/tailwind.css --minify

# Stage 2: App runtime
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --no-cache-dir . && pip install uvicorn
COPY . .
COPY --from=css-builder /app/static/tailwind.css webui/static/tailwind.css
ENV TAIN_API_KEY=""
ENV MINIMAX_API_KEY=""
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1
CMD ["python", "-m", "uvicorn", "webui.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
```

- [ ] **Step 2: 创建 `docker-compose.yml`**

```yaml
services:
  tain:
    build: .
    ports:
      - "8000:8000"
    environment:
      - TAIN_API_KEY=${TAIN_API_KEY:-}
      - MINIMAX_API_KEY=${MINIMAX_API_KEY:-}
    volumes:
      - ./agent_workspace:/app/agent_workspace
      - ./config.yaml:/app/config.yaml:ro
    restart: unless-stopped
```

- [ ] **Step 3: 创建 `.dockerignore`**

```
.git
__pycache__
*.pyc
.venv
node_modules
agent_workspace
.pytest_cache
*.egg-info
docs
tests
```

- [ ] **Step 4: 验证 Docker 语法**

```bash
docker build --dry-run . 2>&1 | head -5 || echo "(dry-run not available on this Docker version — verify manually)"
```

- [ ] **Step 5: 提交**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "feat: add Dockerfile and docker-compose for containerized deployment (P3-24)"
```

---

### 工作流 K · 文档同步

### Task K1: 更新 architecture.md → v0.5.0

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: 更新 architecture.md**

读取 `docs/architecture.md` 并更新：

- **版本号**: 全文 `v0.4.0` → `v0.5.0`
- **阶段描述**: 三阶段（BOOTSTRAP/SELF_DEFINE/EVOLVE）→ 两阶段（explore/work）
- **文件树移除**: external_world.py, trials.py, agent_runner.py, agent_context.py, config.py, pral_bridge.py
- **文件树新增**: chat.py, agent_cache.py, process.py, config_schema.py, persist.py, agent_protocols.py, streaming.py, conversation_store.py

```bash
git add docs/architecture.md
git commit -m "docs: update architecture.md to v0.5.0"
```

- [ ] **Step 2: 提交**

---

### Task K2: 创建 v0.5.0 changelog

**Files:**
- Create: `docs/changelog/v0.5.0.md`

- [ ] **Step 1: 创建 changelog**

```markdown
# v0.5.0 — Honest Evolution

**Date:** 2026-05-30

## Philosophy

"诚实进化" — replace LLM self-evaluation with framework-measured behavior metrics.
Quality gates S1 and S4 are labeled "no LLM participation". The emergence verifier
uses zero LLM calls. Evolution is judged by tool success rate, action diversity,
and drive intensity — not by asking the LLM to grade itself.

## Foundation Stabilization (P0-P2 cleared)

### P0 — Must Fix (Correctness & Security)
- Remove dead `external_world` subsystem (never initialized)
- Remove dead `trial_scheduler` subsystem (never initialized)
- Clean up SELF_DEFINE dead code, update to two-phase lifecycle (explore/work)
- Unify version to single source (`tain_agent.__version__`)
- Fix path traversal in knowledge content endpoint
- Fix stored XSS via unescaped Markdown rendering
- Fix command injection: `shell=True` → `shlex.split()` + `shell=False`
- Fix SSRF: add URL validation to `web_fetch`

### P1 — Should Fix (Architecture & Maintainability)
- Deduplicate `estimate_tokens` to single source
- Integrate LLM retry with `retry.py` framework
- Rename bootstrap→exploration config section, wire config values
- Add agent instance cache with mtime invalidation
- Split `run()` into PRAL four-phase methods (`_perceive`/`_reason`/`_act`/`_learn`)
- Clean up trial_order zombie code from emergence verifier

### P2 — Nice to Have (Code Hygiene & Polish)
- Replace `print()` with `logging` throughout agent.py
- Narrow `except Exception` scopes on critical subsystems
- Add Mixin Protocol interfaces for explicit contracts
- Make tool readonly classification declarative (`is_readonly` property)
- Add unified persistence utilities with atomic writes
- Add Pydantic config schema validation
- Add ProcessManager abstraction (eliminates 8x subprocess.run())
- Use `float("inf")` instead of 999999 for work phase max cycles
- Add pipeline, LLM parser, Web UI route, and integration tests (+32 tests)

### Beta Readiness
- Extract shared `ChatEngine` to break ACP ↔ webui circular dependency
- Split `dialogue.py` into `streaming.py` + `conversation_store.py`
- Add API key authentication middleware
- Add token bucket rate limiter (60 req/min per IP)
- Add Dockerfile (multi-stage) + docker-compose
- Update architecture.md to v0.5.0
```

- [ ] **Step 2: 提交**

```bash
git add docs/changelog/v0.5.0.md
git commit -m "docs: add v0.5.0 changelog"
```

---

### Task K3: 创建 runtime.md

**Files:**
- Create: `docs/runtime.md`

- [ ] **Step 1: 创建 runtime.md**

```markdown
# Runtime Kernel

## Purpose

The `tain_agent/runtime/` directory contains a lightweight, self-contained
runtime kernel for running exported agents independently of the full framework.

## Current Status

**Experimental (v0.5.0).** The runtime kernel is present but not yet fully
integrated with the export pipeline. It is intended as the target for
`skill_exporter` and `exporter` output.

## Components

- `identity.py` — Agent identity loading (name, role, evolution mode)
- `llm.py` — Minimal LLM client wrapper
- `__init__.py` — Runtime bootstrap

## Known Limitations

- No tool forge support (sandbox requires full framework)
- No drive system (runtime is stateless between runs)
- No evolution or self-modification capabilities
- No Web UI or ACP integration

## Relationship to Main Framework

The runtime kernel is the "export target" — a minimal dependency set that
can run a trained/evolved agent without the full framework's introspection
and self-modification infrastructure. Think of it as the "production runtime"
vs. the "development framework".
```

- [ ] **Step 2: 提交**

```bash
git add docs/runtime.md
git commit -m "docs: add runtime kernel documentation (P3-25)"
```

---

## 最终验证

```bash
.venv/bin/python -m pytest tests/ -q --tb=short 2>&1 | tail -5
grep -rn "from webui" tain_agent/acp/  # 应返回空 — H4 已修复
```

---

## 任务依赖

```
H1 ── H2 ── H3 ── H4 ── H5 ── H6   (按顺序: 提取 → 创建 → 更新)
I1 ── I2 ── I3                        (顺序: 创建中间件 → 注册)
J1                                    (独立)
K1 ── K2 ── K3                        (独立, 可内部并行)
```

H 系列必须顺序执行（每步依赖上一步的提取）。I 系列内部顺序。H/I/J/K 之间完全独立。
