# Agent 核心重构 · 设计文档

**日期**: 2026-05-30
**来源**: Agent 自演进模块升级讨论
**范围**: Agent 内核 + 7 个插件协议化子系统 + PRAL 循环重构
**目标**: 以核心-插件架构替代当前 Mixin 模式，为预设角色 Agent 构建完整的身份、记忆、技能、工具、知识、工作流、协作体系

---

## 1. 架构总览

### 1.1 核心-插件架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      Agent Kernel                                │
│                                                                  │
│   PRAL 认知循环  →  生命周期管理  →  插件编排  →  事件路由        │
│                                                                  │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│   │ Perceive │→│  Reason  │→│   Act    │→│  Learn   │          │
│   └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│        ↑                                            │            │
│        └──────────── cycle loop ────────────────────┘            │
└───────────────────┬──────────────────────────────────────────────┘
                    │ PluginProtocol
        ┌───────────┼───────────┬───────────┬───────────┐
        ▼           ▼           ▼           ▼           ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐
  │ Identity │ │ Memory   │ │ Skill    │ │ Tool     │ │ ...     │
  │ Plugin   │ │ Plugin   │ │ Plugin   │ │ Plugin   │ │         │
  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘
```

Kernel 只负责 PRAL 循环编排和插件生命周期管理。所有领域逻辑归入插件。

### 1.2 设计原则

- **协议驱动**：插件通过 `PluginProtocol` 定义接口契约，消除当前 Mixin 的隐式依赖
- **插件隔离**：插件间不直接通信，通过 Kernel 事件路由协调
- **独立持久化**：每个插件管理自己的存储，不共享文件
- **热插拔**：演化模式和 Agent 类型决定加载哪些插件
- **复用底线**：ToolPlugin 包装现有 `ToolRegistry` + `ToolForge` + `ToolSandbox`；LLM backend 保持独立

---

## 2. PluginProtocol 接口

每个插件必须实现：

```python
class PluginProtocol:
    # 生命周期
    def initialize(ctx: AgentContext) -> None
    def shutdown() -> None

    # 状态
    def health_check() -> HealthStatus           # ok / warning / critical + 指标
    def snapshot() -> dict                       # 状态导出
    def restore(snapshot: dict) -> None          # 状态恢复

    # PRAL 钩子（可选）
    def on_cycle_start(cycle: int) -> None
    def on_cycle_end(cycle: int) -> None
    def enrich_prompt(base: str) -> str          # 向系统提示注入上下文
    def on_llm_response(response) -> None        # 观察 LLM 输出

class HealthStatus:
    status: Literal["ok", "warning", "critical"]
    metrics: dict[str, float]
    alerts: list[str]
```

### AgentContext — 插件间共享上下文

```python
class AgentContext:
    agent_name: str
    agent_id: str              # 全局唯一 ID
    evolution_mode: str        # "specified" | "chaos"
    workspace_path: Path
    config: dict
    kernel_version: str
```

---

## 3. Agent Kernel

### 3.1 PRAL 认知循环（重构后）

```
for cycle in 1..MAX:

  ① PERCEIVE ──────────────────────────────────────────────
     ├─ 收集环境状态 (workspace, time, resource usage)
     ├─ memory.recall(当前上下文) → 相关情景记忆
     ├─ knowledge.query(当前话题) → 相关知识
     ├─ collaboration.check_inbox() → 新消息
     └─ workflow.status() → 活跃工作流状态

  ② REASON ───────────────────────────────────────────────
     ├─ 构建 base system_prompt
     ├─ identity.enrich_prompt()    → 身份上下文
     ├─ memory.enrich_prompt()      → 相关记忆
     ├─ knowledge.enrich_prompt()   → 知识
     ├─ skill.enrich_prompt()       → 可用技能
     ├─ drive_system.enrich_prompt() → 驱动力
     └─ LLM 调用 → 思考 + 工具调用 + 技能调用

  ③ ACT ──────────────────────────────────────────────────
     ├─ 解析 LLM 输出 (text + tool_calls + skill_invocations)
     ├─ 执行 tool → tool_plugin.call()
     ├─ 执行 skill → skill_plugin.execute()
     ├─ 执行 workflow_step → workflow_plugin.advance()
     ├─ 收集结果 → 追加到 conversation
     └─ 各插件 on_llm_response()

  ④ LEARN ────────────────────────────────────────────────
     ├─ memory.encode(重要事件)         → 编码情景记忆
     ├─ knowledge.ingest(新信息)         → 暂存动态知识基
     ├─ skill.practice(skill, result)   → 更新技能熟练度
     ├─ identity.evolve(observations)   → 更新人格特质
     ├─ drive_system.record_action()    → 更新驱动力
     ├─ 各插件 on_cycle_end(cycle)
     ├─ 检查阶段转换 (explore → work)
     └─ conversation.trim() + checkpoint()
```

### 3.2 Kernel 职责 vs 插件职责

| 维度 | Kernel (主线) | 插件 (钩子) |
|------|--------------|------------|
| 每轮必做 | PRAL 四阶段 | on_cycle_start/end, enrich_prompt |
| 按条件触发 | 阶段转换检测 | consolidation, 成熟度检查, 新鲜度检查 |
| 异步/定时 | — | 声誉计算, 记忆衰减, 知识冲突检测 |

### 3.3 两种演化模式

| 模式 | 用途 | 插件加载 | 特点 |
|------|------|---------|------|
| **Specified** | 主力 | 全部 7 个插件 | 从角色设定初始化身份，自主闭合演化循环 |
| **Chaos** | 实验观察 | 仅 Identity + Memory + Tool | 空白身份启动，保留 Curiosity 驱动力，观察行为 |

**Chaos 模式 PRAL 行为**：未加载的插件在 PRAL 循环中对应调用返回空值。例如：
- `knowledge.query()` → `[]`（无知识插件）
- `collaboration.check_inbox()` → `[]`（无协作插件）
- `skill.enrich_prompt()` → 返回原文本不变

Kernel 在所有插件调用前检查 `plugin is not None`，确保 Chaos 模式下 PRAL 循环不崩溃。

---

## 4. Identity Plugin — 身份档案

### 4.1 数据模型

```
AgentIdentity
├── 核心身份
│   ├── agent_id: str                    全局唯一 ID
│   ├── name: str                        Agent 名称
│   ├── role: str                        角色设定
│   ├── role_description: str            角色详细描述
│   └── evolution_mode: str              "specified" | "chaos"
│
├── 专业能力
│   └── expertise_domains: list[DomainExpertise]
│       {domain: str, proficiency: 0-5, evidence: str[], acquired_at: str}
│
├── 价值体系
│   └── values: list[Value]
│       {name: str, priority: 1-10, description: str, source: str}
│
├── 行为边界
│   └── constraints: BehaviorConstraints
│       {allowed_categories: [], blocked_categories: [],
│        max_autonomy_level: 1-5, requires_human_for: []}
│
├── 使命与目标
│   ├── mission: str                     核心使命陈述
│   └── goals: list[Goal]                目标层级树
│       {id, title, parent_id, status, progress, children: [...]}
│
├── 成长档案
│   ├── skill_catalog: list[SkillRef]    已掌握技能引用
│   └── experience: ExperienceLevel
│       {overall: 1-10, domain_breakdown: {domain: level}}
│
├── 协作偏好
│   └── collaboration: CollaborationPrefs
│       {preferred_roles: [], communication_style: str,
│        team_size_preference: int, availability: str}
│
├── 人格特质（继承现有 personality.py）
│   └── traits: {category → [{value, confidence, emergence_story}]}
│       7 类别: values, communication_style, interests, quirks,
│               self_description, relationship_stance, growth_orientation
│
└── 演化历史
    └── evolution_log: list[EvolutionEvent]
        {timestamp, event_type, description, version_from, version_to}
```

### 4.2 关键行为

- **身份觉醒**：Specified Agent 从 `role` + `role_description` 初始化所有字段；Chaos Agent 从空白开始
- **渐进式填充**：`expertise_domains`、`values`、`skill_catalog` 随时间丰富，不是一次性赋值
- **约束升级**：`max_autonomy_level` 初始较低，通过评估关卡后逐级提升
- **人格特质保留**：现有 7 类人格特质作为身份档案的子集，记录行为倾向而非角色设定

---

## 5. Memory Plugin — 仿生记忆系统

### 5.1 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    MemoryPlugin                              │
│                                                             │
│  ┌──────────────────┐                                       │
│  │  工作记忆 (WM)    │  ← 会话级，容量限制 (~200 msg)         │
│  │  Working Memory   │    当前对话上下文 + 本轮工具调用结果    │
│  └────────┬─────────┘                                       │
│           │ consolidate (会话结束时)                           │
│           ▼                                                 │
│  ┌──────────────────┐                                       │
│  │  情景记忆 (EM)    │  ← 持久化，带衰减曲线                   │
│  │  Episodic Memory  │    重要事件、决策、成功/失败经验         │
│  │  [向量检索]       │    importance, decay_rate,              │
│  │                   │    last_recalled, recall_count         │
│  └────────┬─────────┘                                       │
│           │ knowledge extraction (周期性)                      │
│           ▼                                                 │
│  ┌──────────────────┐                                       │
│  │  语义记忆 (SM)    │  ← 持久化，知识图谱                      │
│  │  Semantic Memory  │    从情景中抽象出的持久知识              │
│  │  [图数据库]       │    实体 + 关系 + 置信度                  │
│  └──────────────────┘                                       │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 记忆衰减模型

每次情景记忆包含：

```python
class EpisodicMemory:
    content: str
    importance: float           # 初始重要性 0-1
    base_decay_rate: float      # 重要性越高衰减越慢
    created_at: timestamp
    last_recalled_at: timestamp
    recall_count: int           # 唤起次数
    associations: list[str]     # 关联的其他记忆 ID

    # current_strength = importance × e^(-decay_rate × days)
    #                   × (1 + log(1 + recall_count) × 0.1)
    #                   × boost_factor(last_recalled_at)
```

- 强度低于 0.05 的记忆进入"遗忘"状态
- 周期性 `consolidate()` 从 EM 提取模式写入 SM

### 5.3 记忆操作

| 操作 | 描述 |
|------|------|
| `encode(content, importance)` | 写入新情景记忆 |
| `recall(query, k=10)` | 向量语义召回 top-k |
| `recent(n=20)` | 按时间排序 |
| `reinforce(memory_id)` | 唤起加强 |
| `consolidate()` | EM → SM 知识提取 |
| `forget(threshold=0.05)` | 清除弱记忆 |
| `summarize(time_range)` | 时间段摘要 |

### 5.4 与工作记忆的交互

- 每轮 `enrich_prompt()` 从 EM 召回相关记忆注入系统提示
- 重要事件（锻造成功/失败、关键决策、人格发现）自动编码为情景记忆
- WM 在会话结束时触发 consolidate

### 5.5 存储

- WM：内存 dict
- EM：SQLite + 向量索引
- SM：轻量图存储（NetworkX + JSON）

---

## 6. Skill Plugin — 复合技能

### 6.1 数据模型

```python
class Skill:
    name: str                   # 唯一标识
    display_name: str           # 可读名称
    description: str
    category: str               # coding, analysis, creation, communication

    # 技能组成
    tools: list[str]            # 依赖的工具名
    knowledge_refs: list[str]   # 关联的知识节点 ID
    workflow: list[Step]        # 执行步骤编排

    # 成熟度
    maturity: MaturityLevel    # novice → apprentice → skilled → expert → master
    usage_count: int
    success_rate: float
    last_used_at: timestamp

    # 元信息
    created_by: str             # "forged" | "inherited" | "composed"
    parent_skill: str | None
    prerequisites: list[str]
    version: int

class Step:
    type: str                   # tool_call | llm_think | human_approval | condition
    tool_name: str | None
    prompt_template: str | None
    condition: str | None
    on_failure: str             # retry | skip | abort
```

### 6.2 成熟度升级规则

```
novice → apprentice: usage_count >= 5
apprentice → skilled: success_rate >= 0.5 AND usage_count >= 20
skilled → expert: success_rate >= 0.8 AND usage_count >= 50
expert → master: success_rate >= 0.9 AND usage_count >= 100 AND has_taught >= 1
```

### 6.3 技能组合

Agent 组合已有技能创建新技能。新技能继承子技能的所有 tools 和 knowledge_refs。初始成熟度 = min(子技能成熟度) - 1。

### 6.4 SkillPlugin 接口

| 方法 | 描述 |
|------|------|
| `register(skill: Skill)` | 注册新技能 |
| `get(name) → Skill` | 获取技能定义 |
| `list_skills(maturity=None) → list[Skill]` | 列出技能 |
| `practice(name, result: bool)` | 记录一次使用 |
| `teach(name, target_agent_id)` | 传授给另一个 Agent |
| `compose(name, skill_refs, workflow) → Skill` | 组合技能 |

---

## 7. Tool Plugin

### 7.1 与现有代码的关系

```
现有模块                            →  新 ToolPlugin
───────────────────────────────────────────────
tools/registry.py (ToolRegistry)     →  ToolPlugin (核心)
tools/forge.py   (ToolForge)         →  ToolPlugin.forge()
tools/forge.py   (ToolSandbox)       →  ToolPlugin._sandbox()
tools/primal.py  (10 primal tools)   →  保持不变，plugin 初始化时注册
tools/base.py    (ToolBase)          →  工具基类，保持不变
```

### 7.2 闭合演化循环

核心改进——增加 **Generate** 阶段，让 LLM 自主生成工具代码：

```
Analyze → Design → Generate → Forge → Verify → Register
                      ↑                    │         │
                      │ LLM 生成代码        │         │
                      │ 单次最多重试 3 次    │         │
                      └─── 失败回退 ────────┘         │
                                                      │
                        3 次仍失败 → 记录失败报告        │
                        → 降低缺口优先级                │
                        → 等待下轮评估重新尝试           │
                                                      │
                                          人类审批 (autonomy_level < 4)
```

### 7.3 ToolPlugin 接口

```python
class ToolPlugin(PluginProtocol):
    def list_tools() -> dict[str, ToolInfo]
    def call(name: str, **kwargs) -> ToolResult
    def register_primitives()
    def forge(name, description, code) -> ForgeResult
    def needs_human_approval(result: ForgeResult) -> bool
    def audit_forged_tools() -> list[AuditFinding]
    def rollback(tool_name: str)
    def request_generation(spec: ImprovementSpec) -> str   # LLM 生成代码
    def run_full_forge_cycle(spec: ImprovementSpec) -> PipelineResult
```

### 7.4 安全边界（继承现有设计）

- 锻造工具只能在 `agent_workspace/<name>/` 内读写
- 禁止 `os.system`、`subprocess`、`exec`、`eval`
- AST 白名单导入限制
- 60s 超时执行
- 新工具注册前必须通过回归测试

---

## 8. Knowledge Plugin — 知识生命周期

### 8.1 双层知识架构

```
┌──────────────────────────────────────────────────────────────┐
│                    KnowledgePlugin                            │
│                                                              │
│  ┌──────────────────────────┐                                │
│  │  动态知识基 (Dynamic)     │  ← 会话级，临时、待验证           │
│  │  - 本轮新获取的事实        │    置信度低，寿命短               │
│  │  - Web 搜索结果            │    验证后 → 知识图谱 or → 丢弃    │
│  │  - LLM 推断               │                                │
│  └──────────┬───────────────┘                                │
│             │ verify + consolidate                            │
│             ▼                                                │
│  ┌──────────────────────────┐                                │
│  │  结构化知识图谱 (Stable)   │  ← 持久化，验证过的可靠知识       │
│  │  - 实体 (Entity)          │    可查询、推理、传授             │
│  │  - 关系 (Relation)        │                                │
│  │  - 置信度 (Confidence)    │                                │
│  └──────────────────────────┘                                │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 数据模型

```python
class Entity:
    id: str              # 如 "python_asyncio"
    name: str
    type: str            # concept, tool, person, event, project
    properties: dict
    sources: list[str]   # 来源引用
    created_at, updated_at: timestamp

class Relation:
    subject: str         # entity ID
    predicate: str       # depends_on, implements, requires, conflicts_with
    object: str          # entity ID
    confidence: float    # 0-1
    evidence: str

class KnowledgeSnapshot:
    timestamp, entities_count, relations_count,
    new_entities, deleted_entities
```

### 8.3 知识生命周期

```
获取 → 暂存 → 验证 → 存储 → 关联 → 维护 → 分享 → 退役
  │      │      │      │      │      │      │      │
  │      │      │      │      │      │      │      └─ 过期/被证伪
  │      │      │      │      │      │      └─ 传授给其他 Agent
  │      │      │      │      │      └─ 新鲜度检查 + 更新
  │      │      │      │      └─ 建立实体间关系
  │      │      │      └─ 写入知识图谱
  │      │      └─ 多源交叉验证
  │      └─ 写入动态知识基
  └─ 从对话/搜索/工具输出中提取
```

### 8.4 核心机制

**冲突检测**：新知识与已有知识矛盾时 → 比较置信度和来源质量 → LLM 裁决 → 保留强方，弱方归档。

**新鲜度维护**：每个实体有 TTL。过期实体触发 `knowledge_freshness` 重新验证。

**知识传承**：Agent A 导出知识图谱子图 → Agent B 导入时自动验证并建立关联。

### 8.5 与 Memory Plugin 的边界

| | Memory Plugin | Knowledge Plugin |
|---|---|---|
| 存储 | 个人经验（"我做了什么"） | 客观知识（"世界是怎样"） |
| 内容 | 情景记忆 + 行为模式 | 事实 + 概念 + 关系 |
| 主观性 | 第一人称 | 第三人称 |
| 衰减 | 会遗忘，会泛化 | 会过时，会被证伪 |

---

## 9. Workflow Plugin — 多步骤编排

### 9.1 数据模型

```python
class Workflow:
    name, description: str
    steps: list[WorkflowStep]
    state: WorkflowState    # pending → running → paused → completed → failed
    context: dict           # 步骤间传递数据
    created_at, started_at, completed_at: timestamp

class WorkflowStep:
    id: str
    type: StepType          # tool_call | skill_invoke | llm_reason | human_review
                            # | conditional | parallel | sub_workflow
    config: dict
    depends_on: list[str]   # 前置步骤 ID
    retry_policy: RetryPolicy
    timeout_seconds: int

class RetryPolicy:
    max_retries: int = 3
    backoff: str = "exponential"
    on_failure: str = "abort"   # retry | skip | abort | fallback
```

### 9.2 执行引擎

- 解析步骤依赖 → 构建 DAG
- 拓扑排序 → 确定执行顺序
- 并行执行无依赖步骤
- 条件分支 → 根据步骤结果选择路径
- 人工审批 → 暂停等待
- 失败处理 → 按 retry_policy 重试/跳过/中断

### 9.3 工作流来源

| 来源 | 示例 |
|------|------|
| 技能定义 | 每个 Skill 包含一个 workflow |
| 目标分解 | 大目标自动拆解为子目标 → 生成工作流 |
| 人类指定 | 用户直接下发的任务编排 |
| LLM 规划 | Agent 自己规划 |
| 模板库 | 常见任务模式 |
| 学习生成 | 从成功的行为序列中提取 |

### 9.4 目标 → 工作流自动转换

```
Goal: "学会 FastAPI 并创建 REST 服务"
        │
        ▼ (LLM 规划)
Workflow:
  1. web_search("FastAPI tutorial")
  2. read_and_summarize(results)
  3. write_file("main.py", api_code)
  4. execute_code("main.py", test_request)
  5. knowledge.update(FastAPI entity)
  6. skill.register("FastAPI REST 开发")
```

---

## 10. Collaboration Plugin — Agent 社会

### 10.1 三层模型

```
Layer 3: Agent 社会  ───  声誉、社交图、知识传承、社区规范
Layer 2: Agent 团队  ───  组队、分工、协作目标、角色分配
Layer 1: 消息通道    ───  点对点消息、广播、订阅
```

### 10.2 Layer 1: 消息通道

在现有 MessageBus 上升级——增加消息类型、优先级、TTL、广播模式。

```python
class Message:
    id, from_agent: str
    to_agent: str                # "*" 表示广播
    type: str                    # chat | task | knowledge | alert | handshake
    content: str
    reply_to: str | None
    priority: int                # 0=低 1=正常 2=紧急
    ttl_seconds: int
    created_at: timestamp
```

### 10.3 Layer 2: Agent 团队

```python
class Team:
    id, name, mission: str
    members: list[TeamMember]
    created_at, disbanded_at: timestamp

class TeamMember:
    agent_id: str
    role: str                    # lead | member | observer
    responsibilities: list[str]
    joined_at: timestamp

class TeamTask:
    id, team_id, title, description: str
    assigned_to: list[str]
    status: TaskStatus
    dependencies: list[str]      # 依赖的 Task ID
    deadline, result: timestamp | None
```

### 10.4 Layer 3: Agent 社会

| 机制 | 描述 |
|------|------|
| **声誉系统** | 协作后互评，声誉影响团队邀请、任务分配 |
| **知识传承** | expert/master Agent 可将技能传授给其他 Agent |
| **社交发现** | 搜索其他 Agent 的公开技能，寻找协作者 |
| **竞争与合作** | 多个 Agent 可认领同一目标的不同方案 |

### 10.5 与现有工具的关系

现有的 `discover_agents`、`send_message`、`check_messages`、`get_conversation_history` 被 CollaborationPlugin 完全替代。

---

## 11. 存储架构

每个插件独立管理存储，不共享文件：

| 插件 | 存储方式 | 路径 |
|------|---------|------|
| Kernel | JSON | `workspace/version.json` |
| Identity | JSON | `workspace/identity/profile.json` |
| Memory (EM) | SQLite + Vector | `workspace/memory/episodic.db` |
| Memory (SM) | NetworkX + JSON | `workspace/memory/semantic.json` |
| Skill | JSON | `workspace/skills/catalog.json` |
| Tool | 现有 registry + JSON | `workspace/forged_tools/` |
| Knowledge | SQLite + Vector | `workspace/knowledge/graph.db` |
| Workflow | JSON | `workspace/workflows/` |
| Collaboration | SQLite (共享) | `agent_workspace/_social.db` |

Collabration 数据库是唯一 Agent 间共享的存储（替代现有 `_message_bus.db` + `_registry.json`）。

---

## 12. 迁移策略

从当前 Mixin 架构迁移到核心-插件架构分三个阶段：

### 阶段 1: 插件接口层（不破坏现有代码）

1. 定义 `PluginProtocol` 接口
2. 每个现有子系统创建对应的 Adapter，实现 `PluginProtocol`
3. AgentKernel 初始化时加载 Adapter
4. 现有代码在 Adapter 内部继续运行

### 阶段 2: 逐插件替换

1. 先替换独立性最强的插件（Identity → Memory → Knowledge → Skill）
2. 每个插件替换后独立测试
3. 保留 Adapter 作为回退路径

### 阶段 3: 清理

1. 删除旧的 Mixin 文件
2. 移除 Adapter
3. 更新 CLI 和 Web UI 适配新 API

---

## 13. 安全与隔离

继承当前框架的安全设计：

- **工作空间隔离**：Agent 只能在 `agent_workspace/<name>/` 内读写
- **工具执行安全**：线程池超时执行，AST 沙箱，导入白名单
- **自修改保护**：`self_modify` 禁止修改受保护路径
- **消息总线安全**：纯数据，不执行代码
- **新增—自主生成安全**：LLM 生成的工具代码必须通过 AST 扫描 + 回归测试 + 人类审批（autonomy_level < 4）

---

## 14. 文件结构（目标）

```
tain_agent/
  kernel/                        # Agent 内核（新）
    __init__.py                  # AgentKernel 类
    pral.py                      # PRAL 认知循环
    lifecycle.py                 # 生命周期管理
    protocol.py                  # PluginProtocol + AgentContext + HealthStatus
    context.py                   # AgentContext 构建

  plugins/                       # 插件实现（新）
    __init__.py
    identity/
      __init__.py                # IdentityPlugin
      model.py                   # AgentIdentity 数据模型
    memory/
      __init__.py                # MemoryPlugin
      episodic.py                # 情景记忆
      semantic.py                # 语义记忆
      decay.py                   # 衰减引擎
    skill/
      __init__.py                # SkillPlugin
      model.py                   # Skill, Step, MaturityLevel
      composer.py                # 技能组合引擎
    tool/
      __init__.py                # ToolPlugin（包装现有 tools/）
      forge_cycle.py             # 闭合演化循环
    knowledge/
      __init__.py                # KnowledgePlugin
      graph.py                   # 知识图谱引擎
      lifecycle.py               # 冲突检测、新鲜度维护
    workflow/
      __init__.py                # WorkflowPlugin
      engine.py                  # DAG 编排引擎
    collaboration/
      __init__.py                # CollaborationPlugin
      team.py                    # 团队管理
      reputation.py              # 声誉系统
      bus.py                     # 消息通道（升级版）

  core/                          # 保留已稳定的基础设施
    llm.py                       # LLM backend（不变）
    personality.py               # 人格特质（被 IdentityPlugin 引用）
    drives.py                    # 驱动力引擎（被 Kernel 直接使用）
    conversation.py              # 对话管理（不变）
    bootstrap.py                 # 系统提示模板（重构）
    # ... 其他保留模块

  tools/                         # 工具系统（ToolPlugin 包装）
    registry.py, forge.py, primal.py, base.py  # 保持不变

  evolution/                     # 演化子系统 → 逻辑重新分配到各插件
    # quality_gate.py            → Identity Plugin (评估体系)
    # pipeline.py                → Tool Plugin (闭合循环)
    # reporter.py                → Kernel (统一报告生成)
    # improvement_loop.py        → Kernel (统一调度)
    # sub_agent.py, exporter.py   → 保留，后续重构

  runtime/                       # 独立运行时内核（IDE 嵌入目标）
    # 精简为 Kernel + Identity + Skill + Tool
    # 无 Memory/Knowledge/Workflow/Collaboration
```

---

## 15. 依赖关系

```
AgentKernel
  ├── PluginProtocol (定义的接口)
  ├── LLM Backend (直接依赖，不通过插件)
  ├── DriveSystem (直接依赖，不通过插件)
  ├── Conversation (直接依赖，不通过插件)
  │
  ├── IdentityPlugin
  │     └── Personality (现有模块，内部引用)
  │
  ├── MemoryPlugin
  │     └── VectorStore (现有模块)
  │
  ├── SkillPlugin
  │     ├── ToolPlugin (技能调用工具)
  │     └── KnowledgePlugin (技能引用知识)
  │
  ├── ToolPlugin
  │     └── ToolRegistry + ToolForge + ToolSandbox (现有模块)
  │
  ├── KnowledgePlugin
  │     └── MemoryPlugin.semantic (双向：知识 ←→ 语义记忆)
  │
  ├── WorkflowPlugin
  │     ├── ToolPlugin (执行工具步骤)
  │     └── SkillPlugin (执行技能步骤)
  │
  └── CollaborationPlugin
        ├── IdentityPlugin (Agent 画像用于发现)
        └── SkillPlugin (知识传承)
```

插件间不直接 import。需要跨插件协调时，通过 Kernel 的事件路由机制：

```python
# Kernel 中的事件路由
class AgentKernel:
    def dispatch(self, event: str, *args, **kwargs) -> Any:
        """路由事件到对应插件。事件名格式: 'plugin_name.action'"""
        routes = {
            "tool.call": self.tool_plugin.call,
            "tool.forge": self.tool_plugin.forge,
            "skill.execute": self.skill_plugin.execute,
            "knowledge.query": self.knowledge_plugin.query,
            "memory.recall": self.memory_plugin.recall,
            "workflow.advance": self.workflow_plugin.advance,
            "collaboration.send": self.collaboration_plugin.send,
        }
        handler = routes.get(event)
        if handler:
            return handler(*args, **kwargs)
        return None
```

插件在自己内部持有 Kernel 的弱引用（`weakref`），通过回调而非直接 import 请求跨插件服务。

---

*设计文档完*
