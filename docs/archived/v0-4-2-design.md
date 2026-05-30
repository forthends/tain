# Tain Agent Framework v0.4.2 — 设计借鉴与优化方案

## 来源

深度分析 [MiniMax-AI/Mini-Agent](https://github.com/MiniMax-AI/Mini-Agent) v0.1.0（`.demo/Mini-Agent/`）的设计理念与实现细节，提取对 Tain 框架有借鉴价值的内容。

---

## Mini-Agent 架构概览

Mini-Agent 是 MiniMax 官方提供的基于 M2.5 模型构建 agent 的最佳实践演示项目，366 个文件中包含以下核心模块：

```
mini_agent/
├── agent.py              # 核心 agent 执行循环（max_steps + cancel_event）
├── cli.py                # prompt_toolkit 交互式 CLI（历史、自动补全、Esc 取消）
├── config.py             # Pydantic 配置模型（LLMConfig, AgentConfig, ToolsConfig）
├── retry.py              # 异步重试装饰器（指数退避）
├── logger.py             # 结构化 LLM 日志（request/response/tool_result → JSONL）
├── schema/
│   └── schema.py         # Message, ToolCall, LLMResponse, TokenUsage
├── llm/
│   ├── base.py           # 抽象基类 LLMClientBase
│   ├── llm_wrapper.py    # 统一接口 + MiniMax URL 自动后缀
│   ├── anthropic_client.py  # Extended thinking + tool_use
│   └── openai_client.py     # reasoning_content + function calling
├── tools/
│   ├── base.py           # Tool 基类，双格式输出（to_schema / to_openai_schema）
│   ├── file_tools.py     # ReadTool, WriteTool, EditTool（tiktoken 截断）
│   ├── bash_tool.py      # BashTool, BashOutputTool, BashKillTool
│   ├── note_tool.py      # SessionNoteTool + RecallNoteTool（跨会话持久化）
│   ├── skill_tool.py     # GetSkillTool（渐进式披露：元数据→完整内容）
│   ├── skill_loader.py   # SKILL.md 解析器
│   └── mcp_loader.py     # MCP 协议工具加载
├── skills/               # 15 个 Claude Skills（git submodule）
│   ├── document-skills/  # docx, pdf, pptx, xlsx
│   ├── algorithmic-art, canvas-design, theme-factory
│   ├── slack-gif-creator, webapp-testing
│   ├── mcp-builder, skill-creator, artifacts-builder
│   └── internal-comms, brand-guidelines
└── acp/                  # Agent Client Protocol（Zed 编辑器集成）
```

### 关键设计特点

| 特性 | 实现方式 |
|------|----------|
| LLM 抽象 | 统一的 `LLMClient` 封装 Anthropic/OpenAI，MiniMax 域名自动检测并追加 `/anthropic` 或 `/v1` |
| 执行循环 | 基于步骤的循环：LLM → thinking → 工具执行 → 结果反馈，可取消（`cancel_event`） |
| 上下文管理 | tiktoken 精确计数 + `_summarize_messages()` 自动压缩（保留用户消息，摘要执行过程） |
| 工具系统 | `Tool` 基类 + `ToolResult`，双格式输出（Anthropic `to_schema()` / OpenAI `to_openai_schema()`） |
| 会话记忆 | `SessionNoteTool` + `RecallNoteTool`，延迟初始化，跨会话持久化 |
| 技能系统 | 渐进式披露：元数据注入系统提示词（Level 1）→ 完整内容按需加载（Level 2） |
| 重试机制 | 指数退避 + `RetryExhaustedError` + 回调函数通知 |
| 日志 | 每次 LLM 调用和工具执行的完整 JSONL 日志 |
| CLI | prompt_toolkit 交互式体验：历史搜索、自动补全、自动建议、Esc 取消 |

---

## Tain 框架现状 vs Mini-Agent 差距分析

### 1. LLM 重试机制 — Tain 缺失

**Tain 现状**：`tain_agent/core/llm.py` 和 `webui/dialogue.py` 中的 LLM 调用没有任何重试逻辑。网络波动、API 限流、临时服务不可用都会直接导致 agent 崩溃并返回错误。

**Mini-Agent 做法**：
- 独立的 `retry.py` 模块，`async_retry` 装饰器
- 指数退避：`delay = initial_delay × (exponential_base ^ attempt)`
- 可配置：`max_retries`, `initial_delay`, `max_delay`, `retryable_exceptions`
- `RetryExhaustedError` 携带 `last_exception` 和 `attempts` 用于调试
- 回调机制 `on_retry` 通知上层（CLI 显示重试进度）

```python
# Mini-Agent 重试核心逻辑
class RetryConfig:
    enabled: bool = True
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0

def calculate_delay(self, attempt: int) -> float:
    delay = self.initial_delay * (self.exponential_base ** attempt)
    return min(delay, self.max_delay)
```

**建议方案**：
- 在 `tain_agent/core/` 下新增 `retry.py`
- `config.yaml` 中暴露 `llm.retry` 配置项
- LLM 后端 `create_message()` 和 `stream_message()` 统一应用重试

**config.yaml 新增字段**：
```yaml
llm:
  # ... existing fields ...
  retry:
    enabled: true
    max_retries: 3
    initial_delay: 1.0
    max_delay: 30.0
    exponential_base: 2.0
```

---

### 2. Token 感知上下文管理 — Tain 使用固定窗口

**Tain 现状**：`ConversationManager` 使用 `keep_first_and_last(8)` 做固定消息数量截断，完全不了解实际 token 消耗。当工具返回大量文本（如 `read_file` 读取数千行、`web_search` 返回长结果）时，单条消息就可能超出模型上下文限制，导致 API 调用失败。

**Mini-Agent 做法**：
- `_estimate_tokens()` 使用 `tiktoken`（`cl100k_base` 编码器）对完整消息历史做精确 token 计数
- 同时检查本地估算和 API 报告的 `total_tokens`
- `_summarize_messages()` 触发条件：`estimated_tokens > token_limit OR api_total_tokens > token_limit`
- 摘要策略：
  - 保留 system prompt 和所有 user 消息（用户意图不丢失）
  - 对每个 user-user 之间的执行过程生成摘要
  - 调用 LLM 生成结构化摘要（聚焦完成的任务、调用的工具、关键发现）
  - 跳过连续摘要以避免无限循环（`_skip_next_token_check`）

```python
# Mini-Agent 摘要策略伪代码
async def _summarize_messages(self):
    estimated = self._estimate_tokens()
    if estimated <= self.token_limit and self.api_total_tokens <= self.token_limit:
        return  # 无需摘要

    new_messages = [self.messages[0]]  # 保留 system prompt
    for each user message:
        new_messages.append(user_message)  # 保留用户意图
        execution_msgs = messages_between_users
        if execution_msgs:
            summary = await self._create_summary(execution_msgs)
            new_messages.append(summary)  # 压缩执行过程
    self.messages = new_messages
```

**建议方案**：
- 为 `ConversationManager` 添加 `estimate_tokens()` 方法
- 添加 `token_limit` 配置（默认 80000）
- 实现 `summarize()` 方法，在触发阈值时调用 LLM 压缩历史
- 保留"安全边界"逻辑（`_find_safe_boundary`），确保 tool_use/tool_result 不分离
- tiktoken 作为可选依赖（`pip install tiktoken`），不可用时回退到字符估算（2.5 chars/token）

---

### 3. 结构化 LLM 日志 — Tain 缺失

**Tain 现状**：`DecisionLog` 记录 agent 决策（context/options/reasoning/outcome），但没有记录原始 LLM 请求和响应。调试 LLM 调用问题（如 token 超限、工具调用格式错误、thinking 丢失）只能依赖外部抓包或 print 日志。

**Mini-Agent 做法**：
- `AgentLogger` 为每次 agent 运行创建独立的 JSONL 日志文件
- 记录所有关键事件：

```python
# Mini-Agent 日志结构
self.logger.log_request(messages=self.messages, tools=tool_list)
self.logger.log_response(content=..., thinking=..., tool_calls=..., finish_reason=...)
self.logger.log_tool_result(tool_name=..., arguments=..., result_success=..., result_content=...)
```

- 日志存储在 `~/.mini-agent/log/` 下，按时间戳命名
- `/log` 命令在 CLI 中直接查看

**建议方案**：
- 在 `DecisionLog` 旁新增 `LLMLogger`（或扩展现有 logger）
- 记录每次 LLM 调用的：时间戳、模型、provider、消息数量、估算 token 数、工具列表、响应内容（截断）、thinking 内容、token 用量、延迟
- 记录每次工具执行的：工具名称、参数（截断）、成功/失败、结果（截断）、延迟
- 存储位置：`agent_workspace/<name>/logs/llm_calls.jsonl`
- 在 Web UI 的 Agent 详情页增加"LLM 调用"标签页查看日志

---

### 4. Agent 主动记忆工具 — Tain 部分缺失

**Tain 现状**：`SessionMemory`（`tain_agent/core/session_memory.py`）记录对话会话摘要（用户姓名、会话起止时间、消息数、主题），但 agent 在自主演化循环中无法**主动**调用工具保存关键发现。Memory 系统（`tain_agent/core/memory.py`）有 `remember()` 方法，但未暴露为 agent 可调用的工具。

**Mini-Agent 做法**：
- `SessionNoteTool`（`record_note`）：agent 主动写入 `{timestamp, category, content}` 到 `.agent_memory.json`
- `RecallNoteTool`（`recall_notes`）：按可选类别筛选检索所有笔记
- 延迟初始化：文件在第一次 `record_note` 调用时才创建
- 简单但有效：纯 JSON 文件存储，无需外部数据库

```python
# Mini-Agent 笔记结构
note = {
    "timestamp": "2026-05-26T10:30:00",
    "category": "user_preference",
    "content": "User prefers concise responses in Chinese"
}
```

**建议方案**：
- 在 primal tools 中添加 `remember_note` 和 `recall_notes` 两个工具
- 复用现有 Memory 系统的 `remember()` 和 `recall()` 接口
- agent 可在演化过程中主动记录：新发现的模式、重要环境变化、与其他 agent 的交互、自修改决策
- 演化循环中在每个 evolve 阶段结束时提示 agent 保存关键发现

---

### 5. Web Chat 执行取消支持 — Tain 缺失

**Tain 现状**：`process_chat_message` 中的 tool chain 执行最多 5 轮 × 每轮可能 5 分钟 = 最长 5 分钟无响应。用户无法中途取消。前端只有发送按钮，没有停止按钮。

**Mini-Agent 做法**：
- `cancel_event: asyncio.Event` 在 agent 对象上
- 每步开始前和每个工具执行后检查 `_check_cancelled()`
- 取消后调用 `_cleanup_incomplete_messages()` 清理不完整的消息（避免下轮 API 2013 错误）
- CLI 中用独立线程监听 Esc 键
- 跨平台实现（Windows `msvcrt` / Unix `termios + select`）

```python
# Mini-Agent 取消流程
async def run(self, cancel_event=None):
    self.cancel_event = cancel_event
    while step < max_steps:
        if self._check_cancelled():
            self._cleanup_incomplete_messages()
            return "Task cancelled by user."
        # ... LLM call ...
        if self._check_cancelled():
            # Clean up before tool execution
            return "Task cancelled by user."
        # ... tool execution ...
```

**建议方案**：
- 在 `process_chat_message` 外层添加 `asyncio.Event` 作为取消信号
- 每轮循环开始前检查取消信号
- API 路由层存储活跃的 cancel events，通过 `message_id` 索引
- 新增 `POST /api/agent/{name}/chat/cancel?message_id=...` 端点
- 前端：流式传输中发送按钮变为"停止"按钮

---

## 实施计划

### 阶段一：稳定性增强（v0.4.3）

| 优先级 | 改动 | 文件 | 影响范围 |
|--------|------|------|----------|
| P0 | LLM 重试机制 | 新增 `tain_agent/core/retry.py` | `llm.py`, `config.yaml` |
| P1 | Token 感知上下文管理 | `conversation.py` | `agent.py`, `dialogue.py` |

### 阶段二：可观测性（v0.4.4）

| 优先级 | 改动 | 文件 | 影响范围 |
|--------|------|------|----------|
| P2 | LLM 调用日志 | 新增 `tain_agent/core/llm_logger.py` | `agent.py`, Web UI |
| P3 | Web Chat 取消支持 | `dialogue.py`, `api_chat.py`, `chat.html` | 前端体验 |

### 阶段三：Agent 能力增强（v0.4.5）

| 优先级 | 改动 | 文件 | 影响范围 |
|--------|------|------|----------|
| P4 | Agent 记忆工具 | `primal.py`, `session_memory.py` | 演化循环 |

---

## 新增依赖评估

| 依赖 | 用途 | 是否必需 | 体积 |
|------|------|----------|------|
| `tiktoken` | 精确 token 计数 | 否（有字符估算回退） | ~1MB |

所有其他改进均使用现有依赖实现，无需新增包。

---

## 风险与注意事项

1. **上下文摘要可能丢失细节**：自动摘要是不可逆的信息压缩。设置保守的 `token_limit`（80k）和只在确实超限时触发，减少不必要的信息损失。
2. **重试可能延长故障时间**：对真正的永久性错误（如 API key 无效）不应重试。`retryable_exceptions` 应限定为网络错误和 5xx 响应。
3. **取消后的消息一致性**：必须在取消点清理不完整的 assistant/tool_result 消息对，否则下一轮 API 调用会因孤儿 tool_result 报错。Mini-Agent 的 `_cleanup_incomplete_messages()` 逻辑已验证可靠。
4. **tiktoken 的计算偏差**：不同模型的 tokenizer 略有差异。`cl100k_base` 对大多数现代模型是合理的近似（±5%），但不应作为唯一的触发条件——同时检查 API 报告的 `total_tokens`。

---

# 附：Mini-Agent 作为 Agent 进化产物的参照

将 Mini-Agent 视为 Tain agent 经过充分演化后可能达到的"成熟形态"，以下从项目结构、Skills、Tools、协议集成四个维度分析可借鉴的内容。

---

## 一、项目结构：agent 最终自组织架构的参照

Mini-Agent 的目录结构不是人为预先设计的，而是围绕"一个能完成复杂任务的 agent 需要什么"自然生长出来的。这恰好也是 Tain agent 自主演化的目标方向。

### 结构对比

| 层级 | Mini-Agent（成熟态） | Tain 现状（演化中） | 差距 |
|------|---------------------|-------------------|------|
| LLM 抽象 | `llm/` — 独立目录，base + anthropic + openai + wrapper | `core/llm.py` — 单文件内嵌多种后端 | Tain 的 LLM 模块随 provider 增多会膨胀 |
| 工具系统 | `tools/` — 每个工具独立文件，base 定义接口契约 | `tools/registry.py` + `primal.py` — 注册表模式 | Tain 缺少工具接口契约（`Tool` 基类） |
| 技能系统 | `skills/` — 15 个自包含技能包（每个有 SKILL.md + scripts/ + references/ + assets/） | `tools/forged/` — 12 个锻造工具，结构不统一 | Tain 的锻造工具缺少自描述格式和目录约定 |
| 数据模型 | `schema/` — 独立目录，Pydantic 模型定义 | 分散在 `llm.py`（`ToolCall`, `LLMResponse`）和 `conversation.py` 中 | Tain 缺少统一的 schema 层 |
| 配置 | `config/` — 模板 + 示例 + 多级搜索路径 | `config.yaml` — 单一配置文件 | Tain 缺少多环境配置支持 |
| 日志 | `logger.py` — 结构化分段日志 | `decision_log.py` — 仅记录决策 | Tain 缺少 LLM/工具调用日志 |
| 协议集成 | `acp/` — Agent Client Protocol 服务端 | 无 | Tain agent 无法被外部系统标准化调用 |

### 借鉴意义

Tain agent 的 `ToolForge` 目前只关注工具函数本身，缺少对 agent **整体自组织架构**的引导。Mini-Agent 的结构提示了三件事：

1. **Forge 的进化方向**：不只是锻造工具函数，而是锻造 **自包含的能力包**（skill package = 描述 + 脚本 + 参考资料 + 资产文件）。`export_as_skill` 工具已有雏形，需要明确的目标格式。

2. **Schema 独立化**：随着 agent 自主定义的数据结构增多，统一的 schema 层让 agent 能对自己的"思维模型"建立清晰的元认知。

3. **多级配置搜索**：agent 在演化中会产出自己的配置偏好（如偏好的工具组合、知识种子、驱动力权重）。多级搜索路径（工作空间 → 用户 → 系统）让 agent 的自我配置可移植、可共享。

---

## 二、Skills 目录：agent 自主能力的终极形态

### 15 个 Skills 分析

| 类别 | Skill | 复杂度 | 包含的 scripts/ 文件数 | Tain 对应 |
|------|-------|--------|----------------------|-----------|
| 文档操作 | docx, pdf, pptx, xlsx | 高 | 6-12 个 Python 脚本 | 无 |
| 创意设计 | algorithmic-art, canvas-design, theme-factory | 中 | 0-3 个 | 无 |
| 开发工具 | webapp-testing, mcp-builder, skill-creator | 高 | 1-3 个 | 部分（`regression_tester`） |
| 视觉表达 | slack-gif-creator | 高 | 12 个模板 + 7 个核心模块 | 无 |
| 规范约束 | brand-guidelines, internal-comms | 低 | 0 个 | 无 |
| 元技能 | artifacts-builder, template-skill | 低 | 0 个 | `export_as_skill` 接近 |

### SKILL.md 格式：锻造产物的目标规格

当前 Tain 的 `/forge` 命令产出的是单个 Python 函数文件，没有元数据、没有使用说明、没有依赖声明。Mini-Agent 的 SKILL.md 格式提供了一个**锻造成熟度模型**：

```
Level 1（当前 Tain）: 函数文件
    tool_function.py              ← 只有代码

Level 2（基础技能包）: 自描述函数
    tool_function.py + 文档块      ← 代码 + 描述

Level 3（完整技能包）: SKILL.md 格式
    skill-name/
    ├── SKILL.md                  ← 元数据 + 使用指南
    ├── scripts/                  ← 可执行代码
    ├── references/               ← 参考资料
    └── assets/                   ← 产出物模板
```

**建议**：将 SKILL.md 格式作为 `ToolForge` 和 `export_as_skill` 的**目标输出格式**。agent 在锻造工具时，不只是生成代码，还会自动生成配套的 SKILL.md 元数据文件。

### 渐进式披露：agent 知识管理的认知模式

Skills 的三级加载机制（元数据 → 完整内容 → 引用文件）不仅是工程优化，更是一种**认知模式**——agent 对自己拥有什么能力建立"索引"，按需加载细节。这个模式可以推广到 Tain agent 的所有知识领域：

| 领域 | Level 1（索引） | Level 2（内容） | Level 3（引用） |
|------|----------------|----------------|----------------|
| Skills | `get_skills_metadata_prompt()` | `get_skill(name)` | 读取 scripts/references |
| 知识条目 | 知识地图/标签索引 | 全量知识检索 | 关联知识图谱 |
| 工具 | `list_tools()` 返回名+描述 | `get_claude_tool_definitions()` | 工具的依赖/来源 |
| 对话记忆 | SessionMemory 摘要列表 | 完整会话记录 | 具体决策日志 |

---

## 三、Tools 目录：工具设计的模式语言

### 接口契约

Mini-Agent 的 `Tool` 基类定义了清晰的接口契约，所有工具都必须实现：

```python
class Tool:
    name: str            # 唯一标识
    description: str     # 自然语言描述（给 LLM 看）
    parameters: dict     # JSON Schema（给 API 看）
    execute(**kwargs)    # 异步执行（给框架调用）
    to_schema()          # Anthropic 格式
    to_openai_schema()   # OpenAI 格式
```

Tain 的 `ToolRegistry` 是**隐式契约**（`register(name, func, description, parameters)`），没有强制接口。当 agent 自主 `forge` 工具时，没有基类约束意味着生成质量不可控。

**建议**：提炼一个轻量 `Tool` 基类，`ToolForge` 生成的工具必须继承它。基类的 `to_schema()` / `to_openai_schema()` 自动生成，减少 agent 锻造工具时的格式错误。

### 工作空间隔离模式

Mini-Agent 所有文件工具接受 `workspace_dir` 参数，相对路径解析到此目录下：

```python
class ReadTool(Tool):
    def __init__(self, workspace_dir: str = "."):
        self.workspace_dir = Path(workspace_dir).absolute()

    async def execute(self, path: str, ...):
        if not file_path.is_absolute():
            file_path = self.workspace_dir / file_path
```

Tain 已在 `primal.py` 中实现了类似的 `_resolve_path()` 机制，但它是模块级全局变量，而非工具实例属性。Mini-Agent 的每个工具独立持有 `workspace_dir` 引用的方式更清晰，更适合 agent 在子工作空间中锻造工具的场景。

### 智能截断

Mini-Agent 的 `truncate_text_by_tokens()` 对大文件读取做**首尾保留 + 中间截断**：

```
[前 50% 内容 ...Content truncated: 120000 tokens -> ~32000 tokens limit... 后 50% 内容]
```

Tain 的文件读取工具当前没有截断。当 agent 读取自己的日志或知识库时，可能返回超长文本撑爆上下文。这个模式值得直接复用。

### 后台进程管理

`BashTool` + `BackgroundShellManager` 的组合让 agent 可以：
- 启动长时间运行的命令（如 `uv run server &`）
- 异步监控输出
- 增量读取新输出
- 按 ID 终止进程

Tain agent 在演化中需要运行测试、启动服务、执行批量操作——这些都是长时间任务。后台进程管理是一个缺失的基础能力。

### MCP 工具集成

`mcp_loader.py` 展示了 agent 如何**动态加载外部工具**：

1. 读取 `mcp.json` 配置文件
2. 为每个启用的 server 建立连接（stdio / SSE / HTTP）
3. 将远程工具包装为本地 `MCPTool` 实例
4. 统一通过 `tool.execute()` 调用

这对 Tain 的启示是：**agent 的演化不应局限于自己写代码**。一个成熟的 agent 应该能发现、连接、使用外部工具服务。MCP 集成可以作为 agent 的"感官扩展"——触达搜索引擎、知识图谱、记忆服务。

---

## 四、ACP 协议：agent 作为被嵌入的标准接口

Mini-Agent 的 `acp/server.py` 将 agent 包装为一个 **Agent Client Protocol 服务端**，通过 stdio 与外部客户端（如 Zed 编辑器）通信：

```
客户端（Zed） ←→ stdio ←→ ACP Server ←→ Agent.run()
```

核心流：
1. `initialize()` — 协商协议版本和能力
2. `newSession()` — 创建工作空间 + 初始化 agent
3. `prompt(user_text)` — 执行 agent 循环，流式返回 thinking/content/tool_calls
4. `cancel()` — 取消当前执行

Tain 目前有 `sub_agent.py` 实现 agent 间的调用，但没有标准化的外部协议接口。ACP 提供了一个思路：Tain agent 可以暴露 ACP 兼容接口，从而被任何支持 ACP 的编辑器/工具作为 AI 助手嵌入。

---

## 五、对实施计划的补充

基于以上分析，在原有三阶段计划基础上补充：

### 阶段三扩展：Agent 进化产物标准化（v0.4.5）

| 优先级 | 改动 | 说明 |
|--------|------|------|
| P4 | Agent 记忆工具 | 原计划保留 |
| P5 | Tool 基类提炼 | `tools/base.py`，统一 `name/description/parameters/execute/to_schema` 接口 |
| P6 | Forge 输出 SKILL.md 格式 | `export_as_skill` 产出符合 SKILL.md 规范的完整技能包 |
| P7 | forge 工具模板 | 基于 Mini-Agent 的 `ReadTool/WriteTool/EditTool` 设计模式，提供标准模板 |

### 阶段四：Agent 能力边界扩展（v0.5.0）

| 优先级 | 改动 | 说明 |
|--------|------|------|
| P8 | MCP 工具集成 | `tools/mcp_loader.py`，让 agent 能动态加载外部工具 |
| P9 | 后台进程管理 | `tools/bash_tool.py`，支持长时间命令的异步执行和输出监控 |
| P10 | ACP 协议支持 | `acp/server.py`，让 Tain agent 可被标准 ACP 客户端调用 |
| P11 | 多级配置搜索 | `config.py`，dev → user → package 三级搜索路径 |
| P12 | 大文件智能截断 | `utils/token_utils.py`，首尾保留 + 中间截断 |

---

## 六、Skill 移植可行性评估

Mini-Agent 的 15 个 Skills 中，以下可作为 Tain agent 的能力参考或直接移植：

| Skill | 移植难度 | 对 Tain agent 的价值 | 说明 |
|-------|---------|-------------------|------|
| pdf | 中 | 高 | 表单填写、内容提取、PDF 转图片——agent 处理文档的核心能力 |
| docx/pptx/xlsx | 中 | 高 | OOXML 操作——agent 生成报告/演示文稿 |
| webapp-testing | 低 | 高 | Playwright 自动化——agent 验证自己构建的 Web 应用 |
| skill-creator | 低 | 高 | 元技能——指导 agent 如何创建规范的能力包 |
| algorithmic-art | 低 | 中 | p5.js 生成艺术——展示 agent 的创造力 |
| slack-gif-creator | 中 | 中 | Python 动画生成——agent 表达能力的另一维度 |
| mcp-builder | 中 | 中 | 指导 agent 构建 MCP 服务——扩展 agent 的工具生态 |
| brand-guidelines | 低 | 低 | 设计规范约束——特定场景 |
| internal-comms | 低 | 低 | 内部沟通模板——特定场景 |
| theme-factory | 低 | 低 | 主题工厂——UI 美化 |

**建议策略**：不直接复制 skills 目录到 Tain，而是让 Tain agent 在演化中**自主发现对这些能力的需求**，然后通过 `ToolForge` 参照 Mini-Agent 的 SKILL.md 格式来构建自己的版本。Skills 目录作为"参考答案"而非"预设能力"。
