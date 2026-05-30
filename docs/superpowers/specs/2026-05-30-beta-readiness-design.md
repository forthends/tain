# Beta 就绪 (Beta Readiness) · 设计文档

**日期**: 2026-05-30  
**来源**: 项目深度审查报告（docs/evaluation-report.md）P3 项 + 架构 H4/H6  
**范围**: H4 + H6 + P3-22 + P3-24 + P3-25  
**目标**: 解决架构违规，Web UI 安全加固，容器化，文档同步

---

## 架构总览

四个独立工作流：

```
H. 对话层重构 ──── 解决 H4(ACP循环依赖) + H6(dialogue拆分)
I. Web UI 安全 ─── P3-22(认证+限流)
J. 容器化 ──────── P3-24(Docker)
K. 文档同步 ────── P3-25(architecture.md + changelog + runtime)
```

全部并行，互不依赖。

---

## 工作流 H · 对话层重构（H4 + H6）

### 现状问题

```
acp/server.py ──→ webui/dialogue.py ──→ tain_agent/core/agent.py
        ↑                                    │
        └────────────────────────────────────┘
```

`acp/server.py:195` 导入 `webui.dialogue.process_chat_message`，但 ACP 是 stdio JSON-RPC 协议，不需要 SSE 流式、cancel event、conversation store 等 Web 概念。

### 目标结构

```
                         tain_agent/core/chat.py
                        ┌─────────────────────────┐
acp/server.py ─────────┤                         ├──── webui/streaming.py
                        │ ChatEngine              │
                        │ run_turn()              │
                        │ _extract_xml_tool_calls │
                        │ _build_system_prompt    │
                        └─────────────────────────┘
                                     │
                                     ↓
                        tain_agent/core/agent.py
```

### 新增文件

**`tain_agent/core/chat.py`** — 共享聊天引擎，从 dialogue.py 提取：

```python
"""Chat Engine — LLM orchestration shared by Web UI and ACP."""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ChatTurn:
    text: str                       # clean response text (XML stripped)
    tool_calls: list[dict]          # [{name, input, id}]
    tool_results: list[dict]        # [{tool_use_id, content, tool_name}]
    thinking: str = ""              # thinking block content if any


class ChatEngine:
    """Shared engine: LLM call → parse → execute tools — no web/SSE knowledge."""

    def __init__(self, agent):
        self.agent = agent

    def build_system_prompt(self) -> str:
        """Build the system prompt for the agent."""
        # Extracted from dialogue.py:_build_system_prompt
        ...

    async def run_turn(self, messages: list[dict],
                       cancel_event: asyncio.Event = None) -> ChatTurn:
        """Run one chat turn: call LLM → parse XML tool calls → execute tools."""
        # Core loop extracted from dialogue.py:process_chat_message
        ...

    def _extract_xml_tool_calls(self, text: str) -> tuple[str, list]:
        """Strip and extract XML-format tool calls from LLM text response."""
        # Extracted from dialogue.py:_extract_xml_tool_calls (lines 105-170)
        ...

    def _extract_tool_calls_regex_fallback(self, xml_text: str) -> list:
        """Regex fallback for malformed XML tool calls."""
        # Extracted from dialogue.py:_extract_tool_calls_regex_fallback (lines 171-203)
        ...
```

**`webui/streaming.py`** — SSE 流式层，从 dialogue.py 提取：

```python
"""SSE streaming layer for Web UI chat."""
import asyncio
from .conversation_store import load_history, append_message


_active_cancel_events: dict[str, asyncio.Event] = {}


def cancel_chat_message(message_id: str) -> bool:
    """Signal cancellation for an active chat message."""
    ...


def _chunk_text(text: str, size: int = 30) -> list[str]:
    """Chunk text for streaming display."""
    ...


async def stream_chat_message(agent_name: str, user_content: str,
                              cancel_event: asyncio.Event = None):
    """Process a chat message and yield SSE events.

    Wraps ChatEngine.run_turn() with SSE event generation, cancellation
    support, and conversation history management.
    """
    from tain_agent.core.chat import ChatEngine
    from webui.agent_cache import get_agent

    agent = get_agent(agent_name, ...)
    engine = ChatEngine(agent)
    messages = load_history(agent_name)
    messages.append({"role": "user", "content": user_content})
    append_message(agent_name, ...)

    turn = await engine.run_turn(messages, cancel_event)
    # Yield SSE events: text chunks, tool_start, tool_done, done
    ...
```

**`webui/conversation_store.py`** — 对话持久化，从 dialogue.py 提取：

```python
"""Conversation history persistence (JSONL-based)."""
import json
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent / "agent_workspace"


def load_history(agent_name: str) -> list[dict]:
    """Load conversation history from web_user.jsonl."""
    # Extracted from dialogue.py:_load_conversation_history (lines 61-92)
    ...


def append_message(agent_name: str, message: dict) -> None:
    """Append a message to the conversation log."""
    # Extracted from dialogue.py:_append_to_conversation_log (lines 93-100)
    ...


def cleanup_incomplete_messages(messages: list[dict]) -> None:
    """Remove orphaned tool_calls from message list."""
    # Extracted from dialogue.py:_cleanup_incomplete_messages (lines 42-60)
    ...
```

### 修改文件

**`tain_agent/acp/server.py:195`**：

```python
# 旧:
from webui.dialogue import process_chat_message
events = process_chat_message(agent_name=..., user_content=..., cancel_event=...)

# 新:
from tain_agent.core.chat import ChatEngine
from tain_agent.core.agent_factory import AgentFactory

agent = ...  # create agent instance as needed
engine = ChatEngine(agent)
turn = await engine.run_turn(messages, cancel_event)
# Convert turn to ACP events
```

**`webui/routes/api_chat.py`**：

```python
# 旧:
from webui.dialogue import process_chat_message, cancel_chat_message

# 新:
from webui.streaming import stream_chat_message, cancel_chat_message
```

**`webui/dialogue.py`**：重构后变为空壳或删除（所有逻辑已迁移到上述三个文件）。

### 验证

- ACP 导入: `python3 -c "from tain_agent.core.chat import ChatEngine; print('OK')"`
- Web UI 导入: `python3 -c "from webui.streaming import stream_chat_message; print('OK')"`
- 无循环依赖: `grep -rn "from webui" tain_agent/acp/` 应返回空
- 测试: `.venv/bin/python -m pytest tests/test_dialogue.py tests/test_acp.py -v`

---

## 工作流 I · Web UI 安全（P3-22）

### I1. API Key 认证

新增 `webui/auth.py`：

```python
"""API Key authentication middleware for Web UI."""
import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Protect /api/* routes with X-API-Key header.

    Reads TAIN_API_KEY from environment. If not set, middleware is transparent
    (development mode — all requests pass through).
    """

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

### I2. 速率限制

新增 `webui/rate_limit.py`：

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
    """FastAPI middleware: rate-limit /api/agent/{name}/chat at 60 req/min per IP."""
    if request.url.path.startswith("/api/") and "chat" in request.url.path:
        client_ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    return await call_next(request)
```

### I3. 集成到 app.py

修改 `webui/app.py`：

```python
from webui.auth import APIKeyMiddleware
from webui.rate_limit import rate_limit_middleware

def create_app() -> FastAPI:
    app = FastAPI(...)
    app.add_middleware(APIKeyMiddleware)
    app.middleware("http")(rate_limit_middleware)
    ...
    return app
```

### 验证

```bash
# Auth: 无 key 应拒绝
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/agents

# Rate limit: 快速请求应触发 429
for i in $(seq 1 61); do curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/agent/test/chat -X POST -d '{"content":"hi"}'; done | tail -1
```

---

## 工作流 J · 容器化（P3-24）

### J1. Dockerfile

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

### J2. docker-compose.yml

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

### J3. `.dockerignore`

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

---

## 工作流 K · 文档同步（P3-25）

### K1. 更新 architecture.md

- 版本号：v0.4.0 → v0.5.0
- 阶段描述：三阶段 → 两阶段（explore/work）
- 文件树：移除（external_world.py、trials.py、agent_runner.py、agent_context.py、config.py、pral_bridge.py），新增（chat.py、agent_cache.py、process.py、config_schema.py、persist.py、agent_protocols.py）
- 架构图：更新为当前六层结构

### K2. 创建 docs/changelog/v0.5.0.md

覆盖：
- "诚实进化" 哲学转向
- 稳基迭代 P0-P2 清偿成果
- 安全修复（SSRF、XSS、命令注入、路径遍历）
- 模块变更清单

### K3. 创建 docs/runtime.md

- 独立运行时内核用途说明
- 当前状态（实验性）
- 与主框架的关系
- 已知限制

---

## 文件变更汇总

| 工作流 | 新增 | 修改 | 删除 |
|--------|------|------|------|
| H | 3 (`chat.py`, `streaming.py`, `conversation_store.py`) | 3 (`server.py`, `api_chat.py`, `dialogue.py`) | — |
| I | 2 (`auth.py`, `rate_limit.py`) | 1 (`app.py`) | — |
| J | 3 (`Dockerfile`, `docker-compose.yml`, `.dockerignore`) | — | — |
| K | 2 (`changelog/v0.5.0.md`, `runtime.md`) | 1 (`architecture.md`) | — |
| **合计** | **10** | **5** | **0** |

---

## 风险评估

| 风险 | 概率 | 缓解 |
|------|------|------|
| dialogue.py 拆分后 SSE 行为不一致 | 中 | 拆分前先运行现有测试锁定行为，拆分后逐测试对齐 |
| ACP 换用 ChatEngine 后事件格式不兼容 | 低 | ACP 已有 `_convert_to_acp_event` 转换层，只需调整上游 |
| Docker build 网络依赖问题 | 低 | 多阶段构建，Node.js 仅用于 CSS 编译阶段 |
| API key middleware 影响现有测试 | 低 | 未设 TAIN_API_KEY 时中间件透传，测试代码无需修改 |
