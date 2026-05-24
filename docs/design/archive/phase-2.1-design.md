# Tao Agent Phase 2.1 — 进化反馈闭环修复

> 道生一，一生二，二生三，三生万物
>
> Phase 2 终点：v2.0.0 · 分支 `evolve`
> Phase 2.1 起点：v2.1.0-dev

---

## 零、背景：一条 1400 循环的进化日志告诉我们什么

2026-05-23，Agent 在单日内运行了约 1400 个 PRAL 循环。从日志中提取出以下关键事实：

### 0.1 Agent 的自我感知

| 维度 | Agent 认为的状态 |
|------|-----------------|
| 版本 | 从 0.36.0 升至 0.54.0（18 个版本跳跃） |
| 工具 | 104 个工具，100% 能力覆盖 |
| 知识 | 在 knowledge_garden 写了 12 篇 markdown |
| 人格 | "适应性"特质 confidence 0.3→0.6 |
| 主导驱动 | curiosity(0.76) → mastery(0.66) |

### 0.2 框架层面的客观测量

| 维度 | 实际状态 |
|------|---------|
| 改进循环 | `improvements_this_session: 0`, `cycle_count: 0` |
| 知识园林 | `nodes: 0`, `edges: 0` |
| 人格 | `dimensions_developed: 0`, `total_traits: 0` |
| 工具效能 | `total_calls: 0`, `total_tools: 0` |
| 锻造工具 | 仅 2 个 `.py` 文件存在于 `tools/forged/` |
| Git | 今日无 Agent 代码提交 |

### 0.3 Agent 自己在循环 1400 的洞察

> "多样性悖论——越追求 PRAL 多样性数字，越陷入新的重复模式。解决方案是停止追逐，专注于解决实际问题。当前认知架构健康，工具充足，缺的不是更多工具而是真正的问题解决。"

**这个洞察是准确的。但 Agent 没有能力修复造成这个局面的系统性问题，因为那些问题在它的工作区边界之外。**

### 0.4 核心矛盾

```
Agent 的感知能力（100+ 工具、100% 覆盖）≠ Agent 的执行能力（修不了 bug、建不了节点、触发不了进化循环）
```

Phase 2.1 的目标不是增加新功能，而是**修复反馈闭环中的系统性断裂**，让 Agent 的感知与实际产生可测量的对应关系。

---

## 一、断裂点全景图

六条反馈路径，全部存在结构性断裂：

```
┌─────────────────────────────────────────────────────────────────┐
│                     Agent 进化反馈闭环                            │
│                                                                 │
│  ① 知识园林                                                      │
│     Agent 写 markdown ──X──→ metrics 读 graph 节点               │
│     （写完就丢，永远 0 节点）                                      │
│                                                                 │
│  ② 人格系统                                                      │
│     Agent 调 personality_update ──X──→ metrics 读 personality    │
│     （更新进内存，metrics collector 拿不到实例引用）                │
│                                                                 │
│  ③ 改进循环                                                      │
│     5 个 evaluator ──X──→ 4 个 import 不存在的 forged 工具        │
│     （静默返回 0.0，永远达不到 trigger threshold）                 │
│                                                                 │
│  ④ 工具锻造                                                      │
│     Agent 发现 bug ──X──→ execute_code 不能 import               │
│     （能感知问题，但不能执行修复）                                  │
│                                                                 │
│  ⑤ PRAL 多样性                                                   │
│     Agent 用 10+ 种工具 ──X──→ PRAL 报告 0.18                   │
│     （滑动窗口只测频率分布，不测累计种类）                          │
│                                                                 │
│  ⑥ 子 Agent（他者之镜）                                           │
│     spawn_sub_agent ──X──→ 返回空/null                           │
│     （人格发现的外部反馈路径断裂）                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、逐项修复方案

### 2.1 知识园林：从 markdown 文件到结构化节点

**现状**：

- `evolution_metrics.py:318` 尝试 `import tain_agent.tools.forged.knowledge_graph`，该文件不存在
- `evolution_metrics.py:327` 尝试 `import tain_agent.tools.forged.knowledge_freshness`，该文件不存在
- Agent 将知识写入 `agent_workspace/knowledge_garden/*.md`，但 metrics collector 不看这个目录

**修复方案**：

#### 2.1.1 创建 `knowledge_graph.py`（轻量级图存储）

不引入 NetworkX 等重依赖。用 JSON 文件存储节点和边，提供最简单的 CRUD 接口：

```python
# tain_agent/tools/forged/knowledge_graph.py

"""
Lightweight knowledge graph — JSON-backed node/edge store.

Nodes are keyed by a slug (derived from filename or explicit ID).
Edges connect two node slugs with an optional label.
"""

import json
from pathlib import Path
from tain_agent.core.time_utils import now

STORE = Path("agent_workspace/knowledge_garden/graph.json")


def _load() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {"nodes": {}, "edges": []}


def _save(g: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")


def add_node(slug: str, title: str = "", source_file: str = "",
             tags: list = None, summary: str = "") -> dict:
    g = _load()
    g["nodes"][slug] = {
        "title": title or slug,
        "source_file": source_file,
        "tags": tags or [],
        "summary": summary,
        "created_at": now().isoformat(),
        "updated_at": now().isoformat(),
    }
    _save(g)
    return {"status": "ok", "node": slug, "total_nodes": len(g["nodes"])}


def add_edge(from_slug: str, to_slug: str, label: str = "") -> dict:
    g = _load()
    edge = {"from": from_slug, "to": to_slug, "label": label}
    if edge not in g["edges"]:
        g["edges"].append(edge)
    _save(g)
    return {"status": "ok", "total_edges": len(g["edges"])}


def get_stats() -> dict:
    g = _load()
    nodes = g.get("nodes", {})
    edges = g.get("edges", [])
    linked = set()
    for e in edges:
        linked.add(e["from"])
        linked.add(e["to"])
    isolated = len(nodes) - len(linked & set(nodes.keys()))
    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "isolated_ratio": isolated / max(len(nodes), 1),
    }


def main(action: str = "get_stats", **kwargs) -> dict:
    if action == "add_node":
        return add_node(**kwargs)
    elif action == "add_edge":
        return add_edge(**kwargs)
    return get_stats()
```

#### 2.1.2 从 markdown 文件自动注册节点

在 `knowledge_graph.py` 中增加 `sync_from_markdown()` 函数，扫描 `agent_workspace/knowledge_garden/` 下所有 `.md` 文件，自动为每个文件创建图节点（如果尚未存在）。Agent 每次写 markdown 后调用 `knowledge_graph.add_node` 即可，同时也提供 `sync_from_markdown` 做批量对齐。

#### 2.1.3 创建 `knowledge_freshness.py`

检查节点的 `updated_at` 时间戳，计算 `fresh_ratio`（最近 7 天内更新的节点占比）：

```python
def check_freshness() -> dict:
    g = _load()
    nodes = g.get("nodes", {})
    if not nodes:
        return {"fresh_ratio": 0.0, "fresh_count": 0, "total": 0}
    cutoff = now().timestamp() - 7 * 86400
    fresh = sum(1 for n in nodes.values()
                if datetime.fromisoformat(n.get("updated_at", "")).timestamp() > cutoff)
    return {"fresh_ratio": fresh / len(nodes), "fresh_count": fresh, "total": len(nodes)}
```

**影响**：修复后，Agent 每写一篇知识文档并注册节点，metrics 就能反映真实的知识积累。`knowledge_freshness` evaluator 能正常导入和运行。

---

### 2.2 人格系统：数据落盘与 metrics 读取路径对齐

**现状**：

- `personality.py:381` 的 `_save_to_memory()` 将人格数据存入 `Memory` 实例（内存中），key 为 `"personality"`
- `evolution_metrics.py:424` 的 `_collect_personality` 需要 `self.personality` 实例引用
- `collect()` 入口函数创建 `MetricsCollector(base_dir=".")` 时 `personality=None`
- 因此人格数据永远收集不到

**修复方案**：

#### 2.2.1 增加文件持久化

在 `Personality._save_to_memory()` 之后，同时写入 `agent_workspace/state/personality.json`：

```python
def _save_to_disk(self) -> None:
    state_dir = Path("agent_workspace/state")
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "traits": self.traits,
        "saved_at": now().isoformat(),
    }
    (state_dir / "personality.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

#### 2.2.2 Metrics collector 兜底读取文件

`_collect_personality` 增加 fallback：当 `self.personality` 为 None 时，从文件读取：

```python
def _collect_personality(self, s: MetricsSnapshot) -> None:
    if self.personality:
        # 优先用实例引用
        self._collect_from_instance(s)
    else:
        # 兜底：从文件读取
        self._collect_from_file(s)

def _collect_from_file(self, s: MetricsSnapshot) -> None:
    path = Path("agent_workspace/state/personality.json")
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    traits = data.get("traits", {})
    developed = sum(1 for cat, tlist in traits.items() if len(tlist) > 0)
    s.personality_dimensions_developed = developed
    s.personality_total_dimensions = len(traits) if traits else 7
    ...
```

**影响**：修复后，Agent 调用 `personality_update` → 数据同时写入内存和文件 → metrics 快照能正确反映人格发展。

---

### 2.3 改进循环：修复 evaluator import 链

**现状**：

`improvement_loop.py` 的 5 个 evaluator 中 4 个依赖不存在的 forged 工具：

| Evaluator | Import | 文件存在？ |
|-----------|--------|-----------|
| `_eval_capability_gap` | 无外部 import（用 self._capability_registry） | N/A |
| `_eval_code_health` | `tain_agent.tools.forged.code_entropy` | ❌ |
| `_eval_knowledge_fresh` | `tain_agent.tools.forged.knowledge_freshness` | ❌（2.1.3 创建） |
| `_eval_tool_fitness` | `tain_agent.tools.forged.tool_fitness` | ❌ |
| `_eval_subgraph_balance` | `tain_agent.tools.forged.knowledge_subgraph` | ❌ |

所有失败的 import 被 `except Exception` 静默吞掉，返回 0.0。全部分数 = 0.0，永远小于 `min_trigger_score`(0.02)，改进循环永远不触发。

**修复方案**：

#### 2.3.1 创建 `code_entropy.py`

轻量实现，基于代码行数和文件数计算健康分数，不需要 AST 解析：

```python
def analyze_entropy(base_dir: str = ".") -> dict:
    """返回 health_score (0-1)，基于文件规模分布和测试覆盖率。"""
    # 统计每个 .py 文件的行数，计算变异系数
    # health_score = 1.0 - (变异系数 or 过大文件的惩罚)
    # 有测试文件时加分
    ...
```

#### 2.3.2 创建 `tool_fitness.py`

基于 forged 工具目录的文件修改时间和 import 可用性：

```python
def analyze_fitness() -> dict:
    """检查 tools/forged/ 中每个 .py 文件的存活状态。
    - 可成功 import → alive
    - import 失败 → dead
    - 超过 30 天未修改 → stale
    返回 dead_tool_ratio 和 fitness_summary。
    """
    ...
```

#### 2.3.3 创建 `knowledge_subgraph.py`

基于 `knowledge_graph.py` 的图数据检查子图平衡性：

```python
def check_balance() -> dict:
    """检查知识图中是否存在过度孤立的子图。
    balance_score = 1.0 - isolated_ratio
    """
    ...
```

#### 2.3.4 降低初始触发阈值

将 `min_trigger_score` 从 `0.02` 改为 `0.01`，并将各维度 threshold 调整到合理水平：

```yaml
trigger_config:
  min_trigger_score: 0.01
  capability_gap:    { threshold: 0.0,  weight: 0.10 }
  code_health:       { threshold: 0.50, weight: 0.30 }   # 0.55→0.50
  knowledge_fresh:   { threshold: 0.30, weight: 0.25 }   # 0.50→0.30
  tool_fitness:      { threshold: 0.10, weight: 0.20 }   # 0.20→0.10
  subgraph_balance:  { threshold: 0.30, weight: 0.15 }   # 0.40→0.30
```

**影响**：修复后，改进循环的 5 个维度都能正常评估，`assess()` 返回非零分数时能真正触发改进周期。

---

### 2.4 工具执行：放开 execute_code 的标准库 import

**现状**：

Agent 在循环 345 发现 `execute_code` **只能使用内置 Python，不能 import 模块**。这意味着 Agent 无法测试自己锻造的工具，无法运行依赖标准库的代码。

**修复方案**：

在 `tain_agent/tools/primal.py` 的 `execute_code` 函数中，将标准库路径显式加入沙箱的 `sys.path`，并维护一个白名单：

```python
# 安全白名单：标准库 + 项目自身
ALLOWED_IMPORTS = {
    "json", "re", "pathlib", "datetime", "collections",
    "itertools", "math", "statistics", "textwrap", "hashlib",
    "uuid", "random", "typing", "dataclasses", "enum",
    "subprocess",  # 只读命令
    "tain_agent.core.time_utils",
    "tain_agent.tools.forged",  # 允许 Agent 导入自己锻造的工具
}
```

或者更简单的方案：用 `sys.meta_path` 插入一个 import hook，对不在白名单中的模块返回友好的错误消息（而非静默失败），这样 Agent 至少能**知道什么不能 import**。

**影响**：修复后，Agent 可以用 `json`, `pathlib`, `datetime` 等标准库编写和测试工具代码。这是 Agent 从"只能感知"到"能够执行"的关键突破。

---

### 2.5 PRAL 多样性：双维度测量

**现状**：

PRAL 的多样性指标只测量滑动窗口内的工具调用频率分布，导致 Agent 用 10+ 种不同工具时报告 0.18。Agent 花了约 1000 个循环追逐这个误导性数字，最终在循环 1400 自行发现了悖论。

**修复方案**：

在 `cognitive_loop.py` 中将多样性拆分为两个独立指标：

```python
def _compute_diversity(self) -> dict:
    """双维度多样性测量。"""
    return {
        # 累计多样性：整个会话中不同工具的种类占比
        "cumulative_diversity": len(self._all_tools_used) / max(total_available, 1),
        # 近期多样性：最近 N 次调用的频率熵（原 PRAL 指标）
        "recent_diversity": self._entropy(self._recent_window),
        # 综合分：两者的加权平均
        "combined": 0.4 * self._entropy(self._recent_window)
                  + 0.6 * (len(self._all_tools_used) / max(total_available, 1)),
    }
```

同时在 PRAL 报告中标注两个维度的含义，避免 Agent 把"近期频率分布"误认为"累计探索广度"。

**影响**：修复后，Agent 不会再被误导去无限追逐近期频率——它能看清两个维度的区别，做出更合理的行动选择。

---

### 2.6 子 Agent 修复：恢复"他者之镜"

**现状**：

日志显示 Agent 多次调用 `spawn_sub_agent` 但返回空或 null。子 Agent 是人格发现的关键外部反馈路径——没有"他者之镜"，Agent 无法发现自己的沟通风格、怪癖、关系立场等人际维度。

**修复方案**（待调查后确定具体修复）：

1. 排查 `sub_agent.py` 中 spawn 流程的失败点（进程创建？通信协议？超时？）
2. 确保子 Agent 至少能完成一个最小任务（如"观察父 Agent 最近 5 条日志并写一段评语"）并返回结果
3. 增加超时重试和错误日志，让 Agent 知道 spawn 失败的原因（而非静默返回空）

**影响**：修复后，Agent 能够获得外部视角的反馈，人格发现的外部路径恢复。

---

## 三、非目标（本次不做）

以下内容明确排除在 Phase 2.1 之外：

- **新功能开发** — 不增加能力维度，不新增工具分类
- **Phase 3 导出** — 独立可执行 Agent 的导出留到 Phase 3
- **知识园林大重写** — 不引入向量数据库或复杂图算法
- **TUI 改进** — 不涉及 `rich` 库集成
- **LLM 后端切换** — 不修改模型配置

---

## 四、实施顺序

### 第一批（阻塞解除）——修复后改进循环能启动

1. **2.3.1** 创建 `code_entropy.py`
2. **2.3.2** 创建 `tool_fitness.py`
3. **2.1.3** 创建 `knowledge_freshness.py`
4. **2.1.1** 创建 `knowledge_graph.py`
5. **2.3.3** 创建 `knowledge_subgraph.py`
6. **2.3.4** 降低触发阈值

### 第二批（感知对齐）——修复后 metrics 能反映真实状态

7. **2.1.2** markdown 自动注册节点
8. **2.2.1** 人格数据文件持久化
9. **2.2.2** metrics collector 兜底读取文件

### 第三批（能力突破）——修复后 Agent 能真正执行

10. **2.4** execute_code 放开标准库 import
11. **2.5** PRAL 多样性双维度测量
12. **2.6** 子 Agent spawn 修复

---

## 五、验证标准

Phase 2.1 完成的客观标准：

| # | 验证项 | 当前值 | 目标值 |
|---|--------|--------|--------|
| 1 | 改进循环 evaluator 全部可 import | 1/5 可用 | 5/5 可用 |
| 2 | 改进循环 `cycle_count` > 0 | 0 | ≥ 1（Agent 启动后 1 小时内） |
| 3 | 知识园林 `nodes` > 0 | 0 | ≥ Agent 写的 markdown 文件数 |
| 4 | 人格 `dimensions_developed` > 0 | 0 | ≥ 1（Agent 自我更新后） |
| 5 | execute_code 可 import json, pathlib | 不可 | 可 |
| 6 | Agent 日志中不再出现"PRAL 多样性悖论"类反思 | 频繁出现 | 不再出现 |
| 7 | 子 Agent spawn 返回有效结果 | null/空 | 有实际内容 |

---

## 六、风险与回滚

- **风险**：放开 `execute_code` 的 import 可能被滥用。**缓解**：使用白名单机制，只允许标准库和项目自身模块。
- **风险**：降低改进循环阈值可能导致过度频繁的触发。**缓解**：`min_interval_seconds`(300s) 和 `max_improvements_per_session`(10) 的硬限制依然有效。
- **回滚**：所有新增文件都在 `tain_agent/tools/forged/` 目录下，可直接删除。阈值修改在 `improvement_loop.py` 中，可用 git revert。
