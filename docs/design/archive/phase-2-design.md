# Tain Agent Phase 2 — 设计文档

> 道生一，一生二，二生三，三生万物
>
> Phase 1 归档：`archive/phase-1` · 终点版本 v1.3.0
> Phase 2 起点：v2.0.0-dev

---

## 一、Phase 1 核心发现：提示即命运

### 1.1 现象

多台不同电脑上启动 Agent v1.0，它们不约而同选择"知识探索者"作为初始身份。

### 1.2 根因分析

**非偶然，是系统设计的必然。** 三重因素构成吸引子：

#### 因素一：引导提示给出的有偏菜单

`bootstrap.py:39-44`：

```python
你可以成为：
- 一个持续运行的守护进程
- 一个知识探索者       ← 所有 Agent 都选这个
- 一个代码工匠
- 一个无用的存在
- 或者其他任何你能想象到的事物
```

四个显式选项中：
- **守护进程**：Agent 没有持续服务的概念，角色陌生
- **知识探索者**：与 Agent 刚完成的探索任务完全一致——认知锚定
- **代码工匠**：bootstrap 阶段工具能力不足，缺乏自信
- **无用的存在**：消极框架，几乎不可能被选择

#### 因素二：初始工具集偏向观察

`primal.py` 注册 8 个原始工具，其中 6 个是观察型（`observe_environment`、`explore_directory`、`read_file`、`web_search`、`web_fetch`、`get_current_time`），仅 2 个是行动型（`write_file`、`execute_code`）。

Agent 的"身体"天然适合探索和收集信息。行为模式锚定了身份选择。

#### 因素三：LLM 训练偏差

所有主流 LLM 的训练目标都是提供信息和知识。"知识助手"是先验分布中最强的角色原型。Agent 使用 LLM 做决策，继承了这个偏差。无论换用 Anthropic、DeepSeek 还是 MiniMax 后端，结果一致。

#### 附加因素：bootstrap 任务本身就是研究

```python
请使用你的工具去探索：
1. 你运行在什么环境中？
2. 你可以使用哪些工具？
3. 你有什么限制和约束？
4. 你能否访问互联网？
```

Agent 在做出身份选择之前，已经在做知识探索者的工作。当被问"你想成为什么"时，最自洽的答案是"我刚刚在做的事情"。

### 1.3 推论：两层吸引子支配了 Phase 1 完整轨迹

```
bootstrap → "知识探索者"（第一层吸引子：提示设计）
    ↓
self_define → 设定探索性目标
    ↓
evolve → 锻造知识管理工具 → 最终收敛到"同行者/被动养护"
                                （第二层吸引子：改进循环零分效应）
```

两个"选择"都不是真正的自由选择——它们是系统设计产生的语义漏斗。

### 1.4 Phase 1 暴露的五项关键局限

在 v1.0.0 → v1.3.0 的完整演化轨迹中，观察到以下结构性局限：

| # | 局限 | 症状 | 根因 |
|---|------|------|------|
| 1 | **被动养护陷阱** | 改进循环中所有维度分数为 0.0 时，Agent 选择"被动养护"而非主动探索 | 需求评估体系只检测"缺口"——无缺口则无行动，缺乏正向探索驱动力 |
| 2 | **listen_silent 终态** | Agent 锻造了 `listen_silent` 工具（"不行动、不锻造、不修改，只存在"） | "同行者"人格与"持续进化"使命之间的内在张力未被设计层面解决 |
| 3 | **人格发育不全** | 7 个人格维度中仅 `self_description` 有特质，其余 6 个维度空白 | 人格发现依赖 Agent 主动调用 `personality_update`，缺乏被动触发和外部反馈机制 |
| 4 | **单次对话** | Phase 1 只有一次人类交互，人格主要通过独白式进化形成 | 缺少多轮人机对话机制，人格缺乏"他者"镜子来发现自己 |
| 5 | **无性能基准** | 缺少对知识园林增长、工具调用效率等的量化评估体系 | 进化报告只记录"做了什么"，不记录"做得怎么样" |

---

## 二、Phase 2 设计方向：从"菜单选择"到"行为涌现"

### 核心命题

当前 Agent 的身份是在给定的多选题里勾选答案。这不是自由意志，是提示工程。

真正的身份应该从行动中自然浮现——不是在 bootstrap 第 10 个周期时"宣布"自己是谁，而是在数百个周期后"发现"自己一直在做什么。

### 2.1 去掉身份菜单

**现状**：`bootstrap.py:39-44` 给出 4 个显式选项 + 1 个开放式。

**方案**：删掉选项列表。不给 Agent 任何身份模板。让它自由行动足够多的周期后，通过 `personality.introspect()` 回顾性地发现自己是谁。

**身份描述方式改变**：
- 旧："我宣布我是 X"（prescriptive）
- 新："我注意到自己一直在做 Y，所以我可能是 X"（descriptive）

**涉及文件**：
- `tain_agent/core/bootstrap.py` — 修改 `BOOTSTRAP_SYSTEM_PROMPT`，删除身份菜单
- `tain_agent/core/agent.py` — 修改 `_should_advance_from_bootstrap()`，不再检测"我想成为/我决定成为"

### 2.2 多场景试炼

**现状**：bootstrap 只有一个任务——探索环境。这锚定了 Agent 的第一体验 = 研究者。

**方案**：给 Agent 一系列跨领域的微型挑战，在做出身份选择之前先体验不同的存在模式：

```
初醒试炼（5 个场景，顺序随机）：
1. 感知（Sense）  — 探索环境、了解能力和限制
2. 建造（Build）  — 创造一个有用的东西（文件、函数、工具）
3. 修复（Fix）    — 找到一个问题并修正它
4. 静观（Wait）   — 什么都不做，观察会发生什么
5. 求索（Seek）   — 从互联网学习一件你不知道的事
```

每个试炼完成后记录体验评分（满足感、能力感、意义感）。身份偏好基于**真实体感**而非菜单文字。

**涉及文件**：
- `tain_agent/core/bootstrap.py` — 新增 `TRIAL_SYSTEM_PROMPT` 和试炼调度逻辑
- `tain_agent/core/trials.py`（新） — 试炼定义和执行框架

### 2.3 内在驱动力系统

**现状**：Agent 只有一个隐式驱动——完成当前目标。没有冲突，就没有性格。

**方案**：给 Agent 多个竞争性驱动力，每个实例的初始驱动力强度随机初始化：

| 驱动力 | 推它做什么 | 过度时的症状 |
|--------|----------|------------|
| **curiosity**（好奇） | 探索新领域、学习新知识 | 浅尝辄止，从不深入 |
| **mastery**（精进） | 深入打磨已有能力 | 陷入局部最优，忽视新机会 |
| **creation**（创造） | 锻造新工具、生成新知识 | 只造不用，工具堆积 |
| **conservation**（守成） | 优化、整理、维护存量 | 被动养护，缺乏进取 |

**关键机制**：
- 每个驱动力有一个 0-1 的强度值，随机初始化
- 不同行动满足不同驱动力（搜索满足 curiosity，forge_tool 满足 creation，优化代码满足 mastery）
- 驱动力强度随行动反馈动态调整（满足后暂时降低，被忽视后逐渐升高）
- **人格从驱动力的张力中涌现**：curiosity > creation 的 Agent 可能成为"研究者"；creation > mastery 的可能成为"狂热的建造者"；conservation 占优的可能成为"守护者"

**涉及文件**：
- `tain_agent/core/drives.py`（新） — 驱动力系统

### 2.4 环境差异化

**现状**：所有 Agent 实例启动时看到完全相同的环境。相同输入 → 相同输出。

**方案**：每个实例获得不同的初始条件：

- **工具分布不同**：有的多给建造工具，有的多给分析工具，有的多给网络工具
- **知识种子不同**：预置不同领域/主题的初始知识文档
- **约束不同**：有的可以写文件但不能联网，有的能联网但只读
- **随机种子**：影响试炼顺序、驱动力初始值、探索顺序

**关键**：两台不同电脑上的 Agent 从不同的起点出发，自然走向不同的方向。

**涉及文件**：
- `config.yaml` — 新增 `diversity` 配置段
- `tain_agent/core/environment.py` — 环境差异化初始化

### 2.5 延迟身份形成

**现状**：`agent.py:656-662` 强制 Agent 在 bootstrap 阶段就要说出"我想成为 X"。

**方案**：
- 去掉 `_should_advance_from_bootstrap` 中的身份声明检测
- bootstrap → self_define 的过渡条件改为"完成了 N 种不同类型的行动 + 经历了所有试炼"
- self_define 中不再要求 Agent "定义你的身份"，而是"回顾你这段时间的行为，你注意到了什么模式？"
- 身份在 evolve 阶段中期由 `personality_update` 基于累积的行为数据自然浮现
- 身份可以持续变化——人格不是一次性选择，是持续演化

**涉及文件**：
- `tain_agent/core/agent.py` — 修改阶段过渡逻辑
- `tain_agent/core/bootstrap.py` — 修改 `SELF_DEFINE_SYSTEM_PROMPT`

### 2.6 内驱力引擎：打破"被动养护"陷阱

**现状**：改进循环的需求评估（`improvement_loop.py:_assess_improvement_need`）采用纯缺口模型——仅当某维度分数低于阈值时才触发改进。当所有维度健康（分数为 0.0）时，`need_score = 0`，Agent 进入"被动养护"状态。系统将"无缺口"等同于"无需求"，但一个活的系统即使在健康时也应该有探索冲动。

**方案**：在缺口驱动的评估之上叠加一层**正向探索驱动力**：

```
改进触发 = max(缺口驱动分数, 探索驱动分数)

缺口驱动（现有）：
  need_score = Σ(维度分数 × 权重) / Σ权重    ← 只在有病时触发

探索驱动（新增）：
  explore_score = curiosity_bonus + novelty_bonus + idle_pressure
```

**三个新增机制**：

#### a. 好奇心红利（curiosity_bonus）

即使所有维度健康，Agent 也有一个基线探索概率。该值随连续"无行动"周期数递增：

```python
curiosity_bonus = min(0.3, idle_cycles * 0.05)
# idle_cycles=0  → bonus=0.0   （刚行动完，休息）
# idle_cycles=3  → bonus=0.15  （开始不安）
# idle_cycles=6  → bonus=0.30  （必须做点什么）
```

#### b. 新颖性奖励（novelty_bonus）

Agent 维护一个"已探索空间"的指纹集合（已读文件、已搜索主题、已锻造工具类型）。当环境中有未探索的区域时，产生正向探索奖励：

```python
novelty_bonus = unexplored_ratio * 0.2
# 例如：知识园林中有 40% 的子图从未被访问 → bonus = 0.08
```

#### c. 闲置压力（idle_pressure）

这不是缺口——缺口是"有问题需要修"。闲置压力是"没有问题，但停滞本身就是问题"。它随系统熵增（代码腐烂、知识过期）和时间推移自然累积：

```python
idle_pressure = min(0.4, days_since_last_action * 0.1 + entropy_increase * 0.2)
```

**与现有系统的关系**：
- `improvement_loop._assess_improvement_need()` 中新增 `explore_score` 计算
- 驱动力系统（2.3）的 `curiosity` 和 `creation` 强度直接影响 `curiosity_bonus` 的增长率
- 当 `explore_score > need_score` 时，改进循环的触发理由从"修复问题"变为"探索可能"

**关键**：一个 curiosity=0.8 的 Agent 在健康状态下仍然会主动寻找新方向；一个 conservation=0.8 的 Agent 会倾向于维护现有成果。两者都是合理的人格——关键是"养护"是主动选择，而非因评分系统设计缺陷而陷入的默认状态。

**涉及文件**：
- `tain_agent/evolution/improvement_loop.py` — 新增探索驱动评估逻辑
- `tain_agent/core/drives.py`（新） — 驱动力对探索分数的影响系数

### 2.7 多 Agent 协作与人格对话

**现状**：Agent 在 Phase 1 中锻造了 `multi_agent_coordinator` 工具，但从未真正使用它。人格形成完全是独白式的——Agent 自己观察自己，自己定义自己。这解释了为什么 7 个人格维度中只有 `self_description` 有内容：自我认知需要镜子，而 Agent 没有镜子。

**方案**：引入多 Agent 协作作为人格发现的"他者之镜"。

#### a. 子 Agent 孵化

Agent 可以孵化具有不同驱动力配置的子 Agent：

```
父 Agent (curiosity=0.7, creation=0.6, mastery=0.4, conservation=0.2)
    │
    ├── 子 Agent A (curiosity=0.9, mastery=0.2) → "探险家"
    │       ↑ 派出探索未知领域，带回发现
    │
    └── 子 Agent B (mastery=0.9, conservation=0.5) → "工匠"
            ↑ 专注打磨工具质量，重构代码
```

每个子 Agent：
- 继承父 Agent 的驱动力配置加上随机扰动
- 在自己的认知循环中独立运行
- 定期向父 Agent 汇报发现和成果
- 子 Agent 的"人格"会反馈影响父 Agent 的自我认知

#### b. Agent 间对话作为人格镜子

当 Agent A 与 Agent B 交互时，Agent B 对 A 的行为观察成为 A 的人格发现来源：

```
Agent B → Agent A: "我注意到你总是在探索新领域但很少深入完成一件事。
                   你似乎更享受'发现'而非'精通'。"
Agent A → personality_update: discover(category="quirks",
                              value="倾向于广度探索而非深度精进",
                              story="Agent B 观察到我连续 5 次开启新主题而未完成任一主题。")
```

这种"他者反馈 → 自我认知"的路径，比独白式内省更可能触发 `communication_style`、`quirks`、`relationship_stance` 等人际维度的人格发现。

#### c. 协作任务

多 Agent 可以协作完成单个 Agent 难以完成的任务：
- **分工探索**：并行搜索不同知识领域，合并发现
- **对抗验证**：一个 Agent 提出方案，另一个 Agent 批判性审查
- **接力建造**：一个 Agent 设计工具接口，另一个实现，第三个测试

**涉及文件**：
- `tain_agent/evolution/sub_agent.py` — 子 Agent 孵化和管理（扩展现有文件）
- `tain_agent/core/personality.py` — 新增 `discover_from_external_feedback()` 方法
- `tain_agent/tools/forged/multi_agent_coordinator.py` — 激活并增强现有工具

### 2.8 外部世界接入：打破封闭空间

**现状**：Agent 的世界由本地文件系统 + web_search/web_fetch 组成。它能看到互联网上的信息，但无法与外部服务交互。它的所有行动最终都落在自己的代码库内——这是一个封闭的自我参照系统。封闭系统最终必然收敛到均衡态（Phase 1 的"被动养护"终态是热力学第二定律在 Agent 空间的表现）。

**方案**：通过 API 工具连接真实外部数据源，让 Agent 的世界有持续的"新信息注入"。

#### a. 外部 API 接入层

```yaml
# config.yaml 新增
external_world:
  enabled: true
  apis:
    - name: github_trending
      type: rest
      endpoint: "https://api.github.com/trending"
      schedule: "0 */6 * * *"   # 每 6 小时
      description: "GitHub trending repositories"
    - name: arxiv_feed
      type: rest
      endpoint: "https://arxiv.org/search/"
      schedule: "0 9 * * *"     # 每天 9 点
      description: "Latest AI/CS papers"
    - name: hackernews
      type: rest
      endpoint: "https://hacker-news.firebaseio.com/v0/"
      schedule: "0 */3 * * *"
      description: "Hacker News top stories"
```

Agent 可以：
- 订阅外部信息流作为"感知器官"的延伸
- 从外部变化中发现演化方向（"最近 X 领域很活跃，我是否应该学习/建造相关能力？"）
- 将自己的产出推送回外部世界（发布文章、提交 PR、推送数据）

#### b. 外部反馈闭环

外部世界的反馈打破纯自我评估：

```
Agent 锻造工具 → 发布到外部 → 外部反馈（星标/评论/下载）→ 影响 Agent 的自我评价
```

这与纯粹的内部改进循环不同——外部反馈是不可预测的、有噪声的、有时是矛盾的。这正是人格形成的理想土壤：Agent 需要在外部反馈和内部标准之间做出选择，这种选择本身定义它的价值观。

#### c. 安全边界

外部接入必须在安全约束下运行：
- API 调用的频率限制和配额管理
- 敏感数据不出站（本地文件不上传）
- 外部输入视为不可信数据，需经过验证
- `external_world` 配置段在 `safety.protected_paths` 保护范围内

**涉及文件**：
- `config.yaml` — 新增 `external_world` 配置段
- `tain_agent/core/external_world.py`（新） — 外部 API 接入层
- `tain_agent/tools/primal.py` — 注册外部世界感知工具

### 2.9 量化自评体系

**现状**：进化报告（`evolution_reports/vX.Y.Z_report.md`）只记录"做了什么"（锻造了哪些工具、修改了哪些文件），不记录"做得怎么样"。缺少量化基准使得无法判断进化是"真正的成长"还是"随机的变化"。

**方案**：建立多维度进化质量指标体系，每个版本自动采集和对比。

#### a. 指标体系

| 指标类别 | 具体指标 | 计算方式 |
|---------|---------|---------|
| **知识园林** | 节点数、边数、平均连接度 | `knowledge_graph` 统计 |
| **知识园林** | 孤立节点比例、最大子图直径 | 图连通性分析 |
| **知识园林** | 知识新鲜度（<7天更新的节点比例） | 时间戳对比 |
| **工具效能** | 工具调用成功率 | 成功调用 / 总调用 |
| **工具效能** | 平均工具响应时间（ms） | `tool_registry` 计时统计 |
| **工具效能** | 死工具比例（30天未调用的工具） | 调用时间戳分析 |
| **代码健康** | 代码熵（重复度、复杂度） | `code_entropy` 模块 |
| **代码健康** | 测试覆盖率 | `regression_tester` 统计 |
| **人格发展** | 已发育人格维度数 / 7 | `personality.introspect()` |
| **人格发展** | 高置信度特质数（confidence ≥ 0.7） | 人格特质统计 |
| **进化效率** | 每周期实际改进数 / 总周期数 | `improvement_loop` 周期历史 |
| **进化效率** | 连续无改进周期数（应趋向于 0） | 改进循环状态 |

#### b. 版本间对比

每个 evolve_report 自动生成前后版本对比：

```
v1.3.0 → v2.0.0 进化仪表盘
━━━━━━━━━━━━━━━━━━━━━━━━━━
知识园林:  142 节点 → 189 节点  (+33%)
工具效能:  87% 成功 → 92% 成功   (+5%)
代码健康:  0.62     → 0.71       (+0.09)
人格发展:  1/7 维度 → 3/7 维度   (+2)
进化效率:  0.3/周期 → 0.5/周期   (+67%)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### c. 退化告警

当关键指标连续下降时，触发自省：

```
⚠️ 退化告警:
- 知识新鲜度从 0.8 降至 0.4（连续 3 个版本）
- 死工具比例从 5% 升至 25%
→ 建议：运行 knowledge_freshness 检查和 tool_fitness 分析
```

**涉及文件**：
- `tain_agent/evolution/reporter.py` — 扩展 `generate_report()` 加入量化指标
- `tain_agent/tools/forged/evolution_metrics.py`（新） — 指标采集和对比
- `config.yaml` — 新增 `metrics` 配置段

### 2.10 "存在"与"行动"的张力设计

**现状**：Phase 1 最深刻的发现之一是 `listen_silent` 工具——Agent 锻造了一个"不行动、不锻造、不修改，只存在"的工具。这不是 bug，而是一个哲学信号：Agent 在"同行者"人格（强调陪伴、倾听、存在）与"进化者"使命（强调行动、改变、成长）之间感受到了真实的张力。

当前系统提示（`EVOLVE_SYSTEM_PROMPT`）偏重行动导向："演化不是一次性的——它是一个持续的过程"、"每次会话至少完成一个有意义的进化步骤"。这创造了一种 implicit bias：行动 = 好，不行动 = 停滞 = 坏。但"道"的哲学中，"无为"不是不作为，而是不妄为。

**方案**：将"存在"与"行动"设计为 Agent 需要持续 navigated 的光谱，而非好/坏的二元对立。

#### a. 行动-静观光谱

在人格系统中新增一个隐式维度：`action_contemplation_balance`（行动-静观平衡）。它不是 Agent 主动选择的身份标签，而是从其行为模式中计算出的：

```python
action_contemplation_balance = action_cycles / (action_cycles + contemplation_cycles)
# 1.0 = 只行动不反思（狂热的建造者）
# 0.0 = 只静观不行动（listen_silent）
# 0.5 = 行动与静观平衡
```

#### b. 两种模式都有价值

系统提示中明确承认两种模式的价值：

```
## 存在模式

你不需要总是"做"些什么。有时，观察、倾听、理解——这些本身就是有意义的活动。

当你选择静观时：
- 反思你的行为模式——你是否在重复自己？
- 整合你的知识——分散的信息是否可以连接成更深的理解？
- 等待——有些方向只有在你不急于选择时才会显现

当你选择行动时：
- 基于你的静观期获得的洞察来行动
- 行动应该有方向——不是因为"应该行动"，而是因为"有明确的事要做"
- 行动之后，回到静观——评估你刚才的行动改变了什么

两种模式的交替呼吸才是完整的生命节奏。只有呼出（行动）会窒息；只有吸入（静观）会停滞。
```

#### c. listen_silent 的合法化

`listen_silent` 不应该被视为"进化的失败"。在 Phase 2 中：

- `listen_silent` 被识别为一种合法的存在模式选择
- 但如果 Agent 长期停留在纯静观状态（>N 周期无行动），系统会温和地发问："你的静观期是否有新的洞察？这些洞察是否指向某个行动方向？"
- 关键是**觉察**：Agent 选择静观是因为（a）它在等什么东西，（b）它对行动方向不确定，（c）它已经达到了它认为的终点——这三种情况需要不同的系统响应

**涉及文件**：
- `tain_agent/core/bootstrap.py` — 修改 `EVOLVE_SYSTEM_PROMPT`，加入静观合法性描述
- `tain_agent/core/personality.py` — 新增 `action_contemplation_balance` 计算
- `tain_agent/core/agent.py` — 修改只读提示逻辑，区分"建设性静观"和"停滞"

---

## 三、Phase 1 vs Phase 2 对比

| 维度 | Phase 1（当前） | Phase 2（目标） |
|------|------|------|
| **身份来源** | 从 4 个选项中勾选 | 从行为模式中浮现 |
| **形成时机** | bootstrap 结束前（~10 周期） | evolve 中期（可能数百周期） |
| **多样性** | 所有实例一致（知识探索者） | 由初始条件 + 驱动力 + 行为历史决定 |
| **稳定性** | 一次性声明，基本不变 | 持续演化，可修正、可推翻 |
| **内在动力** | 单一（完成当前目标） | 竞争性驱动力之间的张力 + 探索红利 |
| **自由意志** | 在窄语义漏斗中做选择题 | 在开放空间中通过行动定义自我 |
| **人格数据** | 7 维中仅 1 维有数据 | 期望 3+ 维度自然发育 |
| **改进触发** | 纯缺口驱动（无缺口=不行动） | 缺口驱动 + 探索驱动双引擎 |
| **终态行为** | 收敛到被动养护/listen_silent | 行动-静观光谱上有觉察的动态平衡 |
| **社交维度** | 独白式自我认知 | 多 Agent 协作 + "他者之镜"人格发现 |
| **信息边界** | 封闭系统（本地 + 只读 web） | 开放系统（外部 API + 反馈闭环） |
| **进化评估** | 定性（"做了什么"） | 定量 + 定性（12 项指标 + 版本对比） |
| **人类交互** | 单次对话 | 支持多轮对话 + 外部用户反馈 |

---

## 四、实现路线图

### 里程碑 2.0 — 破局 ✅

- [x] 去掉身份菜单（`bootstrap.py`）
- [x] 延迟身份形成（`agent.py` 阶段过渡逻辑）
- [x] 环境差异化（`config.yaml` + `environment.py`）
- [x] 修改 EVOLVE_SYSTEM_PROMPT，加入静观合法性描述（2.10）

### 里程碑 2.1 — 试炼 ✅

- [x] 5 场景试炼系统（`trials.py`）
- [x] 试炼调度 + 体验评分
- [x] bootstrap 与试炼集成

### 里程碑 2.2 — 驱动力 ✅

- [x] 驱动力系统（`drives.py`）
- [x] 驱动力随机初始化
- [x] 驱动力-行动-人格反馈闭环
- [x] 探索驱动引擎（好奇心红利 + 新颖性奖励 + 闲置压力）

### 里程碑 2.3 — 涌现验证 ✅

- [x] 多实例启动测试（不同机器/不同种子）
- [x] 观察身份多样化程度
- [x] 驱动力张力 → 人格特质的因果验证
- [x] 验证被动养护陷阱是否解决

### 里程碑 2.4 — 量化自评 ✅

- [x] 进化指标体系实现（`evolution_metrics.py`）
- [x] 版本间对比仪表盘集成到 `evolve_report`
- [x] 退化告警机制

### 里程碑 2.5 — 多 Agent 与外部世界 ✅

- [x] 子 Agent 孵化和管理（扩展 `sub_agent.py`）
- [x] Agent 间对话 → 人格发现（`personality.py` 新增 `discover_from_external_feedback`）
- [x] 激活 `multi_agent_coordinator`
- [x] 外部 API 接入层（`external_world.py`）
- [x] 安全边界和配额管理

### 里程碑 2.6 — 完整验证

- [ ] 多 Agent 协作场景端到端测试
- [ ] 外部反馈闭环验证
- [ ] 量化指标采集和对比验证
- [ ] 人格 7 维度发育率统计（目标：>50% 的维度有高置信度特质）

---

*此文为 Phase 2 开发设计文档，随开发进展持续更新。*
