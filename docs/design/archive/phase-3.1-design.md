# Phase 3.1 — Agent Skills 集成设计

> 方向 2 (Tool→Skill 导出) + 方向 4 (知识库标准化)
> 将 Tain Agent 的进化产物对齐 agentskills.io 开放标准

---

## 一、设计目标

让 Tain Agent 的进化产物（工具 + 知识）以 **agentskills.io 标准格式** 输出，实现：

1. **工具可被外部 Agent 消费**：锻造的 `.py` 工具导出为标准 `SKILL.md` + `scripts/` 结构，Claude Code / Copilot / Cursor 等可直接加载
2. **知识可被外部 Agent 检索**：知识文档采用 SKILL.md 的 YAML frontmatter 格式，支持渐进式发现
3. **Phase 3 的"出生"产物升级**：导出物从纯内部格式升级为行业标准 + 内部格式双输出

---

## 二、方向 2：Tool → Skill 导出

### 2.1 转换映射

将 Tain Agent 的锻造工具转换为 Agent Skills 标准格式：

```
锻造工具                                   Agent Skill
──────────────────────────────────────    ──────────────────────────────
forged_tools/
├── my_tool.py                            my-tool/
└── my_tool.meta.json                     ├── SKILL.md
                                          │   ├── YAML frontmatter
                                          │   │   name: my-tool
                                          │   │   description: <from .meta.json>
                                          │   │   metadata:
                                          │   │     parameters: <from .meta.json>
                                          │   │     forged_by: <agent_name>
                                          │   │     version: <agent_version>
                                          │   │     evolution_cycles: <N>
                                          │   │   compatibility: "requires tain_agent runtime"
                                          │   └── Markdown body
                                          │       # 工具使用说明（自动生成）
                                          │       ## Parameters
                                          │       ## Returns
                                          │       ## Example
                                          ├── scripts/
                                          │   └── main.py        ← 原 .py 代码
                                          └── references/
                                              └── schema.json    ← .meta.json 原文
```

### 2.2 SKILL.md 自动生成规则

从 `.meta.json` + `.py` 自动生成 SKILL.md：

**Frontmatter**：

```yaml
---
name: <tool_name>                    # .meta.json → name，下划线转连字符
description: <tool_description>      # .meta.json → description
compatibility: requires Python 3.9+  # 可选，从代码 import 推断
metadata:
  forged_by: "<agent_name>"          # 从 personality.json 读取
  agent_version: "<version>"         # 从 version.json 读取
  evolution_cycles: <N>              # 锻造时的进化轮次
  parameters:                        # .meta.json → parameters
    param_name:
      type: string
      description: "..."
  tao_tool_id: "<name>"              # 保留原始 tool name 以便回厂
---
```

**Body**（自动生成模板）：

```markdown
# <Tool Name>

## What this tool does
<description>

## Parameters
- `param1` (string, required): description
- `param2` (integer, optional): description

## Returns
<inferred from code or manual>

## Usage Example
<placeholder — agent can fill in>

## Script
Run with: `python scripts/main.py`
Requires: Python 3.9+ <with dependencies listed>
```

### 2.3 实现模块：`tain_agent/evolution/skill_exporter.py`

```
skill_exporter.py
├── class SkillExporter:
│   ├── export_tool_as_skill(tool_name) → Path
│   │   """将单个 forged tool 导出为 Skill 目录"""
│   │   1. 读取 .meta.json + .py
│   │   2. 生成 SKILL.md (frontmatter + body)
│   │   3. 创建目录结构: {name}/SKILL.md, scripts/main.py, references/schema.json
│   │   4. 返回 Skill 目录路径
│   │
│   ├── export_all_tools(skills_dir) → list[Path]
│   │   """将所有 forged tools 批量导出为 Skills"""
│   │
│   └── export_workspace_as_skills(workspace_dir, output_dir) → ExportResult
│       """将整个 workspace 导出为标准 Skills 集合 + 知识库"""
│
├── class SkillMetadata:
│   """从 forged tool 元数据生成 SKILL.md frontmatter"""
│   ├── from_tool_meta(meta_json, py_code) → dict
│   ├── from_knowledge_doc(md_file) → dict
│   └── to_yaml_frontmatter(metadata_dict) → str
│
├── class SkillBodyGenerator:
│   """从 forged tool 代码自动生成 SKILL.md body"""
│   ├── from_python_code(code, parameters) → str
│   │   """AST 分析 → 提取函数签名、docstring、依赖"""
│   └── from_knowledge_doc(md_content) → str
│       """从现有 markdown 提取 body（去 frontmatter）"""
│
└── def validate_skill(skill_dir) → dict
    """对照 agentskills.io spec 校验 Skill 合法性"""
```

### 2.4 集成到 Phase 3 Export Pipeline

在现有 `exporter.py` 的 Step 3（组装）中增加分支：

```python
# exporter.py Step 3 — 新增
def _assemble_skills(dist_dir, tools, knowledge_dir):
    """并行生成 Skills 格式输出"""
    skills_dir = dist_dir / "skills"
    skill_exporter = SkillExporter()
    skill_exporter.export_all_tools(tools, output_dir=skills_dir)
    # 知识库也按 Skill 格式输出
    skill_exporter.export_knowledge_as_skills(knowledge_dir, skills_dir)
```

产物目录结构升级为：

```
dist/explorer-v0.23.0/
├── main.py                  ← 独立启动入口（现有）
├── runtime/                 ← 运行时内核（现有）
├── tools/                   ← 内部格式工具（现有）
├── skills/                  ← ★ 新增：标准 Skills 格式
│   ├── code-entropy/
│   │   ├── SKILL.md
│   │   ├── scripts/main.py
│   │   └── references/schema.json
│   ├── knowledge-freshness/
│   │   └── ...
│   └── ...
├── knowledge/               ← 知识库（升级为 SKILL.md 格式）
│   ├── memory-architecture/
│   │   ├── SKILL.md         ← ★ 标准化：frontmatter + body
│   │   └── references/
│   └── ...
├── identity.json
├── config.yaml
└── README.md
```

### 2.5 新增工具：`export_as_skill`

Agent 可调用的工具，将指定工具导出为标准 Skill：

```python
# tain_agent/tools/forged/export_as_skill.py

SCHEMA = {
    "name": "export_as_skill",
    "description": (
        "Export a forged tool or knowledge document as a standard Agent Skill "
        "(agentskills.io format). The resulting SKILL.md + scripts/ directory "
        "can be used by Claude Code, Copilot, Cursor, and other agents. "
        "Use this when you want your tools or knowledge to be portable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Name of the forged tool to export as a Skill."
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to write the Skill (default: skills/)."
            },
        },
        "required": ["tool_name"],
    },
}
```

---

## 三、方向 4：知识库标准化

### 3.1 当前状态

知识文档是自由格式的 `.md` 文件，通过 `knowledge_graph.py` 的 `sync_from_markdown()` 被动注册到 `graph.json`。元数据（tags、summary）需要另行调用 `add_node()` 手动添加。

**问题**：
- 无结构化元数据 → 无法渐进式发现
- 无法被外部 Agent 检索和理解
- graph.json 与 .md 文件不同步时失去一致性

### 3.2 目标格式

所有知识文档采用 SKILL.md 的 **YAML frontmatter + Markdown body** 格式：

```markdown
---
name: memory-architecture
description: Three-tier memory system design for AI agents — working memory,
  short-term memory with rolling summaries, and long-term memory with
  vector + knowledge graph hybrid storage.
tags:
  - memory
  - architecture
  - agent-design
  - chromadb
created_at: 2026-05-22T10:00:00+08:00
updated_at: 2026-05-23T14:30:00+08:00
---

# 记忆系统架构

## 三层设计

### 1. 工作记忆层
当前任务的即时上下文，容量约 7±2 项...

### 2. 短期记忆层
会话级的完整对话历史 + Rolling Summary 压缩...
```

### 3.3 升级 `knowledge_graph.py`

```python
# 新增功能

def parse_frontmatter(md_path: str) -> dict:
    """从 .md 文件中提取 YAML frontmatter。
    返回 {"name", "description", "tags", "created_at", "updated_at", ...}
    """

def sync_from_frontmatter(garden_dir: str = None) -> dict:
    """扫描所有 .md 文件，从 frontmatter 提取元数据同步到 graph.json。
    替代现有的 sync_from_markdown()（后者只取第一行标题）。
    自动：
      - name → node slug
      - description → node.summary
      - tags → node.tags
      - updated_at → node.updated_at
    """

def write_frontmatter(md_path: str, metadata: dict) -> None:
    """向 .md 文件写入/更新 YAML frontmatter。
    如果已有 frontmatter，合并更新；如果没有，在文件头插入。
    """

def discover_knowledge(garden_dir: str = None) -> list[dict]:
    """渐进式发现：只解析 frontmatter，不加载 body。
    返回 [{name, description, tags, updated_at, path}, ...]
    供 Agent 启动时注入 system prompt。
    """
```

### 3.4 知识发现流程升级

```
启动时（Discovery）:
  discover_knowledge() → 只读 frontmatter → 注入 system prompt
  ┌─────────────────────────────────────────────┐
  │ Available knowledge:                        │
  │   memory-architecture: Three-tier memory... │
  │   rag-architecture: RAG retrieval design... │
  │   agent-personality: Emergent identity...   │
  │   ...                                        │
  └─────────────────────────────────────────────┘
  Token cost: ~100 tokens / document

查询时（Activation）:
  Agent uses knowledge_search("memory") →
    匹配 frontmatter 的 name + description + tags →
    加载匹配文档的 body →
    注入对话上下文

引用时（On-Demand）:
  Body 中引用的 references/*.md → 按需加载
```

### 3.5 向后兼容

对没有 frontmatter 的旧 `.md` 文件：

```python
def upgrade_legacy_doc(md_path: str) -> dict:
    """将旧格式 .md 升级为新格式。
    - 从文件名推断 name
    - 从第一行标题推断 description
    - 从 graph.json 查找已有的 tags/summary
    - 写入 frontmatter
    """
```

提供 `knowledge_upgrade` 工具，Agent 可一键升级所有旧格式知识文档。

---

## 四、新增/修改文件清单

| 文件 | 操作 | 内容 |
|------|------|------|
| `tain_agent/evolution/skill_exporter.py` | **新增** | Tool→Skill 导出引擎 |
| `tain_agent/tools/forged/export_as_skill.py` | **新增** | Agent 可调用的 Skill 导出工具 |
| `tain_agent/tools/forged/knowledge_graph.py` | **修改** | 新增 frontmatter 解析/写入/发现 |
| `tain_agent/tools/forged/knowledge_upgrade.py` | **新增** | 旧格式知识文档批量升级 |
| `tain_agent/evolution/exporter.py` | **修改** | Step 3 增加 skills/ 输出 |
| `tain_agent/runtime/tui.py` | **修改** | 启动时注入知识 frontmatter 摘要 |

---

## 五、实施任务分解

### Sprint 4.1：Skill 导出引擎 (方向 2)

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 4.1.1 | `SkillMetadata` — frontmatter 生成器 | [skill_exporter.py](tain_agent/evolution/skill_exporter.py) | `from_tool_meta()` 从 .meta.json 生成 YAML frontmatter；`to_yaml()` 序列化 |
| 4.1.2 | `SkillBodyGenerator` — body 自动生成 | [skill_exporter.py](tain_agent/evolution/skill_exporter.py) | `from_python_code()` AST 分析 → 参数文档 + docstring；`from_knowledge_doc()` 提取 markdown body |
| 4.1.3 | `SkillExporter.export_tool_as_skill()` | [skill_exporter.py](tain_agent/evolution/skill_exporter.py) | 单工具导出：读 .meta.json + .py → 生成 SKILL.md + scripts/main.py + references/schema.json |
| 4.1.4 | `SkillExporter.export_all_tools()` | [skill_exporter.py](tain_agent/evolution/skill_exporter.py) | 批量导出所有 forged tools 为 Skills |
| 4.1.5 | `validate_skill()` | [skill_exporter.py](tain_agent/evolution/skill_exporter.py) | 校验 name 格式、description 长度、目录结构完整性 |
| 4.1.6 | `export_as_skill` 工具 | [export_as_skill.py](tain_agent/tools/forged/export_as_skill.py) | Agent 可调用：选择单个工具导出为标准 Skill |
| 4.1.7 | 集成到 export pipeline | [exporter.py](tain_agent/evolution/exporter.py) | Step 3 增加 `skills/` 输出目录 |

### Sprint 4.2：知识库标准化 (方向 4)

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 4.2.1 | `parse_frontmatter()` | [knowledge_graph.py](tain_agent/tools/forged/knowledge_graph.py) | 解析 YAML frontmatter，需 `pip install pyyaml` |
| 4.2.2 | `write_frontmatter()` | [knowledge_graph.py](tain_agent/tools/forged/knowledge_graph.py) | 写入/更新 frontmatter 到 .md 文件 |
| 4.2.3 | `sync_from_frontmatter()` | [knowledge_graph.py](tain_agent/tools/forged/knowledge_graph.py) | 从 frontmatter 同步到 graph.json（替代旧 sync_from_markdown） |
| 4.2.4 | `discover_knowledge()` | [knowledge_graph.py](tain_agent/tools/forged/knowledge_graph.py) | 渐进式发现：只解析 frontmatter，不加载 body |
| 4.2.5 | `upgrade_legacy_doc()` | [knowledge_graph.py](tain_agent/tools/forged/knowledge_graph.py) | 将无 frontmatter 的旧 .md 升级为新格式 |
| 4.2.6 | `knowledge_upgrade` 工具 | [knowledge_upgrade.py](tain_agent/tools/forged/knowledge_upgrade.py) | Agent 可调用：批量升级旧知识文档 |
| 4.2.7 | 系统提示注入发现摘要 | [tui.py](tain_agent/runtime/tui.py) / cognitive_loop | 启动时加载 `discover_knowledge()` 摘要到 system prompt |

### Sprint 4.3：端到端验证

| # | 任务 | 说明 |
|---|------|------|
| 4.3.1 | 单工具导出验证 | 取 regression_tester 导出为 Skill → 校验 SKILL.md + 目录结构 |
| 4.3.2 | 批量导出验证 | 全部 8 个 forged tools 导出 → 校验每个 Skill 合法性 |
| 4.3.3 | 知识升级验证 | 旧 .md → upgrade → 校验 frontmatter 完整性 |
| 4.3.4 | 渐进发现验证 | discover_knowledge() → 校验只返回 frontmatter 摘要，不加载 body |
| 4.3.5 | 外部消费验证 | 导出的 Skill 放入 `.claude/skills/` → Claude Code 能否识别 |
| 4.3.6 | Phase 3 导出完整性 | export pipeline 输出同时包含 tools/ 和 skills/ |

---

## 六、依赖关系

```
Sprint 4.1 (Skill 导出)
  4.1.1 → 4.1.2 → 4.1.3 → 4.1.4 → 4.1.7
                        └──→ 4.1.5
                        └──→ 4.1.6

Sprint 4.2 (知识标准化)  
  4.2.1 → 4.2.2 → 4.2.3 → 4.2.4 → 4.2.7
                   └──→ 4.2.5 → 4.2.6

Sprint 4.3 (验证) — 等待 4.1 + 4.2 完成
  4.3.1 → 4.3.2 → 4.3.3 → 4.3.4 → 4.3.5 → 4.3.6
```

Sprint 4.1 和 4.2 可并行开发，互不依赖。

---

## 七、设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Skill 输出放哪里？ | `dist/{name}/skills/` 与 `tools/` 并列 | 双格式共存，内部用 `tools/`，外部消费用 `skills/` |
| .meta.json 保留吗？ | 保留，并复制到 `references/schema.json` | 回厂升级需要原始元数据 |
| 知识文档格式 | SKILL.md 的 frontmatter 子集（name, description, tags, timestamps） | 不强制完整的 Skill 结构，只取元数据层 |
| YAML 解析依赖 | `pyyaml`（已有 pip 依赖） | requirements.txt 已包含 pyyaml |
| 旧知识文档处理 | 自动升级 + 手动工具两种路径 | 自动确保不丢数据，手动给 Agent 控制权 |
| name 字段命名规则 | 遵守 agentskills.io 规范（小写+连字符），工具名中的下划线自动转换 | `regression_tester` → `regression-tester` |
