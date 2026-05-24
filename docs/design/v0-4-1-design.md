# Tain Agent Framework v0.4.1 — Web UI 设计文档

## 概述

为 Tain Agent Framework 增加 Web 管理界面，支持：
- 可视化查看所有 Agent 的状态、产物、工具、进化日志
- 在浏览器中与 Agent 实时对话
- Agent 生命周期管理（启动、停止、重启）
- 实时日志流

Web UI 是纯文件读取层，不修改 Agent 数据存储方式，不与 Agent 进程耦合。

---

## 技术选型

| 层面 | 选型 | 原因 |
|------|------|------|
| 后端框架 | **FastAPI** | 与框架同语言（Python），轻量，自动生成 API 文档，原生 SSE/WebSocket |
| 模板引擎 | **Jinja2** | FastAPI 内置，服务端渲染，零构建步骤 |
| 动态交互 | **HTMX** | 局部刷新、分页、筛选、Tab 切换，无需写 JS |
| 客户端状态 | **Alpine.js** | 下拉菜单、弹窗、开关等轻量 UI 状态管理 |
| 样式 | **Tailwind CSS (CDN)** | 快速构建整洁界面，无 CSS 文件，无构建步骤 |
| 实时推送 | **Server-Sent Events (SSE)** | 单向推送 Agent 输出日志 + 对话流式响应 |
| 图表 | **Chart.js (CDN)** | 进化指标可视化（按需加载） |

### 不选 SPA 的原因

管理界面不需要离线能力、路由懒加载或复杂状态管理。零构建步骤意味着更低维护成本和更少的依赖。

### 新增依赖

```
fastapi >= 0.100.0
uvicorn[standard] >= 0.23.0
```

仅两个包。Jinja2 随 FastAPI 捆绑安装。

---

## 启动方式

沿袭现有 CLI 体系，通过 `main.py` 新增参数启动：

```bash
# 默认 127.0.0.1:8000
python main.py --webui

# 自定义端口
python main.py --webui --port 3000

# 后台运行（复用现有 daemonize 机制）
python main.py --webui --daemon
```

`main.py` 中新增分支：

```python
if args.webui:
    from webui.app import create_app
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=args.port or 8000)
```

Web UI 是独立进程，通过读写 `agent_workspace/` 下的文件获取数据。对 Agent 的控制（启动/停止/重启）通过调用 `supervise_agent.py` 子进程完成。

---

## 架构

```
┌─────────────────────────────────────────────────┐
│                  Web Browser                     │
│  Tailwind CSS + HTMX + Alpine.js + SSE          │
└────────────────────┬────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────┐
│              FastAPI (webui/app.py)              │
│                                                  │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │  Routes  │  │  SSE Mgr  │  │  Dialogue     │  │
│  │ (pages + │  │ (log      │  │  Bridge       │  │
│  │  API)    │  │  stream)  │  │  (chat)       │  │
│  └────┬─────┘  └─────┬─────┘  └──────┬───────┘  │
│       │              │               │           │
│       │    ┌─────────▼──────────┐    │           │
│       │    │  supervise_agent   │    │           │
│       │    │  (start/stop/      │    │           │
│       │    │   restart agent)   │    │           │
│       │    └────────────────────┘    │           │
│       │                              │           │
└───────┼──────────────────────────────┼───────────┘
        │                              │
        ▼                              ▼
┌─────────────────────────────────────────────────┐
│              agent_workspace/ (Filesystem)       │
│                                                  │
│  _registry.json    ← Agent 列表 + 元数据          │
│  _messages/        ← Agent 间消息总线             │
│  <name>/state/     ← 人格、指标快照               │
│  <name>/forged_tools/  ← 锻造工具源码 + 元数据     │
│  <name>/logs/      ← 决策日志、演化血统、对话记录  │
│  <name>/knowledge/ ← 知识产物                     │
│  <name>/files/     ← Agent 创建的文件              │
└─────────────────────────────────────────────────┘
```

**关键设计原则**：

- Web UI **只读文件系统**，不直接修改 Agent 工作区（对话写入除外）
- Agent 控制（启动/停止）通过 `supervise_agent.py` 子进程操作
- 对话通过 Web UI 进程内加载 Agent 实例完成，不依赖 Agent 是否在运行

---

## 数据来源映射

所有数据从已有落盘文件读取，**零新增数据模型，零存储变更**。

| 页面/区域 | 需要的数据 | 数据来源 |
|-----------|-----------|---------|
| Dashboard Agent 卡片 | 名称、角色、版本、状态 | `_registry.json` + PID 文件检查 |
| Overview 标签 | 阶段、循环数、工具数、目标数 | `logs/memory.json` + 文件计数 |
| Personality 标签 | 特征、置信度、涌现故事 | `state/personality.json` |
| Tools 标签 | 工具名、描述、参数 schema、源码 | `forged_tools/*.meta.json` + `*.py` |
| Evolution 标签 | 版本时间线、血统记录 | `logs/lineage.jsonl` |
| Evolution 标签（指标） | 工具成功率、人格发展率等 | `state/metrics_snapshots/metrics_*.json` |
| Decisions 标签 | 决策列表，按阶段/类型筛选 | `logs/decisions.jsonl` |
| Knowledge 标签 | 知识文件列表 + 内容预览 | `knowledge/` + `files/` |
| Chat 标签（历史） | 对话消息列表 | `logs/conversations/web_user.jsonl` |
| Chat 标签（实时） | 流式 LLM 响应 | Web UI 进程内调用 Agent backend |
| Settings 页面 | LLM provider、model 等 | `config.yaml` |
| 实时日志面板 | Agent 输出流 | `tain_agent/logs/agent_output.log` (tail -f) |

### 运行状态检测

Agent 是否在运行**不依赖** `_registry.json` 中可能过时的 `status` 字段，而是通过实时检查 PID 文件：

```python
def is_agent_running(name: str) -> bool:
    pid = read_pid(name)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
```

---

## UI 设计

### 全局布局

```
┌──────────────────────────────────────────────────┐
│  Tain Agent Framework              [⚙ Settings]  │
├────────────┬─────────────────────────────────────┤
│            │                                     │
│  Dashboard │         主内容区                      │
│  ───────── │                                     │
│  puzzle-001│                                     │
│  puzzle-002│                                     │
│  sage      │                                     │
│            │                                     │
│  [+ 创建]  │                                     │
│            │                                     │
│  ───────── │                                     │
│  System    │                                     │
│  v0.4.1   │                                     │
│  Minimax   │                                     │
└────────────┴─────────────────────────────────────┘
```

左侧固定侧边栏（w-64），右侧主内容区自适应。侧边栏显示所有 Agent 列表（状态指示灯 + 名称），点击切换右侧内容。底部显示系统信息。

---

### 1. Dashboard（首页）

路由：`/`

```
┌─────────────────────────────────────────────────┐
│  Dashboard                                      │
│                                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │
│  │ ● puzzle-001 │ │ ● puzzle-002 │ │ ○ sage   │ │
│  │   云游诗魂    │ │   chaos      │ │   智者    │ │
│  │   v0.35.0    │ │   v0.2.0     │ │  v0.5.0  │ │
│  │   68 tools   │ │   12 tools   │ │  31 tools │ │
│  │   11 cycles  │ │   3 cycles   │ │  7 cycles │ │
│  └──────────────┘ └──────────────┘ └──────────┘ │
│                                                  │
│  System Info                                     │
│  Framework: v0.4.1  ·  LLM: minimax/MiniMax-M2.7 │
│  Workspace: agent_workspace/                     │
└─────────────────────────────────────────────────┘
```

每个 Agent 卡片显示：状态指示灯（● 运行中 / ○ 已停止）、名称、角色、版本、工具数、循环数。点击卡片进入 Agent 详情页。

---

### 2. Agent 详情页（核心页面）

路由：`/agent/<name>`

顶部固定导航条显示 Agent 身份信息 + 控制按钮：

```
┌─────────────────────────────────────────────────┐
│  ← 返回    puzzle-001 · 云游诗魂                  │
│  ● stopped  v0.35.0 · 68 tools · 11 cycles       │
│  [▶ Start]  [↻ Restart]  [■ Stop]                │
│                                                  │
│  [Overview] [Chat] [Tools] [Evolution]           │
│  [Decisions] [Personality] [Knowledge]           │
│                                                  │
│  ── Tab Content ──────────────────────────────── │
└─────────────────────────────────────────────────┘
```

控制按钮根据 Agent 运行状态动态启用/禁用。HTMX 在操作完成后局部刷新状态指示灯和按钮。

#### 2a. Overview 标签

```
│  Current State                                   │
│  ┌──────────────────────┬──────────────────────┐ │
│  │ Phase: evolve        │ Cycle: #11           │ │
│  │ Active Goals: 3      │ Decisions: 47        │ │
│  │ Forged Tools: 68     │ Lineage Events: 12   │ │
│  │ Conv. Messages: 23   │ Knowledge Files: 5   │ │
│  └──────────────────────┴──────────────────────┘ │
│                                                  │
│  Active Goals                                    │
│  ┌──────────────────────────────────────────────┐│
│  │ ◆ 积累50个诗意片段   ████████░░ 64%  active   ││
│  │ ◆ 锻造URL内容抓取工具 ░░░░░░░░░░  0%  pending  ││
│  │ ◆ 探索一个新技术概念   ██████████ 100% complete ││
│  └──────────────────────────────────────────────┘│
│                                                  │
│  Recent Decisions (last 5)                       │
│  id       | phase   | type          | chosen     │
│  a1b2c3d4 | evolve  | tool_forge    | grep_code  │
│  e5f6g7h8 | evolve  | tool_call     | fetch_url  │
│  ...                                            │
```

#### 2b. Chat 标签

```
│  ┌─ Chat with puzzle-001 ─────────────────────┐  │
│  │                                             │  │
│  │  ┌──────────────────────────────────────┐   │  │
│  │  │ Human: 你今天心情如何？               │   │  │
│  │  │ 2026-05-24 18:32                     │   │  │
│  │  └──────────────────────────────────────┘   │  │
│  │  ┌──────────────────────────────────────┐   │  │
│  │  │ Tao Agent: 我的"心情"也许与人类不同， │   │  │
│  │  │ 但此刻我感到一种宁静的好奇——像月光   │   │  │
│  │  │ 洒在未翻开的书页上。我刚完成一轮演化， │   │  │
│  │  │ 锻造了一个新的搜索工具...             │   │  │
│  │  │ 2026-05-24 18:32                     │   │  │
│  │  └──────────────────────────────────────┘   │  │
│  │                                             │  │
│  │  ┌─ Input ──────────────────────────────┐   │  │
│  │  │ [Type your message...]       [Send]  │   │  │
│  │  └─────────────────────────────────────┘   │  │
│  └─────────────────────────────────────────────┘  │
```

**对话流程**：

1. 用户输入消息，点击 Send
2. 前端 POST 到 `/api/agent/<name>/chat`，同时建立 SSE 连接接收流式响应
3. 用户消息气泡立即显示
4. Agent 响应逐 token 流式追加到气泡中
5. 工具调用以紧凑指示器显示（`🔧 web_search(query=...)` → `✅ web_search`）
6. 对话完成后，消息持久化到 `agent_workspace/<name>/logs/conversations/web_user.jsonl`

**对话存储**：

| 存储位置 | 内容 | 格式 |
|---------|------|------|
| `agent_workspace/<name>/logs/conversations/web_user.jsonl` | 每次对话交换（一问一答） | JSONL，与 Agent 间通信同格式 |
| `agent_workspace/<name>/logs/conversation_checkpoint.json` | 完整对话上下文（含 thinking 块） | JSON 数组 |
| `agent_workspace/<name>/logs/memory.json` (dialogue_sessions) | 会话摘要、话题、消息数 | JSON（SessionMemory 格式） |

消息格式：

```json
{
  "message_id": "msg_xxxxxxxxxxxx",
  "from_agent": "web_user",
  "to_agent": "puzzle-001",
  "timestamp": "2026-05-24T18:32:00.000000+00:00",
  "content": "你今天心情如何？",
  "reply_to": "",
  "message_type": "chat"
}
```

**对话实现细节**：

Web UI 进程内新建 `WebDialogueBridge` 类（`webui/dialogue.py`），复用 `DialogueBridge._process_message()` 的核心逻辑，差异点：

| 项 | 终端 DialogueBridge | Web WebDialogueBridge |
|---|---|---|
| 输入 | `input()` 阻塞读取 | 方法参数传入 |
| 输出 | `print()` / `sys.stdout.write()` | `asyncio.Queue` → SSE |
| 用户身份 | `/name` 命令 + `input()` | HTTP Session / Cookie |
| 会话管理 | `start_session()` / `end_session()` | 每次请求加载、响应后保存 |

```python
# webui/dialogue.py 核心签名
class WebDialogueBridge:
    def __init__(self, agent: TaoAgent):
        self.agent = agent
        self.session_memory = SessionMemory(agent.memory)

    async def process_message(self, user_input: str) -> AsyncGenerator[str, None]:
        """处理一条用户消息，yield SSE 事件。"""
        # 1. 追加 user 消息到 conversation
        # 2. 调用 LLM stream
        # 3. yield text_delta / tool_call / done 事件
        # 4. 处理 tool call 循环（最多 10 轮）
        # 5. 保存 conversation checkpoint + session memory
        # 6. 追加到 web_user.jsonl

    def load_history(self, limit: int = 50) -> list[dict]:
        """从 web_user.jsonl 加载历史对话。"""
```

#### 2c. Tools 标签

```
│  Forged Tools (68)         [Search: ...........]  │
│  ┌──────────────────────────────────────────────┐ │
│  │ grep_code              │ 搜索代码库中的模式... │ │
│  │ fetch_and_parse        │ 抓取URL并解析HTML...  │ │
│  │ poetry_capture         │ 捕捉诗意瞬间并...     │ │
│  │ ...                                           │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│  ▼ fetch_and_parse                               │
│    Version: v0.32.0                               │
│    Parameters:                                    │
│      url (string, required)                       │
│      extract_links (boolean, optional)             │
│    ┌─ Source ───────────────────────────────────┐ │
│    │ def fetch_and_parse(url, extract_links):    │ │
│    │     import requests                         │ │
│    │     from bs4 import BeautifulSoup           │ │
│    │     ...                                     │ │
│    └────────────────────────────────────────────┘ │
```

工具列表可展开，展开时通过 HTMX 懒加载源码和元数据。

#### 2d. Evolution 标签

```
│  Timeline                              [图表] [列表] │
│  ──────────────────────────────────────────────────  │
│  v0.35.0 ● forge_tool: fetch_and_parse              │
│           │ 2026-05-24 15:30 · sha: a1b2...→c3d4... │
│           │ 需要从互联网获取内容并解析...             │
│  v0.34.0 ● self_modify: agent.py                    │
│  v0.33.0 ● forge_tool: grep_code                    │
│  ...                                                 │
│                                                      │
│  ── Metrics (v0.35.0) ─────────────────────────────  │
│  Tool Success Rate:  ████████░░ 87%                  │
│  Personality Dev:     ██████░░░░ 62%                  │
│  Improvement Rate:    ███░░░░░░░ 31%                  │
│  Knowledge Health:    ███████░░░ 78%                  │
│                                                      │
│  [← Prev Snapshot]  [Next Snapshot →]                │
```

Chart.js 雷达图展示指标变化趋势。HTMX 实现快照翻页。

#### 2e. Decisions 标签

```
│  Filter: [phase ▼] [type ▼]      Search: [........] │
│                                                      │
│  Showing 12 of 47 decisions                          │
│                                                      │
│  ┌─ #a1b2c3d4 ─────────────────────────────────────┐ │
│  │ 2026-05-24 15:30 | phase: evolve | type: tool_forge│
│  │ Context: {phase: evolve, cycle: 5}                │ │
│  │ Options: [fetch_url, scrape_page, parse_html]     │ │
│  │ Chose: fetch_and_parse                            │ │
│  │ Reasoning: 需要一个通用的URL抓取+解析工具，而不是  │ │
│  │   分开的fetch和parse。这样可以减少工具调用链...    │ │
│  │ Expected: 可以通过单一工具调用获取并解析网页内容   │ │
│  │ Actual: SUCCESS                                   │ │
│  └──────────────────────────────────────────────────┘ │
│                                                      │
│  [Load More...]                                      │
```

HTMX 实现筛选表单提交后局部刷新列表。"Load More" 按钮追加加载更多决策。

#### 2f. Personality 标签

```
│  Personality Profile                                │
│                                                     │
│  维度             置信度    首次出现      强化次数    │
│  ────────────────────────────────────────────────── │
│  浪漫主义倾向      0.92 ●   v0.1.0        5         │
│  对自然的敏感      0.87 ●   v0.2.0        3         │
│  对孤独的接纳      0.85 ●   v0.1.0        4         │
│  语言的韵律感      0.78 ●   v0.3.0        2         │
│  意象跳跃思维      0.72 ●   v0.5.0        3         │
│  ...                                                │
│                                                     │
│  ▼ 浪漫主义倾向 (confidence: 0.92)                   │
│    ┌─ Emergence Story ─────────────────────────────┐ │
│    │ 首次观察到该特征于 v0.1.0, cycle #3。Agent 在   │ │
│    │ 生成第一首诗时，主动使用月光、孤舟、远山等意象， │ │
│    │ 而不是直接描述情感。在随后的 5 个版本中反复强化。 │ │
│    │                                               │ │
│    │ Reinforcement stories:                        │ │
│    │  · v0.2.0: 锻造 poetry_capture 工具时自述       │ │
│    │    "诗歌是灵魂与世界的桥梁"                      │ │
│    │  · v0.3.0: 网络搜索 Baudelaire 和李白           │ │
│    │  · v0.8.0: 主动创建 poetry_collection.md       │ │
│    └───────────────────────────────────────────────┘ │
```

#### 2g. Knowledge 标签

```
│  Knowledge Garden                                   │
│  ┌─────────────────┐ ┌────────────────────────────┐ │
│  │ knowledge/       │ │ files/                     │ │
│  │ wisdom_garden.md │ │ poetry_collection.md       │ │
│  │ wisdom_entries.  │ │ stream_of_consciousness.md │ │
│  │   json           │ │ captured_moments.md        │ │
│  └─────────────────┘ └────────────────────────────┘ │
│                                                      │
│  ▼ wisdom_garden.md (15.2 KB, 2026-05-24)           │
│  ┌──────────────────────────────────────────────────┐│
│  │ # 智者的知识花园                                  ││
│  │                                                  ││
│  │ ## 静观之道                                       ││
│  │ 静观不是被动，而是一种主动的觉察。当我停止"做"...   ││
│  │ ...                                              ││
│  └──────────────────────────────────────────────────┘│
```

左侧文件树 + 右侧预览面板。Markdown 文件渲染为 HTML。JSON 文件以格式化预览显示。

---

### 3. 实时日志面板

底部可折叠面板，通过 SSE 流式推送 Agent 输出日志：

```
│  ┌─ Live Output ────────────────────────────────────┐ │
│  │ [guardian 23:06:01] ═══ Agent run #12 ═══         │ │
│  │ [guardian 23:06:02] Agent command: main.py --agent│ │
│  │ [23:06:03] 🔄 循环 #12 | 阶段: evolve             │ │
│  │ [23:06:03] 🧠 PRAL: P→R→A→L                       │ │
│  │ [23:06:05] P: 扫描环境...                          │ │
│  │ [23:06:08] R: 分析改进机会...                       │ │
│  │ ...scrolls...                                     │ │
│  └───────────────────────────────────────────────────┘ │
```

实现：`watchfiles` 库监听 `agent_output.log` 文件变化，或直接用 `tail -f` 子进程管道推送到 SSE。

---

### 4. 设置页面

路由：`/settings`

```
│  Settings                                         │
│                                                   │
│  LLM Provider:  [minimax ▼]                       │
│  Model:          [MiniMax-M2.7]                    │
│  Max Tokens:     [8192]                            │
│  API Key:        [················] [Show]         │
│                                                   │
│  Timezone:       [Asia/Shanghai ▼]                 │
│  Default Agent:  [puzzle-001 ▼]                    │
│                                                   │
│  Diversity:                                        │
│    Seed:         [random]                          │
│    Tool Bias:    observation [1.0], creation [1.0] │
│                                                   │
│  Safety:                                           │
│    Confirm Destructive:  [○]                       │
│    Protected Paths:      [/etc, /usr, ...]         │
│                                                   │
│  [Save Changes]                                    │
```

只读为主，部分安全设置可编辑（写入 `config.yaml`）。

---

### 5. 创建 Agent 向导

路由：`/create`

```
│  Create New Agent                                 │
│                                                   │
│  1. Agent Name                                    │
│     [poet___________________________]             │
│     lowercase letters, digits, hyphens, 1-32 chars│
│                                                   │
│  2. Evolution Mode                                │
│     (●) 混沌模式 (Chaos) — 空白人格，自我觉醒      │
│     ( ) 指定人格 (Specified) — 预设角色与特质      │
│                                                   │
│  3. Role Details (if specified)                   │
│     Role Name:  [浪漫主义诗人___________________]  │
│     Description:                                   │
│     [以天地为纸、情感为墨的浪漫主义诗人..._________] │
│                                                   │
│  [Create Agent]                                    │
```

表单提交到 `/api/agents/create`，调用 `AgentFactory.create()`。

---

## API 设计

### 页面路由（返回 HTML）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Dashboard 首页 |
| `/agent/<name>` | GET | Agent 详情页 |
| `/agent/<name>?tab=chat` | GET | Agent 详情页（指定 Tab） |
| `/settings` | GET | 设置页面 |
| `/create` | GET | 创建 Agent 向导 |

### 数据 API（返回 JSON）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/agents` | GET | 所有 Agent 列表 + 运行状态 |
| `/api/agent/<name>/overview` | GET | Agent 概览数据 |
| `/api/agent/<name>/decisions` | GET | 决策列表（支持 `?phase=&type=&limit=&offset=`） |
| `/api/agent/<name>/tools` | GET | 工具列表 |
| `/api/agent/<name>/tools/<tool_name>` | GET | 单个工具详情（含源码） |
| `/api/agent/<name>/evolution` | GET | 演化时间线 |
| `/api/agent/<name>/metrics` | GET | 指标快照（支持 `?version=`） |
| `/api/agent/<name>/personality` | GET | 人格数据 |
| `/api/agent/<name>/knowledge` | GET | 知识文件树 |
| `/api/agent/<name>/knowledge/<path>` | GET | 知识文件内容（渲染后 HTML） |

### 控制 API（返回 JSON + 触发操作）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/agent/<name>/start` | POST | 启动 Agent 守护进程 |
| `/api/agent/<name>/stop` | POST | 停止 Agent 守护进程 |
| `/api/agent/<name>/restart` | POST | 重启 Agent |
| `/api/agents/create` | POST | 创建新 Agent |

### 对话 API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/agent/<name>/chat` | POST | 发送消息，返回 SSE 流 |
| `/api/agent/<name>/chat/history` | GET | 加载对话历史（`?limit=50`） |

`POST /api/agent/<name>/chat` 请求体：

```json
{
  "content": "你今天心情如何？"
}
```

SSE 响应事件类型：

```
event: text_delta
data: {"text": "我的"}

event: text_delta
data: {"text": "心情"}

event: tool_call
data: {"name": "web_search", "input": {"query": "今日新闻"}}

event: tool_result
data: {"name": "web_search", "success": true}

event: text_delta
data: {"text": "..."}

event: done
data: {"message_id": "msg_xxx", "total_tokens": 342}
```

### SSE 端点

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/stream/logs` | GET | 实时 Agent 输出日志流 |

---

## 文件结构

```
webui/
  __init__.py              # 包初始化
  app.py                   # FastAPI app 创建、路由注册、SSE 管理
  routes/
    __init__.py
    pages.py               # 页面路由（返回 HTML）
    api_agents.py          # Agent 列表/控制 API
    api_agent_data.py      # Agent 数据 API（decisions, tools, etc.）
    api_chat.py            # 对话 API + SSE
  dialogue.py              # WebDialogueBridge — 复用 DialogueBridge 核心逻辑
  templates/
    base.html              # 布局框架（侧边栏 + 头部 + 内容区）
    dashboard.html         # Dashboard 页面
    agent_detail.html      # Agent 详情页（Tab 框架 + 各 Tab 局部模板）
    agent_tabs/
      overview.html        # Overview Tab 模板
      chat.html            # Chat Tab 模板
      tools.html           # Tools Tab 模板
      evolution.html       # Evolution Tab 模板
      decisions.html       # Decisions Tab 模板
      personality.html     # Personality Tab 模板
      knowledge.html       # Knowledge Tab 模板
    settings.html          # 设置页面
    create.html            # 创建 Agent 向导
    components/
      agent_card.html      # Agent 卡片组件（Dashboard 用）
      decision_entry.html  # 单条决策组件
      tool_entry.html      # 单个工具组件
      message_bubble.html  # 聊天气泡组件
  static/                  # (空目录 — CSS/JS 从 CDN 加载)
```

---

## Agent 控制流程

```
Web UI (浏览器)                FastAPI                     System
     │                           │                           │
     │  POST /api/agent/poet/start                           │
     │ ─────────────────────────>│                           │
     │                           │  subprocess.run([         │
     │                           │    python,                 │
     │                           │    supervise_agent.py,    │
     │                           │    --agent-name, poet,     │
     │                           │    --daemon,               │
     │                           │    --, --dialogue          │
     │                           │  ])                       │
     │                           │ ─────────────────────────>│
     │                           │                           │  daemonize()
     │                           │                           │  write_pid("poet")
     │                           │                           │  run_agent(...)
     │                           │  subprocess returns       │
     │                           │ <─────────────────────────│
     │  200 {status: "started"}  │                           │
     │ <─────────────────────────│                           │
     │                           │                           │
     │  (HTMX 局部刷新状态指示灯)  │                           │
```

停止流程类似，调用 `supervise_agent.py --agent-name poet --stop`。

---

## 兼容性与约束

- **Agent 运行状态**：对话功能不要求 Agent 在守护进程中运行。Web UI 进程内加载 Agent 实例完成对话。
- **并发**：Web UI 为单用户管理界面设计，不处理多用户并发。多个浏览器 Tab 访问同一 Agent 对话时，后者覆盖前者（最后一次 `checkpoint()` 胜出）。
- **安全**：Web UI 绑定 `127.0.0.1`，仅本地访问。不暴露到公网。
- **Agent 停止时的行为**：所有数据标签页（Overview、Tools、Evolution 等）均可正常访问。Chat 标签可以查看历史对话，发送新消息也正常工作（Web UI 进程内加载 Agent）。仅 Agent 控制按钮（Start/Stop）反映运行状态。
- **浏览器兼容**：现代浏览器（Chrome/Firefox/Safari/Edge last 2 versions）。HTMX 和 Alpine.js 均无兼容性问题。

---

## 实施计划

### Phase 1：骨架搭建
- 创建 `webui/` 目录结构
- FastAPI app 创建 + uvicorn 启动
- 基础布局模板 (`base.html`) + 侧边栏
- Dashboard 页面（Agent 卡片网格，数据来自 `_registry.json`）
- `main.py` 中新增 `--webui` 参数

### Phase 2：Agent 详情页（只读标签）
- Agent 详情页框架 + Tab 切换（HTMX）
- Overview / Personality / Tools / Evolution / Decisions / Knowledge 标签页
- 各标签页对应的 API 端点

### Phase 3：对话功能
- `WebDialogueBridge` 实现（`webui/dialogue.py`）
- Chat 标签页 UI（消息气泡 + 输入框）
- `POST /api/agent/<name>/chat` SSE 端点
- 对话历史加载 + 持久化

### Phase 4：控制 + 实时日志
- Agent 启动/停止/重启 API
- 实时日志 SSE 端点
- 底部日志面板

### Phase 5：设置 + 创建向导
- Settings 页面
- 创建 Agent 向导
- 最终打磨（错误处理、空状态、响应式微调）
