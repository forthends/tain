# IDE 嵌入运行时 · 设计文档

**日期**: 2026-05-31
**来源**: Agent 自演进模块升级 — 目标 3
**范围**: MCP Server（运行时嵌入）+ Skill Bundle（离线分发）+ Slim Kernel
**依赖**: Core-Plugins 架构（v0.6.0）+ 评估体系（投产判定）

---

## 1. 架构总览

```
                    ┌──────────────────────────────┐
                    │      IDE (Claude Code /       │
                    │      Cursor / Codex)          │
                    └──────────┬───────────────────┘
                               │ MCP Protocol (stdio / SSE)
            ┌──────────────────┼──────────────────┐
            │                  │                  │
            ▼                  ▼                  ▼
   ┌────────────┐    ┌────────────┐    ┌────────────────┐
   │ tools/list │    │ tools/call │    │ resources/read │
   │  → Tool    │    │  → Tool    │    │  → Knowledge   │
   │   Plugin   │    │   Plugin   │    │    Plugin      │
   └────────────┘    └────────────┘    └────────────────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
   ┌────────────┐ ┌────────────┐ ┌────────────┐
   │ prompts/get│ │ prompts/list│ │  (export)  │
   │ → Identity │ │ → Identity │ │ Skill Bundle│
   │   Plugin   │ │   Plugin   │ │  → 离线分发  │
   └────────────┘ └────────────┘ └────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        Slim Kernel (AgentKernel — 5 插件精简模式)
  Identity + Tool + Skill + Knowledge + Memory
  (无 Workflow + Collaboration + Evaluation + 演化循环)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 设计原则

- **MCP 标准协议**：IDE 嵌入使用 Model Context Protocol，零侵入 IDE，被 Claude Code/Cursor/Codex 原生支持
- **投产门禁**：只有通过评估体系判定为 `PRODUCTION_READY` 的 Agent 才能启动 MCP Server
- **精简内核**：IDE 模式加载 5 个插件（identity/skill/tool/knowledge/memory），无演化循环
- **双模式互补**：MCP Server（运行时嵌入）+ Skill Bundle（离线文件分发）

### 与现有代码的关系

```
现有                                →  IDE 嵌入层
──────────────────────────────────────────────────────────
runtime/ (独立内核，实验性)           →  废弃，Kernel 的 "ide" 布局替代
evolution/skill_exporter.py          →  保留，新增 export_agent_bundle()
tools/mcp_loader.py (加载外部MCP)    →  保留（加载外部工具），新增 mcp/server.py（暴露自身）
tain_agent/compat.py                 →  新增 mcp_server 入口
```

---

## 2. Slim Kernel — "ide" 插件布局

### 2.1 布局定义

在 `tain_agent/kernel/lifecycle.py` 的 `PLUGIN_LAYOUT` 中新增：

```python
PLUGIN_LAYOUT = {
    "specified": ["identity", "memory", "skill", "tool", "knowledge", "workflow", "collaboration", "evaluation"],
    "chaos": ["identity", "memory", "tool"],
    "ide": ["identity", "tool", "skill", "knowledge", "memory"],
}
```

IDE 模式不加载 workflow、collaboration、evaluation 插件——这些是演化期需要的，投产 Agent 不需要。

### 2.2 启动方式

```bash
# 方式 1：直接通过 CLI
python main.py --agent <name> --mcp-serve

# 方式 2：作为 Python 模块（供 IDE 配置）
python -m tain_agent.mcp.server --agent <name> --mode stdio
```

---

## 3. MCP Server

### 3.1 入口点

```python
# tain_agent/mcp/server.py

class AgentMCPServer:
    """将已投产 Agent 暴露为 MCP Server，供 IDE 调用。"""

    def __init__(self, agent_name: str, mode: str = "stdio"):
        # 1. 检查投产就绪度
        # 2. 加载 Slim Kernel（"ide" 布局：5 插件）
        # 3. 注册 MCP 端点
        pass

    def serve(self) -> None:
        """启动 MCP Server，阻塞直到收到终止信号。"""
```

### 3.2 MCP 端点映射

| MCP 端点 | 数据源 | 作用 |
|----------|--------|------|
| `tools/list` | ToolPlugin.list_tools() | IDE 发现 Agent 能做什么 |
| `tools/call` | ToolPlugin.call(name, **kwargs) | IDE 委托 Agent 执行操作 |
| `resources/list` | KnowledgePlugin + MemoryPlugin | 浏览 Agent 知识库和记忆 |
| `resources/read` | KnowledgePlugin.query(entity_id) | 获取特定知识详情 |
| `prompts/list` | IdentityPlugin | Agent 的身份感知提示模板 |
| `prompts/get` | IdentityPlugin.enrich_prompt() | 将 Agent 身份上下文注入 IDE 会话 |

### 3.3 tools/list 响应示例

```json
{
  "tools": [
    {
      "name": "web_search",
      "description": "搜索互联网获取最新信息",
      "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"]
      }
    }
  ]
}
```

### 3.4 prompts/get 响应示例

```json
{
  "messages": [
    {
      "role": "system",
      "content": {
        "type": "text",
        "text": "## 你的身份\n角色: Python 后端工程师\n使命: 以 Python 后端工程师的身份持续学习..."
      }
    }
  ]
}
```

### 3.5 安全边界

- **投产门禁**：`evaluate.get_production_readiness()["status"] == "production_ready"` 不满足则拒绝启动
- **只读优先**：resources/read 和 prompts/get 纯只读
- **沙箱继承**：tools/call 受 ToolPlugin 现有沙箱约束
- **工作空间隔离**：Agent 只能访问 `agent_workspace/<name>/`
- **速率限制**：可配置 `max_tool_calls_per_minute`，默认 60

---

## 4. Skill Bundle 导出

### 4.1 导出流程

```
已投产 Agent (PRODUCTION_READY)
         │
         ▼
  export_agent_bundle()
         │
    ┌────┴────┐
    ▼         ▼
  MCP        Skill
  Server    Bundle
  (运行时)   (离线文件)
```

### 4.2 Bundle 结构

```
exports/<agent_name>/
├── SKILL.md                    # Agent 完整能力说明书
├── scripts/
│   ├── identity.json           # IdentityPlugin.snapshot()
│   ├── skills.json             # SkillPlugin 技能 + 成熟度
│   ├── tools.json              # ToolPlugin 工具 Schema
│   └── knowledge_graph.json    # KnowledgePlugin 子图导出
└── references/
    ├── domain_knowledge/       # 按领域整理的 Markdown 文档
    └── best_practices/         # 最佳实践
```

### 4.3 SKILL.md 模板

```markdown
---
name: {agent_name}
description: {role_description}
tags: [tain-agent, {role}, exported]
version: {agent_version}
---

# {agent_name} — {role}

## 身份
{从 IdentityPlugin 读取的角色描述、使命、专长领域}

## 技能清单
| 技能 | 成熟度 | 成功率 | 工具 |
|------|--------|--------|------|
...

## 可用工具
{从 ToolPlugin.list_tools() 导出}

## 知识领域
{从 KnowledgePlugin 导出}

## 使用方式
### 作为 MCP Server
python -m tain_agent.mcp.server --agent {agent_name} --mode stdio

### 作为独立 Skill 包
将此目录复制到 IDE skill 目录即可使用。
```

### 4.4 实现接口

```python
# 扩展 tain_agent/evolution/skill_exporter.py

def export_agent_bundle(agent_name: str, output_dir: str = None) -> dict:
    """导出已投产 Agent 的完整能力包。

    1. 加载 Agent（Slim Kernel，5 插件）
    2. 检查投产就绪度
    3. snapshot() 各插件 → JSON 文件
    4. KnowledgePlugin.export_subgraph() → Markdown 文档
    5. 生成 SKILL.md

    Returns:
        {"success": bool, "bundle_path": str, "files_created": int}
    """
```

### 4.5 与现有 skill_exporter 的关系

| | 现有 skill_exporter | 新增 export_agent_bundle |
|---|---|---|
| 粒度 | 1 tool = 1 skill | 1 agent = 1 bundle |
| 内容 | 单个工具代码 + 说明 | 全部 5 插件快照 + 身份 + 知识 |
| 用途 | 分享单个能力 | 分享完整 Agent |
| 兼容性 | 保持不变 | 新增，互补不冲突 |

---

## 5. CLI 集成

```bash
# 启动 MCP Server
python main.py --agent poet --mcp-serve

# 导出 Agent Skill Bundle
python main.py --agent poet --export-bundle --output ./exports/

# 列出可投产 Agent
python main.py --list-production-ready
```

### 新增 CLI 参数

| 参数 | 作用 |
|------|------|
| `--mcp-serve` | 以 MCP Server 模式启动 Agent |
| `--export-bundle` | 导出 Agent 为 Skill Bundle |
| `--list-production-ready` | 列出所有通过投产判定的 Agent |

---

## 6. 文件结构

```
tain_agent/
  mcp/                             # 新建 — MCP Server
    __init__.py
    server.py                      # AgentMCPServer
    endpoints.py                   # MCP 端点注册（tools/resources/prompts）
    middleware.py                   # 投产门禁 + 速率限制

  evolution/
    skill_exporter.py              # 修改 — 新增 export_agent_bundle()
    exporter.py                    # 修改 — 新增 --export-bundle 支持

  kernel/
    lifecycle.py                   # 修改 — PLUGIN_LAYOUT 新增 "ide" 布局

  main.py                          # 修改 — 新增 --mcp-serve, --export-bundle 标志

tests/
    test_mcp_server.py             # 新建 — MCP Server 测试
    test_agent_bundle.py           # 新建 — Skill Bundle 导出测试
```

---

## 7. 与上游目标的关系

| # | 目标 | IDE 嵌入的贡献 |
|---|------|---------------|
| 1 | Agent 核心重构 | Slim Kernel 复用 Kernel + 5 插件 |
| 2 | 评估体系 | 投产门禁确保只有成熟 Agent 能通过 MCP 暴露 |

---

*设计文档完*
