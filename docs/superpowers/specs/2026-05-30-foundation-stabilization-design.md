# 稳基迭代 (Foundation Stabilization) · 设计文档

**日期**: 2026-05-30  
**来源**: 项目深度审查报告（docs/evaluation-report.md）  
**范围**: P0（3项）+ P1（7项）+ 精选 P2（8项）= 18 项  
**目标**: 不增加新功能，代码质量从 2.95/5 → ~3.8/5

---

## 架构总览

五个独立工作流，按依赖关系排序：

```
A. 清理 ──┐
B. 版本与配置 ──┤
               ├── C. run() 拆分 + Mixin 契约 + 日志
               │
D. 重试 + agent 复用 + 工具声明式 + 持久化
               │
               └── E. 测试补强
```

**不涉及（留给后续阶段）**:
- 进化循环代码生成闭合（P3-21，架构级新功能）
- Web UI 认证限流（P3-22）
- 驱动力与进化因果链接（P3-23）
- 容器化部署（P3-24）
- 文档同步（P3-25）

---

## 工作流 A · 清理（Cleanup）

### A1. 移除 `external_world` 子系统

- **`bootstrap.py`**: 删除 `_register_external_world_tools()` 函数及其调用点
- **`config.yaml`**: 删除 `external_world` 配置节
- **`tain_agent/core/external_world.py`**: 删除文件（无任何导入者）

### A2. 移除 `trial_scheduler` 子系统

- **`bootstrap.py`**: 删除 `_register_trial_tools()` 函数及其调用点
- **`agent_phase.py`**: 清理 `_should_advance_from_bootstrap` 中残留的 trial_scheduler 引用
- **`emergence_verifier.py`**: 移除或注释直接实例化 `TrialScheduler` 的代码
- **`tain_agent/core/trials.py`**: 删除文件

### A3. 清理 SELF_DEFINE 死代码

- **`agent.py`**: 删除未使用的 `SELF_DEFINE_SYSTEM_PROMPT` / `SPECIFIED_SELF_DEFINE_SYSTEM_PROMPT` 导入；更新 docstring 从三阶段（BOOTSTRAP → SELF_DEFINE → EVOLVE）改为两阶段（explore → work）
- **`agent_phase.py`**: 删除 `_should_advance_from_bootstrap()`；删除 `_should_advance_from_self_define()`
- **`bootstrap.py`**: 删除 SELF_DEFINE 相关提示词常量

### A4. 消除 `estimate_tokens` 四重定义

- **`utils/token_utils.py`**: 保留为唯一实现，添加 `model: str` 参数
- **`tools/templates.py`**: `from tain_agent.utils.token_utils import estimate_tokens`
- **`core/memory.py`**: 同上
- **`core/conversation.py`**: 同上

### A5. 修复 bootstrap 配置节

- **`config.yaml`**: `bootstrap` 节 → `exploration` 节，保留 `max_exploration_cycles`、`min_bootstrap_cycles`
- **`agent_config.py`**: 读取路径从 `bootstrap.*` → `exploration.*`
- **`agent.py`**: 将 `len(self._bootstrap_action_categories) >= 3` 替换为配置值驱动

---

## 工作流 B · 版本与配置统一（Version & Config Unification）

### B1. 单一版本源

- **`tain_agent/__init__.py`**: `__version__ = "0.5.0"` 为唯一版本定义
- **`webui/app.py`**, **`webui/data.py`**, **`webui/routes/pages.py`** (4处): 硬编码 `"0.4.3"` → `from tain_agent import __version__`
- **`tain_agent/core/agent_config.py`**: 默认值 `"0.4.3"` → `__version__`
- **`tain_agent/core/agent_factory.py`**: `check_compatibility` 中的版本号 → `__version__`
- **`runtime/`**: `3.0.0-dev` 统一或标注为独立版本

### B2. config schema 验证

新增 `tain_agent/core/config_schema.py`（Pydantic model，~80-100行）。

核心模型结构：
- `LLMConfig(model, max_tokens, temperature, retry: RetryConfig)`
- `AgentConfig(default_agent, timezone, max_cycles: dict[str, int])`
- `FrameworkConfig(version, min_agent_version)`
- `ExplorationConfig(max_exploration_cycles, min_bootstrap_cycles)`
- `AppConfig(framework, agent, llm, exploration, ...)`

**调用点**: `agent_config.py` 的 `_load_config()` 末尾加 `AppConfig(**merged).model_dump()`。

**效果**: 用户配置错误时启动报清晰错误。

---

## 工作流 C · `run()` 拆分 + Mixin 契约 + 日志

### C1. `run()` 按 PRAL 四阶段拆分

将 `agent.py:run()` 290 行重构为：

```python
def run(self) -> None:
    self._running = True
    while self._running:
        self._perceive()
        response = self._reason()
        if response is None:
            continue
        self._act(response)
        self._learn(response)
```

| 方法 | 估行数 | 职责 |
|------|--------|------|
| `_perceive()` | ~40 | 认知环境采集、驱动力快照、system prompt 构建、对话裁剪 |
| `_reason()` | ~60 | LLM 调用（含重试）、响应解析、thinking block 处理。失败/rate limit 返回 None |
| `_act()` | ~80 | 工具调用分发、结果收集、对话追加、action 追踪、readonly 快照 |
| `_learn()` | ~90 | 人格观察、阶段切换检查、检查点、空闲追踪、驱动力探索注入、内省触发、改进循环 tick |

### C2. Mixin Protocol 接口

新增 `tain_agent/core/agent_protocols.py`，定义 4 个 Protocol：

- `ConfigProvider`: `config`, `agent_name`, `workspace_dir`, `_load_config()`
- `SubsystemProvider`: 所有子系统属性（drive_system, personality, tool_registry, conversation, memory 等）
- `CognitionProvider`: `_build_system_prompt()`, `_collect_cognitive_context()`
- `PhaseProvider`: `phase`, `cycle_count`, `_should_advance_phase()`, `_advance_phase()`

Mixin 的 `__init__` 参数使用 Protocol 类型注解。逐步消除 10+ 处 `hasattr` 检查。

### C3. `except Exception` 收窄

9 处 `except Exception` 分类处理：
- 关键子系统（认知采集、人格观察、驱动力、改进循环）→ `except (AttributeError, IOError) as e: logging.warning(...)`
- LLM 重试（5处）→ 保留宽泛捕获但加 `logging.warning(error_details)`

### C4. `print()` → `logging`

- `logging_config.py` 配置 root logger
- `agent.py` 33 处 `print()` → `logging.info/warning/error`
- 格式: `"%(asctime)s [%(levelname)s] %(name)s: %(message)s"`
- daemon 模式日志写入 workspace 文件

---

## 工作流 D · 重试 + Agent 复用 + 工具声明式 + 持久化

### D1. 重试逻辑整合

在 `retry.py` 新增 LLM 专用重试装饰器 `llm_retry`（指数退避 + jitter + 429 特殊处理 + 对话裁剪回调）。`_reason()` 使用该装饰器。消除 `agent.py` 中 ~30 行手动重试代码。

### D2. Agent 惰性缓存 + 变更检测

新增 `webui/agent_cache.py`：

```python
_cache: dict[str, tuple[float, TaoAgent]] = {}  # {name: (mtime, agent)}

def get_agent(name: str, config: dict) -> TaoAgent:
    workspace = WORKSPACE_ROOT / name
    mtime = (workspace / "agent.yaml").stat().st_mtime
    if name in _cache and _cache[name][0] >= mtime:
        return _cache[name][1]
    agent = TaoAgent(config, name)
    _cache[name] = (time.time(), agent)
    return agent

def invalidate_agent(name: str) -> None:
    _cache.pop(name, None)
```

提供 `POST /api/agent/{name}/reload` 端点。

### D3. 工具分类声明式化

`tools/base.py` 的 `Tool` 基类增加 `is_readonly: bool = False`。`_readonly_tools` 改为属性动态计算：

```python
@property
def _readonly_tools(self) -> set[str]:
    return {t.name for t in self.tool_registry.list_tools() if t.is_readonly}
```

### D4. 持久化策略统一

新增 `tain_agent/utils/persist.py`：
- `WritePolicy` enum: `IMMEDIATE | BUFFERED | LAZY`
- 每种状态文件明确标注策略
- 统一 buffer flush 时机：agent 停止时 + 每 10 个循环自动 flush
- JSON 写入使用 `tempfile + rename` 原子写入，防止写入中断导致文件损坏

---

## 工作流 E · 测试补强（Test Hardening）

### E1. 进化系统测试 (`tests/test_pipeline.py`)

不依赖真实 LLM：
- `test_pipeline_detect_gap_returns_candidate` — 缺口检测
- `test_pipeline_design_stage_requires_human` — design 阶段正确停止
- `test_pipeline_verify_rejects_invalid_code` — 质量门拦截不安全工具
- `test_pipeline_register_adds_to_registry` — 注册流程

### E2. LLM 响应解析测试 (`tests/test_llm_parser.py`)

Fixture 构造模拟 SSE chunk 流：
- `test_parse_xml_tool_call_from_text` — 提取 `<tool_call>` XML
- `test_parse_multiple_tool_calls` — 多工具并列解析
- `test_parse_text_and_thinking_blocks` — 思考块与文本块分离
- `test_parse_malformed_xml_falls_back_to_regex` — 格式错误时正则回退
- `test_parse_no_tool_call_pure_text` — 纯文本不误报
- `test_parse_rate_limit_error_message` — rate limit 消息识别

### E3. Web UI 路由测试 (`tests/test_webui_routes.py`)

使用 `TestClient`：
- `test_get_dashboard_returns_200`
- `test_get_create_page_returns_200`
- `test_get_agent_detail_returns_200` (mock workspace)
- `test_post_chat_returns_sse_stream` (mock LLM)
- `test_post_chat_agent_not_found_returns_404`
- `test_get_agent_knowledge_rejects_path_traversal`

### E4. 集成测试 (`tests/test_integration.py`)

使用 `pytest.fixture` 临时 workspace：
- `test_agent_create_run_stop_restart_state_consistency`
- `test_agent_tool_execution_roundtrip` (mock LLM)
- `test_agent_phase_transition_explore_to_work`
- `test_conversation_persists_across_restarts`
- `test_registry_json_survives_corruption`

---

## 文件变更汇总

| 工作流 | 新增文件 | 修改文件 | 删除文件 |
|--------|---------|---------|---------|
| A | — | 10 | 2 |
| B | 1 | 7 | — |
| C | 1 | 3 | — |
| D | 2 | 5 | — |
| E | 4 | — | — |
| **合计** | **8** | **25** | **2** |

---

## 风险评估

| 风险 | 概率 | 缓解 |
|------|------|------|
| `run()` 拆分为 PRAL 后行为不一致 | 中 | 拆分前先为当前 `run()` 行为写特征测试 |
| agent 惰性缓存导致状态过期 | 低 | mtime 变更检测 + `/reload` 手动刷新端点 |
| Pydantic schema 拒绝现有配置格式 | 低 | 先 dump 现有 config，对照定义 model |
| `lazy` persist 策略丢失数据 | 低 | 原子写入保证单文件一致性；agent stop hook flush 所有 buffer |
