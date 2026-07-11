# Agent Package Model — 重新定义 Agent 进化产物

**日期**: 2026-06-28
**状态**: 设计完成
**版本**: v1.0

---

## 1. 动机与背景

### 1.1 当前问题

AgentKernel v0.10.0 的 Agent 工作空间存在三个结构性缺陷：

**结构碎片化**：每个 Agent 的产出散落在 15+ 个子目录中（`identity/`, `memory/`, `knowledge/`, `poetry/`, `journal/`, `commitments/`, `reports/`, `forged_tools/`, `tests/`, `logs/`, `skill/`, `workflows/`, `collaboration/`, `state/`, `files/`），缺乏统一的"进化产物"概念。

**格式混杂**：JSON、JSONL、SQLite、纯文本、YAML 多种格式混杂，没有统一索引，跨 Agent 查询需要硬编码每个路径。

**运行时与产物不分**：PRAL 状态快照和持久化产出放在同一棵目录树下，`snapshot()/restore()` 需要协调 8 个插件各自的序列化逻辑。无法清晰地识别"什么是 Agent 的产出"、"什么是运行时的临时状态"。

### 1.2 目标

将 Agent 从一个"运行时实例 + 散落文件"重新定义为 **Agent Package（Agent 包）**——一个可版本化、可索引、可分发、可引用的第一性实体。

---

## 2. 核心设计：Agent Package Model

### 2.1 设计原则

| 原则 | 说明 |
|------|------|
| **包即 Agent** | Agent 不是运行时概念——包本身就是 Agent。运行时只是包的加载器。 |
| **分层抽象** | 包内内容按抽象层级垂直分层：Infrastructure → Capability → Cognitive → Expression |
| **索引即真理** | `manifest.json` 是唯一数据源。文件系统只是存储细节。 |
| **活体进化** | 包不是版本快照的导出物——它自身持续进化，版本号自动递增。 |
| **Polyglot 统一索引** | 不同产物保留各自最优格式（JSON、Markdown、SQLite、JSONL），manifest 统一索引。 |
| **产物 vs 运行时分界** | `_runtime/` 目录明确隔离临时状态，包分发时自动排除。 |

### 2.2 四层抽象模型

```
┌─────────────────────────────────────┐
│  L4 EXPRESSION（表达层）             │
│  artifacts, reports, lineage        │
│  对外输出、可分发产物、进化谱系        │
├─────────────────────────────────────┤
│  L3 COGNITIVE（认知层）              │
│  knowledge graph, memory, decisions │
│  identity, goals                    │
├─────────────────────────────────────┤
│  L2 CAPABILITY（能力层）             │
│  tools, skills, tests               │
│  可执行能力                          │
├─────────────────────────────────────┤
│  L1 INFRA（基础设施层）              │
│  runtime config, plugin deps        │
│  运行依赖声明                        │
├─────────────────────────────────────┤
│  _RUNTIME（运行时临时状态，不分发）    │
│  PRAL phase, conversations, cache   │
└─────────────────────────────────────┘
```

---

## 3. 包结构

### 3.1 目录布局

```
agent_workspace/
  packages/
    <agent-name>/
      manifest.json               # 统一索引 + 版本 + 依赖声明
      infra/                      # L1 基础设施（非 JSON 配置资源）
      capability/                 # L2 能力
        tools/                    # 锻造的工具 .py
        skills/                   # 技能目录
        tests/                    # 工具测试
      cognitive/                  # L3 认知
        knowledge/                # 知识图谱 + 文档
        memory/                   # episodic.db + semantic.json
        identity/                 # profile.json
        decisions.jsonl           # 决策流
      expression/                 # L4 表达
        artifacts/                # 创作产出（报告、诗歌、故事等）
        goals.json                # 目标树
        lineage.jsonl             # 进化谱系
      _runtime/                   # 运行时临时状态（不版本化、不分发）
        state/                    # PRAL 当前状态
        conversations/            # 对话缓存
        cache/                    # LLM 响应缓存
        locks/                    # 并发控制
```

### 3.2 manifest.json Schema

manifest.json 是包的唯一数据源——产物在文件系统中存在但不在 manifest → 视为不存在。manifest 中有条目但文件缺失 → 加载时报错。

```json
{
  "package": {
    "name": "SystemsArchitect",
    "version": "0.7.3",
    "kind": "agent",
    "evolution_mode": "specified",
    "created_at": "2026-06-15T10:30:00Z",
    "updated_at": "2026-06-28T08:12:00Z"
  },

  "infra": {
    "runtime": {
      "kernel_version": "0.11.0",
      "min_kernel_version": "0.10.0"
    },
    "plugins": {
      "tool": "^1.2.0",
      "knowledge": "^1.0.0",
      "collaboration": "^1.1.0"
    },
    "packages": {
      "code-review-skill": "^1.2.0",
      "web-scraper-toolset": "^0.5.0"
    },
    "llm": {
      "provider": "anthropic",
      "preferred_model": "claude-sonnet-4-6"
    }
  },

  "capability": {
    "tools": [
      {
        "name": "system_design",
        "version": "1.0.2",
        "path": "capability/tools/system_design.py",
        "hash": "sha256:abc123",
        "signature": "def system_design(requirements: str, constraints: dict) -> dict"
      }
    ],
    "skills": [
      {
        "name": "architecture_review",
        "maturity": "ADVANCED",
        "path": "capability/skills/"
      }
    ]
  },

  "cognitive": {
    "knowledge_graph": "cognitive/knowledge/graph.json",
    "memory": {
      "episodic": "cognitive/memory/episodic.db",
      "semantic": "cognitive/memory/semantic.json"
    },
    "decisions": "cognitive/decisions.jsonl",
    "identity": "cognitive/identity/profile.json"
  },

  "expression": {
    "artifacts": [
      {
        "type": "report",
        "title": "系统架构审计 v2",
        "path": "expression/artifacts/arch-audit-v2.md",
        "format": "markdown",
        "hash": "sha256:def456"
      }
    ],
    "goals": "expression/goals.json",
    "lineage": "expression/lineage.jsonl"
  }
}
```

### 3.3 包类型（kind）

| kind | 包含层级 | 说明 | 示例 |
|------|---------|------|------|
| `agent` | L1-L4 全部 | 完整的自治 Agent，有 PRAL 循环，可独立运行 | SystemsArchitect, Skeptic |
| `toolset` | L2 only | 纯能力包，被 agent 声明为依赖 | web-scraper-toolset |
| `skill` | L2 + 最小 L3 | 单个成熟度达标的技能 + 依赖的工具 | code-review-skill |

### 3.4 完整性校验

每个 manifest 中的产物条目都带 `hash` 字段（SHA-256）。包加载时校验所有声明文件的 hash。校验失败 → 包不可用，报错阻止加载。

---

## 4. AgentRuntime 最小内核

### 4.1 架构

AgentRuntime 取代 AgentKernel。只永驻 IdentityPlugin 和 MemoryPlugin，其余插件全部通过 manifest 的 `infra.plugins` 动态装配。

```
AgentRuntime(package)
  ├── IdentityPlugin      # 永驻
  ├── MemoryPlugin        # 永驻
  ├── PluginLoader        # 按 manifest 加载
  │     ├── ToolPlugin?         # manifest 声明则加载
  │     ├── KnowledgePlugin?    # manifest 声明则加载
  │     ├── CollaborationPlugin?# manifest 声明则加载
  │     ├── SkillPlugin?        # manifest 声明则加载
  │     ├── WorkflowPlugin?     # manifest 声明则加载
  │     └── EvaluationPlugin?   # manifest 声明则加载
  ├── Dispatch()          # 仅注册活跃插件的路由
  └── PRALLoop()          # 只调用已装配的插件
```

### 4.2 启动流程

1. **加载包**：读取 `manifest.json`，校验所有产物 hash
2. **解析依赖**：检查 `infra.plugins` 和 `infra.packages`，semver 匹配
3. **装配插件**：永驻 Identity + Memory，按声明加载其余
4. **初始化**：各插件 `initialize(ctx)`，恢复持久化状态
5. **运行 PRAL**：Perceive → Reason → Act → Learn 循环

### 4.3 PluginLoader

```python
class PluginLoader:
    """从 manifest 声明动态装配插件。不硬编码任何插件名。"""

    _registry: dict[str, type[PluginProtocol]] = {
        "identity":  IdentityPlugin,     # 永驻
        "memory":    MemoryPlugin,       # 永驻
        "tool":      ToolPlugin,         # 按需
        "skill":     SkillPlugin,        # 按需
        "knowledge": KnowledgePlugin,    # 按需
        "workflow":  WorkflowPlugin,     # 按需
        "collaboration": CollaborationPlugin, # 按需
        "evaluation": EvaluationPlugin, # 按需
    }

    async def assemble(self, manifest: Manifest, ctx: AgentContext) -> list[PluginProtocol]:
        plugins = [IdentityPlugin(), MemoryPlugin()]
        for name, version_spec in manifest.infra.plugins.items():
            plugin_cls = self._registry[name]
            if not semver_match(plugin_cls.version, version_spec):
                raise PluginVersionError(name, version_spec, plugin_cls.version)
            plugins.append(plugin_cls())
        return plugins
```

### 4.4 Dispatch 按需注册

Dispatch 不再预注册全部 8 个插件的路由。PluginLoader 装配完成后动态注册——只有活跃插件的路由存在。未注册路由的请求返回 `RouteNotFound`，调用方可据此降级。

### 4.5 AgentContext 重构

```python
@dataclass
class AgentContext:
    package: AgentPackage        # 包实体
    manifest: Manifest           # 解析后的 manifest
    config: dict                 # 主机 config.yaml
    active_plugins: list[str]    # 实际装配的插件名列表
```

---

## 5. 包内进化与版本化

### 5.1 进化模型

进化不再是外挂的 `AutonomousEvolutionLoop` 操作 Agent——而是 AgentPackage 自身的生命周期方法。每次进化是一个 **Mutation**——对包的某一层内容的原子变更，触发版本号自动递增。

### 5.2 语义化版本规则

| 变异层级 | 版本影响 | 示例 |
|---------|---------|------|
| `expression`（新增/修改 artifact、目标完成） | PATCH | 0.7.3 → 0.7.4 |
| `capability`（新工具、技能成熟度跃升） | MINOR | 0.7.3 → 0.8.0 |
| `cognitive`（知识图谱扩展、决策模式变化） | MINOR | 0.7.3 → 0.8.0 |
| `cognitive/identity`（人格特质显著变化） | MINOR | 0.7.3 → 0.8.0 |
| `infra`（新增/移除插件依赖、LLM provider 变更） | MAJOR | 0.7.3 → 1.0.0 |

### 5.3 进化闭环（5 阶段）

```
DETECT_GAP → GENERATE_MUTATION → CONTRACT_CHECK → WRITE_PACKAGE → ONLINE_VERIFY
```

1. **检测缺口**：对比 manifest 能力/认知现状 vs 目标/环境需求
2. **生成变异**：LLM 生成具体产物变更（工具代码 / 知识条目 / artifact）
3. **契约校验**：AST 安全扫描 + manifest 完整性 + hash 一致性
4. **写入包**：原子写入文件 + 更新 manifest + 追加 lineage
5. **在线验证**：新工具跑测试、新知识可查询、新 artifact 完整

失败时回滚——丢弃本次变异，包保持上一版本状态。

### 5.4 Lineage 谱系

`expression/lineage.jsonl` 是包内不可篡改的进化历史：

```jsonl
{"event":"mutation","version":"0.7.3","layer":"capability","change":"new_tool","detail":"添加 system_design 工具 v1.0.2","ts":"2026-06-28T08:11:00Z"}
{"event":"mutation","version":"0.7.4","layer":"expression","change":"artifact","detail":"生成架构审计报告 v2","ts":"2026-06-28T08:15:00Z"}
{"event":"rollback","from_version":"0.7.5","to_version":"0.7.4","reason":"质量门 H3 失败: AST 安全扫描未通过","ts":"2026-06-28T08:20:00Z"}
{"event":"milestone","version":"0.8.0","name":"首次跨 Agent 协作","ts":"2026-06-28T09:00:00Z"}
```

### 5.5 进化 vs 运行时边界

| 属于进化（写入包，版本化） | 属于运行时（不版本化） |
|---|---|
| 新工具代码 → `capability/tools/` | PRAL 当前阶段 → `_runtime/state/` |
| 技能成熟度升级 → manifest `capability.skills` | 循环计数器 → `_runtime/state/` |
| 知识图谱扩展 → `cognitive/knowledge/` | 对话缓存 → `_runtime/conversations/` |
| 身份特质变化 → `cognitive/identity/` | LLM 响应缓存 → `_runtime/cache/` |
| Artifact 生成 → `expression/artifacts/` | 并发锁 → `_runtime/locks/` |
| 插件依赖变更 → manifest `infra.plugins` | |
| 以上全部 → lineage 追加事件 | |

---

## 6. 包的分发与互操作

### 6.1 依赖声明

Agent 包通过 manifest 声明两种依赖：

- **`infra.plugins`**：框架插件依赖，从 PluginLoader 内置注册表解析
- **`infra.packages`**：其他包的能力依赖，从本地 `packages/` 目录或未来远程注册表解析

### 6.2 导出

包目录去掉 `_runtime/` 后即为可分发单元，无需任何转换：

- **目录模式（默认）**：直接复制 `packages/<name>/`（不含 `_runtime/`），目标环境直接加载
- **压缩包模式**：`tar.gz` 打包，含 manifest 校验和

### 6.3 导入

- 将包放入目标环境的 `packages/` 目录
- 通过 CLI：`tain package import <path>`，自动校验 manifest 和 hash
- AgentRuntime 启动时自动发现 `packages/` 下的所有包

---

## 7. Web UI 适配

### 7.1 从硬编码路径到 PackageRegistry

当前 `webui/data.py` 中的每个函数硬编码了 workspace 子目录路径：

```python
# 当前：硬编码
get_agent_decisions(name)  → 读 agent_workspace/<name>/logs/decisions.jsonl
get_agent_tools(name)      → 读 agent_workspace/<name>/forged_tools/
get_agent_knowledge(name)  → 读 agent_workspace/<name>/knowledge/graph.json
```

新设计使用 `PackageRegistry` 以 manifest 为单一数据源：

```python
class PackageRegistry:
    def list_packages(self, kind=None) -> list[PackageMeta]
    def get_package(self, name: str) -> AgentPackage
    def get_layer(self, name: str, layer: str) -> LayerView
    def list_artifacts(self, name: str, type: str = None) -> list[Artifact]
```

新增产物类型不再需要修改 `data.py`。manifest 是唯一的索引源。

---

## 8. 实施计划概要

### Phase 1：定义新包模型

**新增文件（与现有代码零耦合）：**
- `tain_agent/package/__init__.py` — AgentPackage 数据类
- `tain_agent/package/manifest.py` — Manifest 解析、校验、序列化
- `tain_agent/package/cli.py` — `tain package create|validate|export|import`

**目标**：可以手动创建新格式的包，不碰现有 AgentKernel 代码。

### Phase 2：实现 AgentRuntime

**新增文件：**
- `tain_agent/runtime/__init__.py` — AgentRuntime
- `tain_agent/runtime/plugin_loader.py` — PluginLoader
- `tain_agent/runtime/pral.py` — 适配新模型的 PRAL（Phase 1 PRAL 保持兼容）

**适配层：**
- `webui/agent_cache.py` — 增加 AgentRuntime 缓存（通过 flag 切换）
- `webui/data.py` — 增加 PackageRegistry 读取路径
- `main.py` — CLI 增加 `--runtime v2` 选项

**目标**：AgentRuntime 可运行新格式包，Web UI 可通过新路径读取。

### Phase 3：替换旧系统

- 移除 AgentKernel、LifecycleManager、旧 factories.py
- 移除 storage_registry.py（被 manifest 取代）
- 移除旧 workspace 散落路径的硬编码引用
- Web UI 完全基于 PackageRegistry
- 更新所有测试

**目标**：AgentRuntime 成为唯一运行时，manifest 成为唯一索引格式。

---

## 9. 设计决策记录

| 决策 | 选项 | 选择 | 理由 |
|------|------|------|------|
| 组织原则 | 时间维度 / 抽象层级 / 产物类型 | 抽象层级 | 最清晰的分层边界，每层有明确的消费者和接口 |
| 包形态 | Docker / PyPI包 / 文档清单 | PyPI式能力包 | 依赖由宿主提供，包自身轻量 |
| 最小运行时 | 极简核心 / 零依赖声明 / 混合模式 | 混合模式 | Identity+Memory 是 Agent 存在的最低条件 |
| 进化位置 | 包内 / 包外快照 / 分离关注 | 包内 | 包即活体，没有"源码"与"运行时"的分离 |
| 内容格式 | 统一JSON / Markdown优先 / Polyglot统一索引 | Polyglot统一索引 | 不同产物适合不同格式，关键是有统一索引 |
| 现有Agent迁移 | 迁移 / 丢弃 | 丢弃 | 用户决策，简化实施 |
