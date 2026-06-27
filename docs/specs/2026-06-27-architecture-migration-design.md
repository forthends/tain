# 架构迁移设计：Mixin → Kernel/Plugin 体系

**日期：** 2026-06-27
**版本：** v0.9.0 → v0.10.0
**目标：** 完成 AgentKernel 架构迁移，删除旧 TaoAgent + 6 Mixin + compat 层，AgentKernel 成为唯一路径

---

## 一、背景与动机

### 1.1 当前状态

Tain Agent Framework 正在进行一次架构迁移——从 Mixin-based `TaoAgent` 迁移到 Plugin-based `AgentKernel`：

- **旧架构**：`TaoAgent` + 5 个 Mixin（AgentConfigMixin, AgentSubsystemsMixin, AgentCognitionMixin, AgentPhaseMixin, AgentToolsMixin），通过 `hasattr` 隐式契约通信
- **新架构**：`AgentKernel` → `PRALLoop` + `LifecycleManager` + `Dispatch`，通过 `PluginProtocol` 显式接口通信，7 个 Plugin（Identity, Memory, Tool, Skill, Knowledge, Workflow, Collaboration）+ 1 个 EvaluationPlugin
- **过渡层**：`TaoAgentCompat` 封装 AgentKernel，对外暴露旧 TaoAgent 接口

### 1.2 痛点

insight-report-2026-06-26 识别了以下由旧架构导致的结构性问题：

| 问题 | 报告编号 | 现状 |
|------|---------|------|
| agent.py `run()` 290行 God Method | P1 #10 | PRALLoop 已分解四阶段，但旧代码仍在 |
| Mixin hasattr 地狱（60+ 处） | P2 #13 | agent_protocols.py 已定义 Protocol，但旧 Mixin 仍在用 |
| Web UI 每次请求重建 TaoAgent | P1 #9 | Kernel 轻量初始化为此奠定基础 |
| estimate_tokens 重复定义（3处） | P1 #4 | 待统一 |
| agent.py 手动重试 vs retry.py 重复 | P1 #5 | 待统一 |

### 1.3 设计原则

1. **compat 层是临时的**——迁移完成后删除，AgentKernel 成为唯一对外接口
2. **一次性切换**——所有消费方在单一迭代中完成迁移，避免新旧代码长期共存
3. **功能不退化**——迁移后的框架功能完整度等于旧架构
4. **先补齐，再切换，再清理**——线性推进，每步有明确的完成标准

---

## 二、目标架构

```
消费层:   main.py (CLI)  ·  webui/  ·  dialogue.py  ·  acp/server.py
              ↓                   ↓              ↓              ↓
              └───────────────────┴──────────────┴──────────────┘
                                          │
                                   AgentKernel
                              (唯一对外接口)
                                          │
                    ┌─────────────────┬───┴───┬─────────────────┐
              PRALLoop         LifecycleManager    Dispatch
         (感知→推理→行动→学习)   (Plugin 生命周期)   (事件路由)
                    │                   │                  │
                    └───────────────────┼──────────────────┘
                                        │
        ┌──────────┬──────────┬─────────┼────────┬──────────┬──────────┐
   IdentityPlugin  MemoryPlugin  ToolPlugin  SkillPlugin  KnowledgePlugin
        │              │           │            │              │
        │              │     ┌─────┴─────┐      │              │
        │              │  ToolRegistry  ToolForge │       GoalManager
        │              │     │           │        │         (新增)
        │              │  原生工具    锻造管线      │
        │              │                         │
   WorkflowPlugin  CollaborationPlugin  EvaluationPlugin
```

**关键设计决策：**

- `AgentKernel` 成为唯一入口——所有消费方直接创建 `AgentContext` + `AgentKernel`，不再经过 `TaoAgent` 或 `TaoAgentCompat`
- Plugin 工厂函数标准化——每个消费方使用相同的插件工厂字典，避免重复定义
- 系统提示从 `bootstrap.py` 迁移到 `kernel/prompts.py`，保留提示模板但移除闭包注册逻辑
- dialogue.py 的会话反思逻辑保留，但从"访问 TaoAgent 属性"改为"通过 lifecycle.get() 查询 Plugin 状态"

---

## 三、Phase 1：补齐 Plugin 能力缺口

compat.py 暴露了四个 `→ None` 缺口，加上 dialogue.py 的实际调用链，需要补齐以下能力：

### 3.1 Forge 完整接入 ToolPlugin

**当前状态：** ToolPlugin 已有 `forge()` 方法和 `ClosedForgeCycle`，`AgentKernel._build_routes()` 已注册 `tool.forge` 路由。

**补齐工作：**
- 确认 `ToolPlugin.forge(name, description, code, parameters)` 的 `action` 参数支持 `create`/`update`/`rollback`（v0.8.0 新增的 `--update` 模式在 Plugin 路径中可访问）
- 确保 `get_sandbox_allowlist()` 通过 ToolPlugin 暴露（旧代码在 `bootstrap.py:921`）
- 将 sandbox allowlist 和 quality gate 相关能力内聚到 ToolPlugin
- 暴露 `list_forged()` 方法（dialogue.py 需要）

### 3.2 Goals → KnowledgePlugin 扩展

**当前状态：** 旧 `goals` 提供 `set_goal()`, `complete_goal()`, `list_active()`, `list_completed()`。

**补齐工作：**
- 在 KnowledgePlugin 中新增 `GoalManager` 子组件，对外接口：

```python
class GoalManager:
    def create(self, description: str, success_criteria: str) -> str: ...  # returns goal_id
    def complete(self, goal_id: str, summary: str = "") -> bool: ...
    def list_active(self) -> list[dict]: ...
    def list_completed(self) -> list[dict]: ...
    def get(self, goal_id: str) -> dict | None: ...
```

- 通过 `knowledge.goals` 暴露 GoalManager 实例
- GoalManager 存储目标到 agent workspace 的 `goals.json`，支持跨 session 持久化

### 3.3 Memory 接口标准化

**当前状态：** MemoryPlugin 已实现 `recall()`, `encode()`, `snapshot()`, `restore()`。

**补齐工作：**
- 在 MemoryPlugin 上暴露 `session_memory` 属性，支持 `SessionMemory` 兼容接口
- 确保 `encode()` 方法签名与 PRAL loop 的 `_learn` 调用一致

### 3.4 Personality → IdentityPlugin 合并

**当前状态：** v0.8.0 已完善 personality（workspace_path, disk fallback, T2→T1 sync）。

**补齐工作：**
- 将 Personality 作为 IdentityPlugin 的子组件
- 暴露 `identity.personality.get_context_for_prompt()` 和 `identity.personality.introspect()` 方法
- 确保跨 session 持久化在 Plugin 生命周期中正确触发

### 3.5 不需要补齐的能力

| 旧属性 | 处理方式 |
|--------|---------|
| `capability.assess()` | 编译时统计，由 ToolPlugin.list_tools() + KnowledgePlugin stats 实时计算 |
| `decision_log` | 由 PRAL loop 统一记录，不再作为独立可访问属性 |
| `agent_factory` | Kernel 的 LifecycleManager 已覆盖生命周期管理，Registry 由调用方管理 |

---

## 四、Phase 2：消费方迁移

按依赖复杂度和风险从低到高排列。

### 4.1 agent_factory.py — 直接删除

当前创建 TaoAgent + 写入 `_registry.json`。Kernel 的 `LifecycleManager` 已覆盖生命周期管理。Registry 改为由 CLI/调用方直接管理——创建 AgentKernel 即可，无需工厂包装。

### 4.2 main.py (CLI) — 最小侵入

**当前：**
```python
agent = TaoAgent(config_path, agent_name)
agent.run(autonomous=True)
agent.print_state()
```

**改为：**
```python
ctx = AgentContext(
    agent_name=name, agent_id=...,
    evolution_mode=evolution_mode,
    workspace_path=workspace, config=config,
    kernel_version=__version__,
)
kernel = AgentKernel(ctx)
kernel.load_plugins(STANDARD_FACTORIES)
kernel.run(llm_backend, conversation, drive_system, system_prompt)
# 健康检查通过 lifecycle.all_health_checks()
```

系统提示从 `kernel/prompts.py`（从 bootstrap.py 迁移）加载。LLM backend、conversation、drive system 的创建逻辑内联在 main.py 中（与 compat.py 当前做法一致）。

`STANDARD_FACTORIES` 定义在 `kernel/factories.py`，包含 7 个标准 Plugin：

```python
# kernel/factories.py
from tain_agent.plugins.identity import IdentityPlugin
from tain_agent.plugins.memory import MemoryPlugin
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.skill import SkillPlugin
from tain_agent.plugins.knowledge import KnowledgePlugin
from tain_agent.plugins.workflow import WorkflowPlugin
from tain_agent.plugins.collaboration import CollaborationPlugin

STANDARD_FACTORIES = {
    "identity": IdentityPlugin,
    "memory": MemoryPlugin,
    "tool": ToolPlugin,
    "skill": SkillPlugin,
    "knowledge": KnowledgePlugin,
    "workflow": WorkflowPlugin,
    "collaboration": CollaborationPlugin,
}
```

### 4.3 webui/agent_cache.py — 关键改进点

当前 `get_agent()` 每次创建 `TaoAgent` 实例（报告 P1 #9）。改为 `get_kernel()` 创建 `AgentKernel` 实例并缓存。

缓存键：`(config_mtime, workspace_mtime)`，与当前逻辑一致。
缓存值：`tuple[float, AgentKernel]`。

Kernel 初始化比 TaoAgent 轻（无 Mixin 线性扫描），但仍有 ToolForge 沙箱验证开销——缓存仍有用。

### 4.4 acp/server.py — 会话级缓存

当前每次 ACP 请求创建 TaoAgent。改为：
- 每个 ACP session 缓存一个 AgentKernel 实例（keyed by session ID）
- Session 结束时调用 `kernel.shutdown()`
- 确保不同 ACP 客户端的 agent 状态隔离

### 4.5 dialogue.py — 最大改动

当前通过 `hasattr` 强依赖 TaoAgent 子系统。改动映射：

| 旧访问方式 | 新访问方式 |
|-----------|-----------|
| `agent.memory` | `kernel.lifecycle.get("memory")` |
| `agent.tools.list_tools()` | `kernel.lifecycle.get("tool").list_tools()` |
| `agent.tools.get_claude_tool_definitions()` | ToolPlugin 暴露 `get_claude_tool_definitions()` |
| `agent.forge.list_forged()` | `kernel.lifecycle.get("tool").list_forged()` |
| `agent.goals.create_goal(...)` | `kernel.lifecycle.get("knowledge").goals.create(...)` |
| `agent.personality.get_context_for_prompt()` | `kernel.lifecycle.get("identity").personality.get_context_for_prompt()` |
| `agent.capability.assess()` | 实时聚合各 Plugin 状态 |
| `agent.conversation` | PRAL loop 已管理 conversation |

`_reflect_on_session()` 和 `_shutdown()` 方法保留，内部访问路径改为 Plugin 查询。

### 4.6 chat.py — 轻量调整

当前通过 `hasattr(agent, 'personality')` 检查子系统存在。改为 `kernel.lifecycle.get("identity") is not None`——语义更清晰，消除 hasattr 使用。

---

## 五、Phase 3：清理旧代码

### 5.1 删除清单

| 文件 | 行数 | 清理理由 |
|------|------|---------|
| `core/agent.py` | 723 | 已废弃，被 AgentKernel 取代 |
| `core/agent_config.py` | 105 | Mixin，被 AgentContext + IdentityPlugin 取代 |
| `core/agent_subsystems.py` | 241 | Mixin，被 LifecycleManager.load() 取代 |
| `core/agent_cognition.py` | 238 | Mixin，被 PRALLoop 四阶段 + Plugin hooks 取代 |
| `core/agent_phase.py` | 117 | Mixin，被 PRALLoop 的 phase 逻辑取代 |
| `core/agent_tools.py` | 101 | Mixin，被 ToolPlugin 取代 |
| `core/agent_protocols.py` | 55 | Protocol 定义，迁移后无引用 |
| `core/bootstrap.py` | 1043 | 工具闭包注册，被各 Plugin 原生实现取代 |
| `compat.py` | 165 | 临时兼容层，使命终结 |
| **合计** | **2788** | |

### 5.2 保留并迁移的内容

- `bootstrap.py` 中三个系统提示模板 → `kernel/prompts.py`
- `bootstrap.py` 中 `_TOOL_CATEGORY_MAP` → `ToolPlugin` 内部常量
- `agent_factory.py` — 删除

### 5.3 保留不改的文件

- `core/conversation.py` — PRAL loop 直接使用，接口不变
- `core/llm.py` — LLMBackend，接口稳定
- `core/drives.py` — DriveSystem，PRAL loop 已使用
- `core/dialogue.py` — 保留但内部访问路径适配
- `core/chat.py` — 保留但内部访问路径适配

### 5.4 清理验证

```bash
# 确认无 import 残留
grep -r "from.*agent_config\|from.*agent_subsystems\|from.*agent_cognition\|from.*agent_phase\|from.*agent_tools\|from.*agent_protocols" tain_agent/ main.py webui/
# → 预期：空输出

# 确认 hasattr 在核心层降至零（kernel 协议检查除外）
grep -rn "hasattr" tain_agent/kernel/ tain_agent/plugins/
# → 仅保留 plugin hooks 中的防御性 hasattr（`getattr(plugin, method, None)`）

# 全量测试
pytest tests/ -q
# → 预期：零回归
```

---

## 六、测试策略

### 6.1 Phase 1 完成后（能力补齐验证）

- 补齐 `test_tool_plugin.py` 的 forge cycle 测试（确保 action 参数正确）
- 补齐 `test_knowledge_plugin.py` 的 goal 管理测试
- 补齐 `test_identity_plugin.py` 的 personality 测试
- 新旧工具列表对比——确保 ToolPlugin 覆盖全部 17 类工具

### 6.2 Phase 2 每一步（回归验证）

- 每个消费方迁移后运行全量测试套件：`pytest tests/ -q`
- 确保 718 项测试零回归
- 对 dialogue.py 编写新的 Plugin-aware 集成测试

### 6.3 Phase 3 完成后（最终验证）

- 全量测试通过
- import 残留检查通过
- hasattr 清理检查通过
- 集成测试："创建→运行→停止→重启→验证状态一致性"

---

## 七、风险与缓解

### 7.1 ToolPlugin 覆盖度不足

**风险：** 旧 bootstrap.py 注册了 17 个工具类别，ToolPlugin 可能未覆盖某些类别。

**缓解：** Phase 1 完成时运行工具列表对比——旧 bootstrap.py 的 17 类工具（decision, forge, goals, self_modify, capability, pipeline, loop_control, personality, drives, metrics, sub_agent, reporter, export, test, sandbox_info, introspection, knowledge, diagnostics）vs 新 ToolPlugin + 各 Plugin 暴露的工具列表。差集即为遗漏项，在 Phase 2 开始前补齐。

### 7.2 dialogue.py 的隐式依赖

**风险：** dialogue.py 通过 `hasattr` 访问子系统，编译期无保护。

**缓解：** 迁移前对 dialogue.py 做完整属性访问审计，列出所有 `self.agent.<attr>` 调用点，确认每个在新架构中有对等路径。

### 7.3 conversation checkpoint 兼容性

**风险：** 迁移后 agent 丢失会话历史。

**缓解：** `conversation.py` 本身不被删除——接口不变，PRAL loop 继续使用。Phase 2 完成后运行 "创建→对话→重启→验证历史" 集成测试。

### 7.4 ACP session 隔离

**风险：** 不同 ACP 客户端共享 agent 状态。

**缓解：** ACP 使用 session-scoped kernel 缓存（keyed by session ID），与 Web UI 的 agent-name-scoped cache 分离。

### 7.5 回滚策略

所有变更在独立分支上进行。Phase 1/2/3 各自独立提交，形成三个可独立回滚的变更集。`compat.py` 保留到 Phase 3 最后一步才删除，作为最后的安全网。

---

## 八、不影响的事项

以下框架功能本次迁移不涉及：

- LLM 后端抽象——接口不变
- 安全沙箱（forge pipeline）——ToolPlugin 内部封装，外部行为不变
- 驱动力系统——PRAL loop 继续使用 DriveSystem
- 进化管线（pipeline/lineage/emergence_verifier）——独立模块，不在迁移范围
- Web UI 前端（HTMX + Alpine.js）——仅后端 agent 实例创建逻辑改变
- ACP 协议——仅 agent 创建方式改变，协议不变
- MCP 集成——不受影响
- 消息总线——不受影响
- Guardian 守护进程——不受影响

---

## 九、非目标

本次迁移明确不做以下事项（留待后续迭代）：

- 闭合进化循环中的代码生成瓶颈（报告长期愿景 #10）
- Web UI 添加认证和限流（报告中期 #11）
- 全局 print() → logging 迁移——agent.py 已从 33 处降至 3 处，其余文件后续处理
- 统一持久化策略（报告中期 #14）
- 容器化部署（报告长期愿景 #18）
- 文档-代码版本同步机制（报告长期愿景 #19）
