# Agent 评估体系 · 设计文档

**日期**: 2026-05-31
**来源**: Agent 自演进模块升级 — 目标 2
**范围**: EvaluationPlugin（第 8 个插件）+ 七维成熟度引擎 + 可执行报告 + 投产判定
**依赖**: Agent Core-Plugins 架构（v0.6.0）

---

## 1. 架构总览

评估体系作为第 8 个插件（EvaluationPlugin）加入 Core-Plugins 架构，通过 `PluginProtocol` 钩子和 `dispatch()` 与其他插件交互。

```
┌────────────────────────────────────────────────────────────────┐
│                    EvaluationPlugin                             │
│                                                                │
│  ┌──────────────────┐    ┌──────────────────┐                  │
│  │  时间触发器        │    │  事件触发器        │                 │
│  │  on_cycle_end     │    │  dispatch 事件    │                 │
│  │  每 50 轮例行评估  │    │  锻造成功/失败     │                 │
│  │  每 200 轮深度评估 │    │  技能升级/退化     │                 │
│  │                    │    │  自主等级变更      │                 │
│  └────────┬───────────┘    └────────┬─────────┘                 │
│           │                         │                           │
│           └─────────┬───────────────┘                           │
│                     ▼                                           │
│  ┌──────────────────────────────────────┐                       │
│  │        七维成熟度引擎                  │                       │
│  │  identity  memory  skill  tool       │                       │
│  │  knowledge  workflow  collaboration   │                       │
│  └──────────────────────────────────────┘                       │
│                     │                                           │
│                     ▼                                           │
│  ┌──────────────────────────────────────┐                       │
│  │        可执行报告生成器                │                       │
│  │  成熟度画像 → 改进建议 → Goal/Workflow │                       │
│  └──────────────────────────────────────┘                       │
│                     │                                           │
│                     ▼                                           │
│  ┌──────────────────────────────────────┐                       │
│  │        投产判定器                      │                       │
│  │  稳定达标 N 轮 + 实际场景验证           │                       │
│  └──────────────────────────────────────┘                       │
└────────────────────────────────────────────────────────────────┘
```

### 设计原则

- **协议遵循**：EvaluationPlugin 实现 `PluginProtocol`，通过 `enrich_prompt()` 注入改进建议
- **插件隔离**：只通过 `dispatch()` 与其他插件交互，不直接 import
- **渐进式评估**：快速例行扫描（50 轮）+ 完整深度评估（200 轮）
- **闭环改进**：评估报告自动转化为 Goal/Workflow 注入 Agent 演化
- **部分可用**：Chaos 模式不加载，不破坏现有运行路径

---

## 2. 触发系统

### 2.1 时间触发

```python
ROUTINE_EVAL_INTERVAL = 50     # 每 50 轮：快速健康扫描（仅检查 health_check）
DEEP_EVAL_INTERVAL = 200       # 每 200 轮：完整七维评估 + 生成报告
```

通过 `on_cycle_end(cycle)` 钩子，Kernel 在每个 PRAL 循环结束时调用。插件内部计数，达到阈值时触发对应评估。

### 2.2 事件触发

通过监听 Kernel `dispatch()` 事件，关键行为即时触发评估：

| 事件 | 触发动作 |
|------|---------|
| `tool.forge.success` | 评估 tool 维度 + skill 维度 |
| `tool.forge.failure`（连续 3 次） | 告警 tool 维度退化 |
| `skill.maturity.upgrade` | 评估 skill 维度成长趋势 |
| `skill.success_rate_below_0.3` | 告警 skill 退化 |
| `identity.autonomy.change` | 记录并评估 identity 维度 |
| `collaboration.teach.complete` | 评估 collaboration 维度 |

### 2.3 与现有代码的关系

```
现有 evolution/              →  新 EvaluationPlugin
────────────────────────────────────────────────
quality_gate.py (15 gates)   →  保留不修改。EvaluationPlugin 持续评估 → 稳定 → ExportQualityGate 最终检查
reporter.py                  →  保留不修改。EvaluationPlugin 生成自己的报告格式，内部可调用 reporter
```

---

## 3. 七维成熟度引擎

### 3.1 数据模型

```python
class MaturityTier(Enum):
    NASCENT    = 1   # 萌芽：数据极少（score < 0.2）
    DEVELOPING = 2   # 发展中：有基础数据（0.2 ≤ score < 0.5）
    CAPABLE    = 3   # 可用：指标良好（0.5 ≤ score < 0.75）
    MATURE     = 4   # 成熟：持续稳定（0.75 ≤ score < 0.9）
    EXCELLENT  = 5   # 卓越：接近理论上限（score ≥ 0.9）

class TrendDirection(Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"

@dataclass
class DimensionMaturity:
    dimension: str              # 维度名
    score: float                # 0.0 – 1.0
    level: MaturityTier
    trend: TrendDirection
    evidence: list[str]         # 支持评级的具体数据点
    recommendations: list[str]  # 改进建议
    evaluated_at: str

@dataclass
class EvaluationSnapshot:
    agent_id: str
    evaluated_at: str
    dimensions: dict[str, DimensionMaturity]
    overall_score: float        # 七维加权平均
    production_readiness: ProductionReadiness
    report_id: str
```

### 3.2 七维评估指标

| 维度 | 数据源 | 核心指标 | 权重 |
|------|--------|---------|------|
| **Identity** | IdentityPlugin.health_check() + traits | 专长领域数、价值观密度（≥4 个值）、自主等级、特质置信度中位数 | 0.15 |
| **Memory** | MemoryPlugin.health_check() + EM stats | 情景记忆数（≥50）、语义实体数（≥20）、记忆强度中位数、遗忘率 | 0.10 |
| **Skill** | SkillPlugin.health_check() + maturity | 技能总数、master/expert 占比、平均成功率、组合技能数 | 0.20 |
| **Tool** | ToolPlugin.health_check() + forge stats | 工具总数、锻造工具数、调用成功率、forge_cycle 成功率 | 0.20 |
| **Knowledge** | KnowledgePlugin.health_check() + graph | 知识实体数（≥30）、关系密度、新鲜度比例、冲突解决数 | 0.15 |
| **Workflow** | WorkflowPlugin.health_check() + history | 完成工作流数、成功率、平均步骤数、失败回退率 | 0.10 |
| **Collaboration** | CollaborationPlugin.health_check() + social | 协作次数、团队参与数、声誉分、知识传授次数 | 0.10 |

### 3.3 趋势判定

对比最近 3 次评估快照中同一维度的分数：
- `improving`：最近一次 > 前两次均值 + 0.05
- `declining`：最近一次 < 前两次均值 - 0.05
- `stable`：其他情况（含首次评估或少于 3 次快照）

---

## 4. 可执行报告生成器

### 4.1 报告结构

```python
@dataclass
class EvaluationReport:
    report_id: str
    agent_id: str
    agent_name: str
    evaluated_at: str

    # 雷达图数据
    dimensions: dict[str, DimensionMaturity]
    radar_data: dict[str, float]               # 维度名 → score

    # 趋势
    trend_summary: dict[str, str]              # 维度名 → "↑" | "→" | "↓"
    historical_scores: list[dict]              # 最近 10 次快照（压缩格式）

    # 亮点与风险
    strengths: list[str]                       # score ≥ 0.8 且趋势非 declining
    risks: list[Risk]                          # score < 0.5 或趋势 declining

    # 可执行改进
    action_items: list[ActionItem]             # 按优先级排序

    # 投产状态
    production_readiness: ProductionReadiness

@dataclass
class Risk:
    dimension: str
    severity: str                              # "critical" | "warning"
    description: str
    current_score: float
    trend: str

@dataclass
class ActionItem:
    priority: int                              # 1 = 最高
    dimension: str
    description: str
    goal_title: str                            # 自动生成的 Goal 标题
    suggested_workflow: list[str]              # 建议的步骤
    expected_impact: float                     # 预计提升幅度
```

### 4.2 改进建议映射表

| 维度 | score < 0.5 | 0.5 ≤ score < 0.75 | score ≥ 0.75 |
|------|-----------|-------------------|-------------|
| **Skill** | 练习已有技能提高成功率 | 组合技能形成新能力 | 传授技能给其他 Agent |
| **Tool** | 运行 forge_cycle 填补工具缺口 | 优化已有工具提高成功率 | 审计工具安全性并文档化 |
| **Knowledge** | 扩展知识面增加实体和关系 | 验证过期知识更新新鲜度 | 导出知识子图传授他人 |
| **Identity** | 探索自身定位发现特质 | 申请自主等级升级 | 撰写自身能力白皮书 |
| **Memory** | 巩固重要情景记忆 | 提取记忆模式到语义记忆 | 清理劣化记忆整理记忆库 |
| **Workflow** | 完成简单工作流练习 | 执行复杂多步骤工作流 | 提取成功经验为模板 |
| **Collaboration** | 主动建立 Agent 间联系 | 组建或加入团队协作 | 传授技能给其他 Agent |

### 4.3 闭环注入

```python
def _inject_action_items(self, report: EvaluationReport):
    """将评估建议转化为改进计划，写入 identity 目标树并通过 prompt 注入。"""
    for item in report.action_items[:3]:
        # 方案 1：通过 enrich_prompt 注入到系统提示
        # 方案 2：通过 dispatch("workflow.create_from_goal") 直接创建工作流
        goal_spec = {
            "title": item.goal_title,
            "description": item.description,
            "priority": item.priority,
            "source": "evaluation_engine",
        }
        self._dispatch.call("workflow.create_from_goal", goal_spec)
```

---

## 5. 投产判定器

### 5.1 判定流程

```
单次评估七维均 ≥ 0.75 + 无 critical 风险？
         │
    是   ▼
连续 N=3 次评估全部通过 + 趋势 stable/improving？
         │
    是   ▼
执行实际场景验收任务 → 结果通过？
         │
    是   ▼
★ 可投产 — 自动升级 autonomy_level → FULL
```

### 5.2 生产就绪模型

```python
@dataclass
class ProductionReadiness:
    status: ProductionStatus
    stable_streak: int              # 连续稳定评估次数
    required_streak: int = 3
    scenario_results: list[ScenarioResult]
    certified_at: str | None
    certification_report_id: str | None

class ProductionStatus(Enum):
    NOT_READY        = "not_ready"          # 未通过单次评估
    STABILIZING      = "stabilizing"         # 通过但连续次数不足
    READY_FOR_TRIAL  = "ready_for_trial"     # 连续稳定，等待场景验证
    PRODUCTION_READY = "production_ready"    # ★ 可投产

@dataclass
class ScenarioResult:
    task_name: str
    task_description: str
    passed: bool
    evidence: dict                    # 工具调用链、输出、耗时
    evaluated_by: str                 # "human" | "llm" | "framework"
    notes: str
```

### 5.3 验收任务场景

```python
SCENARIO_TEMPLATES = {
    "coding": {
        "task_name": "独立开发验收",
        "description": "根据需求描述独立完成一个功能模块的完整开发流程",
        "steps": ["需求分析 → 设计 → 代码生成 → 测试 → 文档"],
        "success_criteria": {"tool_success_rate": 0.8, "test_pass_rate": 1.0},
    },
    "analysis": {
        "task_name": "数据分析验收",
        "description": "对给定数据集完成端到端分析并输出报告",
        "steps": ["数据获取 → 清洗 → 分析 → 可视化 → 报告"],
        "success_criteria": {"tool_chain_success": 0.9},
    },
    "general": {
        "task_name": "综合能力验收",
        "description": "自主识别一个问题，设计解决方案并执行完成",
        "steps": ["问题识别 → 方案设计 → 工具使用 → 结果验证 → 总结"],
        "success_criteria": {"action_diversity": 0.5, "completion_rate": 1.0},
    },
}
```

### 5.4 投产判定接口

```python
class ProductionGate:
    def evaluate(self, snapshot: EvaluationSnapshot,
                 history: list[EvaluationSnapshot]) -> ProductionReadiness: ...
    def request_scenario_verification(self, agent_role: str) -> ScenarioResult: ...
    def certify(self, readiness: ProductionReadiness) -> str: ...
```

---

## 6. EvaluationPlugin 接口

```python
class EvaluationPlugin(PluginProtocol):
    # ── PluginProtocol ──
    def initialize(ctx: AgentContext) -> None
    def shutdown() -> None
    def health_check() -> HealthStatus
    def snapshot() -> dict
    def restore(data: dict) -> None

    # ── PRAL 钩子 ──
    def on_cycle_start(cycle: int) -> None
    def on_cycle_end(cycle: int) -> None        # 时间触发点
    def enrich_prompt(base: str) -> str          # 注入改进建议到系统提示
    def on_llm_response(response) -> None

    # ── 评估 API ──
    def evaluate(mode: str = "routine") -> EvaluationReport   # "routine" | "deep"
    def get_latest_report() -> EvaluationReport | None
    def get_report_history(n: int = 10) -> list[EvaluationReport]
    def get_production_readiness() -> ProductionReadiness
    def request_production_trial(approval: str = "human") -> ScenarioResult

    # ── 内部 ──
    def _collect_plugin_metrics() -> dict[str, dict]
    def _compute_dimension(dim: str, metrics: dict) -> DimensionMaturity
    def _detect_trend(dim: str, current: float) -> TrendDirection
    def _generate_action_items(report: EvaluationReport) -> list[ActionItem]
    def _inject_into_agent(report: EvaluationReport) -> None
```

---

## 7. 存储架构

```
agent_workspace/<name>/
  evaluations/                       # 评估专用目录
    snapshots/                       # 历史评估快照
      2026-05-31T120000.json
      2026-05-31T140000.json
    reports/                         # 评估报告（Markdown）
      report_2026-05-31T120000.md
    certifications/                  # 投产认证记录
      certification_2026-05-31.json
    trends.json                      # 趋势数据（供 Web UI 渲染）
```

---

## 8. 与 Web UI 的集成

评估数据通过 Web UI 渲染为：

- **Agent 详情页新增 "Evaluation" Tab**：展示最新雷达图（Chart.js） + 历史趋势折线图
- **Dashboard**：Agent 列表中显示投产状态徽章（🔴 未就绪 / 🟡 稳定中 / 🟢 可投产）
- **评估报告页**：可读的 Markdown 报告 + 改进建议列表 + "开始验证" 按钮

---

## 9. 文件结构

```
tain_agent/
  plugins/
    evaluation/                      # 新建
      __init__.py                    # EvaluationPlugin
      engine.py                      # MaturityEngine（七维评估）
      reporter.py                    # EvaluationReporter（报告生成 + 改进建议）
      gate.py                        # ProductionGate（投产判定）
      triggers.py                    # TriggerManager（时间 + 事件触发器）
      models.py                      # 数据模型
  evolution/                         # 保留不修改
    quality_gate.py                  # 导出前最终检查
    reporter.py                      # 版本进化报告
```

---

*设计文档完*
