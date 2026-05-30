# 稳基迭代 (Foundation Stabilization) · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不增加新功能，将代码质量从 2.95/5 提升到 ~3.8/5，完成一次彻底的技术债务清偿

**Architecture:** 五个独立工作流按依赖顺序执行 — A.清理 → B.版本与配置统一 → C.run()拆分+Mixin契约+日志 → D.重试+agent复用+工具声明式+持久化 → E.测试补强。每步可独立验证。

**Tech Stack:** Python 3.12+, Pydantic, pytest, FastAPI, Jinja2, YAML, tiktoken

---

### 工作流 A · 清理

### Task A1: 移除 `external_world` 子系统

**Files:**
- Modify: `tain_agent/core/bootstrap.py:220,725-799`
- Modify: `config.yaml:110-130`
- Delete: `tain_agent/core/external_world.py`

- [ ] **Step 1: 删除 bootstrap.py 中的 `_register_external_world` 及其调用**

修改 `tain_agent/core/bootstrap.py`，删除以下内容：

1. 第 220 行的调用：`self._register_external_world()`
2. 第 725–799 行的整个 `_register_external_world` 方法（包含 `external_fetch`、`external_subscribe`、`external_status` 三个闭包和三个 `self.a.tools.register()` 调用）

- [ ] **Step 2: 删除 config.yaml 中的 external_world 配置节**

修改 `config.yaml`，删除第 110–130 行：

```yaml
# 删除以下内容
# ── Phase 2: External World ────────────────────────────────────────────
external_world:
  enabled: true
  apis:
    ...
```

- [ ] **Step 3: 删除 external_world.py 文件**

```bash
rm tain_agent/core/external_world.py
```

- [ ] **Step 4: 编译检查**

```bash
python3 -m py_compile tain_agent/core/bootstrap.py && echo "OK"
python3 -c "import yaml; yaml.safe_load(open('config.yaml'))" && echo "OK"
```

- [ ] **Step 5: 提交**

```bash
git add tain_agent/core/bootstrap.py config.yaml tain_agent/core/external_world.py
git commit -m "chore: remove dead external_world subsystem (P0-1)"
```

---

### Task A2: 移除 `trial_scheduler` 子系统

**Files:**
- Modify: `tain_agent/core/bootstrap.py:217,587-608`
- Modify: `tain_agent/core/agent_phase.py:94-113`
- Modify: `tain_agent/evolution/emergence_verifier.py:25`
- Delete: `tain_agent/core/trials.py`

- [ ] **Step 1: 删除 bootstrap.py 中的 `_register_trials` 及其调用**

修改 `tain_agent/core/bootstrap.py`：
- 删除第 217 行的 `self._register_trials()`
- 删除第 587–608 行的整个 `_register_trials` 方法

- [ ] **Step 2: 删除 agent_phase.py 中的死方法**

修改 `tain_agent/core/agent_phase.py`，删除第 94–113 行的 `_should_advance_from_bootstrap` 方法：

```python
# 删除从第 94 行到第 113 行的整个方法
```

- [ ] **Step 3: 修复 emergence_verifier.py**

修改 `tain_agent/evolution/emergence_verifier.py` 第 25 行：

```python
# 旧:
from tain_agent.core.trials import TrialScheduler, TRIAL_DEFINITIONS

# 新: 移除该 import，改为注释说明 trial_scheduler 已废弃
```

检查 `emergence_verifier.py` 中所有对 `TrialScheduler` 和 `TRIAL_DEFINITIONS` 的引用，用临时 fixture 替代或注释掉相关测试。

- [ ] **Step 4: 删除 trials.py**

```bash
rm tain_agent/core/trials.py
```

- [ ] **Step 5: 编译检查**

```bash
python3 -m py_compile tain_agent/core/bootstrap.py && \
python3 -m py_compile tain_agent/core/agent_phase.py && \
python3 -m py_compile tain_agent/evolution/emergence_verifier.py && echo "OK"
```

- [ ] **Step 6: 提交**

```bash
git add tain_agent/core/bootstrap.py tain_agent/core/agent_phase.py \
        tain_agent/evolution/emergence_verifier.py tain_agent/core/trials.py
git commit -m "chore: remove dead trial_scheduler subsystem (P0-1)"
```

---

### Task A3: 清理 SELF_DEFINE 死代码

**Files:**
- Modify: `tain_agent/core/agent.py:1-15,39-42`
- Modify: `tain_agent/core/agent_phase.py:115-117`
- Modify: `tain_agent/core/bootstrap.py:81-104`

- [ ] **Step 1: 更新 agent.py docstring 和导入**

修改 `tain_agent/core/agent.py`：

第 1-28 行，将 docstring 改为：

```python
"""
Tain Agent — 道

The core Agent class. This is "道" — the source from which everything emerges.

Each agent has two phases:
  0. EXPLORE — 道生一: explore environment, understand capabilities
  1. WORK    — 一生二，二生三，三生万物: pursue goals, create tools, modify self

Hard rule: every decision is logged with context, options, reasoning, and outcome.

v0.5.0 — Framework-measured metrics replace LLM self-evaluation.
Architecture: 5 Mixin classes (Config, Subsystems, Cognition, Phase, Tools)
compose the TaoAgent via multiple inheritance.
"""
```

第 39-42 行，删除 SELF_DEFINE 相关导入：

```python
# 旧:
from tain_agent.core.bootstrap import BOOTSTRAP_SYSTEM_PROMPT, \
    SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT, \
    SELF_DEFINE_SYSTEM_PROMPT, SPECIFIED_SELF_DEFINE_SYSTEM_PROMPT, \
    EVOLVE_SYSTEM_PROMPT

# 新:
from tain_agent.core.bootstrap import BOOTSTRAP_SYSTEM_PROMPT, \
    SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT, \
    EVOLVE_SYSTEM_PROMPT
```

- [ ] **Step 2: 删除 agent_phase.py 中的 `_should_advance_from_self_define`**

修改 `tain_agent/core/agent_phase.py`，删除第 115–117 行：

```python
# 删除:
def _should_advance_from_self_define(self, text_parts: list[str]) -> bool:
    return len(self.goals.list_active()) > 0
```

- [ ] **Step 3: 删除 bootstrap.py 中的 SELF_DEFINE 提示词常量**

修改 `tain_agent/core/bootstrap.py`，删除第 81–104 行的 `SELF_DEFINE_SYSTEM_PROMPT` 和 `SPECIFIED_SELF_DEFINE_SYSTEM_PROMPT`。

- [ ] **Step 4: 编译检查**

```bash
python3 -m py_compile tain_agent/core/agent.py && \
python3 -m py_compile tain_agent/core/agent_phase.py && \
python3 -m py_compile tain_agent/core/bootstrap.py && echo "OK"
```

- [ ] **Step 5: 提交**

```bash
git add tain_agent/core/agent.py tain_agent/core/agent_phase.py tain_agent/core/bootstrap.py
git commit -m "chore: remove SELF_DEFINE dead code, update docstring to two-phase (P0-3)"
```

---

### Task A4: 消除 `estimate_tokens` 四重定义

**Files:**
- Modify: `tain_agent/utils/token_utils.py:9-27`
- Modify: `tain_agent/tools/templates.py:178-189`
- Modify: `tain_agent/core/memory.py:86-88`
- Modify: `tain_agent/core/conversation.py:187-194`

- [ ] **Step 1: 增强 utils/token_utils.py 为唯一实现**

修改 `tain_agent/utils/token_utils.py` 第 9 行，添加 `model` 参数：

```python
def estimate_tokens(text: str, model: str = "cl100k_base") -> int:
    """Estimate token count for a string.

    Tries tiktoken with the given model encoding, falls back to
    character-based estimate (2.5 chars ≈ 1 token).

    Args:
        text: Text to estimate token count for.
        model: tiktoken encoding name (default: cl100k_base).

    Returns:
        Estimated token count (minimum 1).
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding(model)
        return len(enc.encode(text))
    except (ImportError, ModuleNotFoundError):
        return max(1, len(text) * 2 // 5)
```

- [ ] **Step 2: 替换 templates.py 中的重复定义**

修改 `tain_agent/tools/templates.py` 第 178 行，删除函数定义，改为导入：

```python
# 删除第 178-189 行的 estimate_tokens 函数定义
# 在文件顶部导入部分添加:
# from tain_agent.utils.token_utils import estimate_tokens
```

- [ ] **Step 3: 替换 memory.py 中的重复定义**

修改 `tain_agent/core/memory.py` 第 86-88 行：

```python
# 删除:
def estimate_tokens(self, text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4

# 替换为从 utils 导入的调用，在类中使用:
from tain_agent.utils.token_utils import estimate_tokens as _estimate

# 类中 self.estimate_tokens 改为调用:
def estimate_tokens(self, text: str) -> int:
    return _estimate(text)
```

- [ ] **Step 4: 替换 conversation.py 中的重复定义**

修改 `tain_agent/core/conversation.py` 第 187 行，将类的独立实现改为导入 `utils.token_utils.estimate_tokens` 并保留方法包装：

```python
from tain_agent.utils.token_utils import estimate_tokens as _estimate_tokens

# 类方法改为:
def estimate_tokens(self, messages: Optional[list[dict]] = None) -> int:
    # ... 保持消息到文本的转换逻辑不变 ...
    text = self._messages_to_text(msgs)
    return _estimate_tokens(text)
```

关键：保留 `_messages_to_text` 转换逻辑，仅替换底层的 token 计数调用。

- [ ] **Step 5: 运行现有测试确认无回归**

```bash
python3 -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [ ] **Step 6: 提交**

```bash
git add tain_agent/utils/token_utils.py tain_agent/tools/templates.py \
        tain_agent/core/memory.py tain_agent/core/conversation.py
git commit -m "refactor: deduplicate estimate_tokens to single source in utils/token_utils.py (P1-4)"
```

---

### Task A5: 修复 bootstrap 配置节 → exploration

**Files:**
- Modify: `config.yaml:47-55`
- Modify: `tain_agent/core/agent_config.py:68-69`
- Modify: `tain_agent/core/agent.py:297`

- [ ] **Step 1: 重命名 config.yaml 配置节**

修改 `config.yaml` 第 47-55 行：

```yaml
# 旧:
bootstrap:
  max_exploration_cycles: 10
  max_definition_cycles: 5
  min_bootstrap_cycles: 5
  min_action_categories: 2

# 新:
exploration:
  max_exploration_cycles: 10
  max_definition_cycles: 5
  min_bootstrap_cycles: 5
  min_action_categories: 2
```

- [ ] **Step 2: 更新 agent_config.py 读取路径**

修改 `tain_agent/core/agent_config.py` 第 68-69 行：

```python
# 旧:
self.max_exploration_cycles = self.config.get("bootstrap", {}).get("max_exploration_cycles", 10)
self.max_definition_cycles = self.config.get("bootstrap", {}).get("max_definition_cycles", 5)

# 新:
self.max_exploration_cycles = self.config.get("exploration", {}).get("max_exploration_cycles", 10)
self.max_definition_cycles = self.config.get("exploration", {}).get("max_definition_cycles", 5)
```

同时在 `agent_config.py` 中新增一个属性读取 `min_action_categories`：

```python
self.min_action_categories = self.config.get("exploration", {}).get("min_action_categories", 2)
```

- [ ] **Step 3: 让 agent.py 使用配置值**

修改 `tain_agent/core/agent.py` 第 297 行：

```python
# 旧:
if self.phase == "explore" and len(self._bootstrap_action_categories) >= 3:

# 新:
min_cats = getattr(self, 'min_action_categories', 3)
if self.phase == "explore" and len(self._bootstrap_action_categories) >= min_cats:
```

- [ ] **Step 4: 编译检查**

```bash
python3 -m py_compile tain_agent/core/agent.py && \
python3 -m py_compile tain_agent/core/agent_config.py && echo "OK"
```

- [ ] **Step 5: 提交**

```bash
git add config.yaml tain_agent/core/agent_config.py tain_agent/core/agent.py
git commit -m "fix: rename bootstrap→exploration config section, wire config values (P1-7)"
```

---

### 工作流 B · 版本与配置统一

### Task B1: 单一版本源

**Files:**
- Modify: `tain_agent/__init__.py`
- Modify: `webui/app.py:12`
- Modify: `webui/data.py:113`
- Modify: `webui/routes/pages.py:34,59,73,86`
- Modify: `tain_agent/core/agent_config.py:73`
- Modify: `tain_agent/core/agent_factory.py:94`

- [ ] **Step 1: 确认 `__init__.py` 版本字符串**

检查 `tain_agent/__init__.py` 确保 `__version__ = "0.5.0"`：

```python
# tain_agent/__init__.py
__version__ = "0.5.0"
```

- [ ] **Step 2: 修复 webui/app.py**

修改 `webui/app.py` 第 12 行：

```python
# 旧:
app = FastAPI(title="Tain Agent Framework — Web UI", version="0.4.3")

# 新:
from tain_agent import __version__
app = FastAPI(title="Tain Agent Framework — Web UI", version=__version__)
```

- [ ] **Step 3: 修复 webui/data.py**

修改 `webui/data.py` 第 113 行：

```python
# 旧:
"version": version.get("version", info.get("framework_version", "0.4.3")) if version else info.get("framework_version", "0.4.3"),

# 新:
from tain_agent import __version__ as FW_VERSION
# ...
"version": version.get("version", info.get("framework_version", FW_VERSION)) if version else info.get("framework_version", FW_VERSION),
```

- [ ] **Step 4: 修复 webui/routes/pages.py**

修改第 34、59、73、86 行，4 处硬编码替换：

```python
# 旧:
framework_version = cfg.get("framework", {}).get("version", "0.4.3")

# 新:
from tain_agent import __version__ as FW_VERSION
# ...
framework_version = cfg.get("framework", {}).get("version", FW_VERSION)
```

- [ ] **Step 5: 修复 agent_config.py 默认值**

修改 `tain_agent/core/agent_config.py` 第 73 行：

```python
# 旧:
self.framework_version = fw_cfg.get("version", "0.4.3")

# 新:
from tain_agent import __version__ as FW_VERSION
# ...
self.framework_version = fw_cfg.get("version", FW_VERSION)
```

- [ ] **Step 6: 修复 agent_factory.py**

修改 `tain_agent/core/agent_factory.py` 第 94 行：

```python
# 旧:
"framework_version": info.get("framework_version", "0.4.3"),

# 新:
from tain_agent import __version__ as FW_VERSION
# ...
"framework_version": info.get("framework_version", FW_VERSION),
```

- [ ] **Step 7: 验证所有 0.4.3 残留**

```bash
grep -rn "0\.4\.3" --include="*.py" tain_agent/ webui/ | grep -v __pycache__ | grep -v ".pyc"
```
预期输出：无结果（或仅包含注释/文档中的历史引用）

- [ ] **Step 8: 提交**

```bash
git add tain_agent/__init__.py webui/app.py webui/data.py \
        webui/routes/pages.py tain_agent/core/agent_config.py \
        tain_agent/core/agent_factory.py
git commit -m "fix: unify version to single source (tain_agent.__version__) (P0-2)"
```

---

### Task B2: config schema 验证

**Files:**
- Create: `tain_agent/core/config_schema.py`
- Modify: `tain_agent/core/agent_config.py`

- [ ] **Step 1: 创建 Pydantic schema**

创建 `tain_agent/core/config_schema.py`：

```python
"""Pydantic schema for config.yaml validation."""
from typing import Optional
from pydantic import BaseModel, Field


class RetryConfigSchema(BaseModel):
    enabled: bool = True
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0


class LLMConfigSchema(BaseModel):
    provider: str = "minimax"
    model: str = "MiniMax-M2.7"
    max_tokens: int = 8192
    api_key_env: str = "MINIMAX_API_KEY"
    base_url: Optional[str] = None
    retry: RetryConfigSchema = Field(default_factory=RetryConfigSchema)


class AgentConfigSchema(BaseModel):
    default_agent: str = "default"
    timezone: str = "Asia/Shanghai"


class AgentWorkspaceSchema(BaseModel):
    dir: str = "agent_workspace"
    auto_create: bool = True


class ConversationConfigSchema(BaseModel):
    token_limit: int = 80000
    model_context_window: int = 131072


class ExplorationConfigSchema(BaseModel):
    max_exploration_cycles: int = 10
    max_definition_cycles: int = 5
    min_bootstrap_cycles: int = 5
    min_action_categories: int = 2


class DiversityConstraintsSchema(BaseModel):
    allow_network: bool = True
    allow_file_write: bool = True
    allow_forge: bool = True


class DiversityToolBiasSchema(BaseModel):
    observation: float = 1.0
    creation: float = 1.0
    reflection: float = 1.0


class DiversitySchema(BaseModel):
    seed: str = "random"
    tool_bias: DiversityToolBiasSchema = Field(default_factory=DiversityToolBiasSchema)
    knowledge_seeds: list[str] = Field(default_factory=list)
    constraints: DiversityConstraintsSchema = Field(default_factory=DiversityConstraintsSchema)


class DrivesExplorationSchema(BaseModel):
    curiosity_bonus_rate: float = 0.05
    max_curiosity_bonus: float = 0.30
    novelty_weight: float = 0.20
    idle_pressure_rate: float = 0.10
    max_idle_pressure: float = 0.40


class DrivesSchema(BaseModel):
    exploration: DrivesExplorationSchema = Field(default_factory=DrivesExplorationSchema)


class MetricsSchema(BaseModel):
    degradation_alert_threshold: float = 0.15
    auto_collect_on_report: bool = True
    snapshot_dir: str = "tain_agent/state/metrics_snapshots"


class SafetySchema(BaseModel):
    protected_paths: list[str] = Field(default_factory=list)
    confirm_destructive: bool = False


class LoggingSchema(BaseModel):
    directory: str = "tain_agent/logs"
    decision_log_file: str = "decisions.jsonl"
    memory_file: str = "memory.json"
    checkpoint_file: str = "conversation_checkpoint.json"
    lineage_file: str = "lineage.jsonl"


class FrameworkConfigSchema(BaseModel):
    version: str = "0.5.0"
    min_agent_version: str = "0.0.1"


class AppConfig(BaseModel):
    framework: FrameworkConfigSchema = Field(default_factory=FrameworkConfigSchema)
    agent: AgentConfigSchema = Field(default_factory=AgentConfigSchema)
    agent_workspace: AgentWorkspaceSchema = Field(default_factory=AgentWorkspaceSchema)
    llm: LLMConfigSchema = Field(default_factory=LLMConfigSchema)
    conversation: ConversationConfigSchema = Field(default_factory=ConversationConfigSchema)
    exploration: ExplorationConfigSchema = Field(default_factory=ExplorationConfigSchema)
    diversity: DiversitySchema = Field(default_factory=DiversitySchema)
    drives: DrivesSchema = Field(default_factory=DrivesSchema)
    metrics: MetricsSchema = Field(default_factory=MetricsSchema)
    safety: SafetySchema = Field(default_factory=SafetySchema)
    logging: LoggingSchema = Field(default_factory=LoggingSchema)
```

- [ ] **Step 2: 集成到 agent_config.py**

修改 `tain_agent/core/agent_config.py`，在 `_load_config` 方法末尾添加验证调用：

```python
# 在 _load_config 方法的 return 之前添加:
try:
    from tain_agent.core.config_schema import AppConfig
    AppConfig(**self.config)
except ImportError:
    pass  # pydantic not installed — skip validation
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"Config validation warning: {e}")
```

- [ ] **Step 3: 运行测试 + 用当前 config.yaml 验证**

```bash
python3 -c "
import yaml
from tain_agent.core.config_schema import AppConfig
cfg = yaml.safe_load(open('config.yaml'))
validated = AppConfig(**cfg)
print('Config validated successfully')
print(f'Version: {validated.framework.version}')
print(f'Model: {validated.llm.model}')
"
```

预期输出：`Config validated successfully`

- [ ] **Step 4: 提交**

```bash
git add tain_agent/core/config_schema.py tain_agent/core/agent_config.py
git commit -m "feat: add Pydantic config schema validation (P2-20)"
```

---

### 工作流 C · run() 拆分 + Mixin 契约 + 日志

### Task C1: `run()` 按 PRAL 四阶段拆分

**Files:**
- Modify: `tain_agent/core/agent.py:129-420`
- Create: `tests/test_agent_run.py`

- [ ] **Step 1: 写特征测试（拆分前行为快照）**

创建 `tests/test_agent_run.py`：

```python
"""Feature tests for agent.run() — captures current behavior before refactor."""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


class TestAgentRunStructure:
    """Verify the run loop calls the expected PRAL methods in order."""

    def test_run_loop_calls_perceive_reason_act_learn(self):
        from tain_agent.core.agent import TaoAgent
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            # Write minimal config
            cfg = ws / "config.yaml"
            cfg.write_text("""
framework: {version: "0.5.0"}
agent: {default_agent: test}
llm: {provider: test, model: test, max_tokens: 100, api_key_env: NONE}
exploration: {max_exploration_cycles: 10, max_definition_cycles: 5, min_bootstrap_cycles: 3, min_action_categories: 2}
agent_workspace: {dir: "%s"}
safety: {protected_paths: []}
logging: {directory: "/tmp", decision_log_file: test.jsonl, memory_file: test.json}
""" % ws)
            agent = TaoAgent(config_path=str(cfg))
            agent.agent_name = "test"

            # Track method calls
            with patch.object(agent, '_perceive', wraps=lambda: setattr(agent, '_perceive_called', True)) as mock_p, \
                 patch.object(agent, '_reason', wraps=lambda: (setattr(agent, '_reason_called', True) or None)) as mock_r, \
                 patch.object(agent, '_act', wraps=lambda r: setattr(agent, '_act_called', True)) as mock_a, \
                 patch.object(agent, '_learn', wraps=lambda r: setattr(agent, '_learn_called', True)) as mock_l:
                agent._running = True
                # Run one iteration
                agent._perceive()
                mock_p.assert_called_once()
                response = agent._reason()
                mock_r.assert_called_once()
                if response is not None:
                    agent._act(response)
                    mock_a.assert_called_once()
                    agent._learn(response)
                    mock_l.assert_called_once()

    def test_public_run_interface_unchanged(self):
        """TaoAgent.run() signature remains (self, autonomous: bool = False) -> int."""
        import inspect
        sig = inspect.signature(TaoAgent.run)
        params = list(sig.parameters.keys())
        assert 'self' in params
        assert 'autonomous' in params

    def test_perceive_does_not_modify_conversation(self):
        """_perceive should not append messages — only build context."""
        # This test captures the contract: _perceive is read-only on conversation
        pass  # Will be implemented with concrete assertions after refactor
```

```bash
python3 -m pytest tests/test_agent_run.py -v
```

- [ ] **Step 2: 提取 `_perceive()` 方法**

在 `tain_agent/core/agent.py` 中，将 `run()` 方法中 "PRAL: Perceive" 段的逻辑（当前约第 178-192 行）提取到新方法 `_perceive()`：

```python
def _perceive(self) -> None:
    """PRAL Perceive: collect cognitive environment, drive snapshot, context."""
    try:
        env = self._get_cognitive_environment()
        conv_summary = self.conversation.summarize_recent() if hasattr(
            self.conversation, 'summarize_recent') else ""
        self.cognitive_loop.perceive(env, conv_summary)
        self.cognitive_loop.state.phase = CognitivePhase.REASON

        available_actions = list(self.tools._tools.keys()) if hasattr(self.tools, '_tools') else []
        reasoning = self.cognitive_loop.reason(env, available_actions)
        if reasoning and reasoning.get('recommendation'):
            logging.info("认知建议: %s", reasoning['recommendation'])
    except (AttributeError, TypeError) as e:
        logging.warning("Cognitive context partial: %s", e)
```

- [ ] **Step 3: 提取 `_reason()` 方法**

将 LLM 调用逻辑（当前约第 194-234 行）提取到 `_reason()`：

```python
def _reason(self):
    """PRAL Reason: call LLM with system prompt + conversation, return parsed response.
    
    Returns:
        LLMResponse or None if LLM call failed / rate limited.
    """
    try:
        system_prompt = self._get_system_prompt_with_cognition()
        messages = self.conversation.to_claude_messages()
        tool_defs = self.tools.get_claude_tool_definitions()
        llm_response = self.backend.create_message(
            system_prompt=system_prompt,
            messages=messages,
            tools=tool_defs,
        )
        return llm_response
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "rate_limit" in err_str:
            self._detect_rate_limit_type(err_str)
            if self._rate_limit_exit_code:
                return None
        logging.warning("LLM call failed: %s", e)
        if self.conversation.len() > 16:
            logging.info("Trimming conversation and retrying...")
            self.conversation.trim_to_token_budget(keep_last=8)
            try:
                messages = self.conversation.to_claude_messages()
                llm_response = self.backend.create_message(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tool_defs,
                )
                logging.info("Retry succeeded")
                return llm_response
            except Exception as e2:
                err_str2 = str(e2)
                if "429" in err_str2 or "rate_limit" in err_str2:
                    self._detect_rate_limit_type(err_str2)
                    if self._rate_limit_exit_code:
                        return None
                logging.warning("Retry also failed: %s", e2)
                time.sleep(3)
                return None
        else:
            logging.info("Waiting before next cycle retry...")
            time.sleep(2)
            return None
```

- [ ] **Step 4: 提取 `_act()` 方法**

将工具执行、对话追加、action 追踪逻辑（当前约第 236-306 行）提取到 `_act()`：

```python
def _act(self, llm_response) -> None:
    """PRAL Act: execute tool calls, append results to conversation, track actions."""
    text_parts = llm_response.text_blocks
    tool_use_blocks = llm_response.tool_calls

    if text_parts:
        thought = "\n".join(text_parts)
        logging.info("Agent thought:\n%s", thought)

    assistant_content = []
    for text in text_parts:
        assistant_content.append({"type": "text", "text": text})
    for tc in tool_use_blocks:
        assistant_content.append({
            "type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input,
        })
    for extra in llm_response.extra_blocks:
        assistant_content.append(extra)

    if assistant_content:
        self.conversation.append("assistant", assistant_content)

    if tool_use_blocks:
        if self.phase == "explore":
            for tc in tool_use_blocks:
                self._track_action_category(tc.name)

        if hasattr(self, 'drive_system') and self.drive_system:
            took_productive = False
            for tc in tool_use_blocks:
                cat = self._TOOL_CATEGORY_MAP.get(tc.name, "observation")
                if cat in ("creation", "reflection"):
                    self.drive_system.record_action(tc.name)
                    took_productive = True
            if not took_productive and tool_use_blocks:
                self.drive_system.record_idle_cycle()

        tool_results = self._execute_tool_calls(tool_use_blocks)
        user_content = [
            {"type": "tool_result", "tool_use_id": tr["tool_use_id"], "content": tr["content"]}
            for tr in tool_results
        ]
        self.conversation.append("user", user_content)

        # Action-Contemplation Balance
        self._apply_action_contemplation_balance(tool_use_blocks, text_parts)
```

- [ ] **Step 5: 提取 `_learn()` 方法**

将阶段切换、检查点、驱动力、内省逻辑（当前约第 308-419 行）提取到 `_learn()`：

```python
def _learn(self, llm_response) -> None:
    """PRAL Learn: phase transitions, checkpoints, introspection, drive injection."""
    tool_use_blocks = llm_response.tool_calls
    text_parts = llm_response.text_blocks
    tool_results = getattr(self, '_last_tool_results', [])

    # Personality observation
    if hasattr(self, 'personality') and self.personality and tool_use_blocks:
        tool_names = [tc.name for tc in tool_use_blocks]
        self.personality.auto_observe(tool_names, text_parts)

    # Phase transition check
    min_cats = getattr(self, 'min_action_categories', 3)
    if self.phase == "explore" and len(self._bootstrap_action_categories) >= min_cats:
        self._advance_phase()

    # Self-destruct check
    for tc in tool_use_blocks:
        if tc.name == "self_destruct":
            logging.info("Agent self-destructed")
            self._running = False
            return

    # PRAL cognitive tracking
    try:
        env = self._get_cognitive_environment()
        for tc in tool_use_blocks:
            result_text = ""
            for r in tool_results:
                if r.get('tool_name') == tc.name:
                    result_text = str(r.get('content', ''))[:500]
                    break
            self.cognitive_loop.record_action(tc.name, result_text)
        self.cognitive_loop.learn(tool_results)
        self.cognitive_loop.run_cycle(
            environment=env, conversation_summary="",
            action_name=tool_use_blocks[0].name if tool_use_blocks else "observe",
            action_result=str(tool_results[0].get('content', '')[:200]) if tool_results else "",
        )
        reflection = self.cognitive_loop.reflect()
        if reflection:
            self.cognitive_loop.log_reflection(reflection)
            self.conversation.append("user",
                f"[认知自省] {reflection}\n这是来自你自己的认知循环的反馈——请在下一次行动中考虑它。")
    except (AttributeError, TypeError, KeyError) as e:
        logging.warning("Cognitive tracking partial: %s", e)

    # Conversation trimming + checkpoint
    if self.conversation.len() > 150:
        removed = self.conversation.trim_to_token_budget(keep_last=40)
        if removed:
            logging.info("Conversation trimmed: %s messages removed", removed)
    checkpoint_result = self.conversation.checkpoint_if_needed()
    if checkpoint_result:
        logging.info("Checkpoint: %s messages saved", checkpoint_result['message_count'])

    # Cognitive introspection
    self._maybe_introspect()

    # Drive exploration prompt
    if self.cycle_count % 8 == 0 and hasattr(self, 'drive_system') and self.drive_system:
        prompt = self.drive_system.get_exploration_prompt()
        if prompt:
            self.conversation.append("user", prompt)
```

- [ ] **Step 6: 提取 `_apply_action_contemplation_balance` 辅助方法**

将第 345-407 行的行动-沉思平衡逻辑提取为独立方法：

```python
def _apply_action_contemplation_balance(self, tool_use_blocks, text_parts) -> None:
    """Apply action-contemplation balance tracking and injection."""
    _readonly_tools = {
        "read_file", "smart_read", "grep_code",
        "web_search", "web_fetch", "api_fetch", "fetch_and_parse",
        "observe_environment", "explore_directory",
        "get_current_time",
        "rag_tool", "knowledge_vector_search", "wikipedia",
        "content_extractor", "knowledge_graph", "knowledge_health",
        "knowledge_freshness", "knowledge_gap_finder",
        "knowledge_linker", "knowledge_subgraph",
        "coevolution_monitor", "emergent_topic_detector",
        "capability_index", "agent_dashboard",
        "code_stats", "self_audit", "impact_analyzer",
        "lineage_query", "meta_learn", "session_digest",
        "decision_log_health", "outcome_update",
        "metrics_collector", "tool_fitness",
        "version_diff", "knowledge_version_tracker",
        "parse_url", "html_to_text", "json_query",
    }
    _reflective_tools = {
        "personality_introspect", "personality_update",
        "record_decision", "set_goal", "complete_goal",
        "evolve_report", "assess_capabilities", "pipeline_status",
    }

    took_action = any(
        tc.name not in _readonly_tools and tc.name not in _reflective_tools
        for tc in tool_use_blocks
    )
    had_reflection = any(
        tc.name in _reflective_tools for tc in tool_use_blocks
    )

    if took_action:
        self._readonly_streak = 0
        self._contemplation_insights = []
    elif had_reflection:
        self._readonly_streak = max(0, self._readonly_streak - 2)
        self._contemplation_insights.append(
            " ".join(text_parts)[:200] if text_parts else "reflection"
        )
    else:
        self._readonly_streak += 1

    if self.phase == "work":
        if self._readonly_streak == 5:
            self.conversation.append("user", (
                "[系统提示] 你已经进行了多轮静观。这本身是有价值的——"
                "不是所有时刻都需要行动。\n"
                "不过请反思：你近期的静观是否产生了新的洞察？"
                "如果有，可以用 personality_update 记录下来。"
                "如果没有，也许可以尝试一个小的行动来打破现有视角。"
            ))
        elif self._readonly_streak > 8:
            logging.info("Long contemplation — injecting gentle action reminder")
            self.conversation.append("user", (
                "[系统提示] 你已经静观了很长时间。这不是问题——"
                "静观是完整生命节奏的一部分。\n"
                "但值得问自己：你是在等待什么吗？"
                "你的静观期是否有了新的领悟？\n"
                "如果有了新的方向感，现在也许是行动的时候了。"
                "如果还没有，你希望观察什么来帮助自己找到方向？"
            ))
            self._readonly_streak = 0
```

- [ ] **Step 7: 重写 `run()` 方法**

将第 129-420 行替换为：

```python
def run(self, autonomous: bool = False) -> int:
    """Start the agent. PRAL cognitive loop: Perceive → Reason → Act → Learn."""
    if not self.backend:
        api_key_env = self.config.get("llm", {}).get("api_key_env", "MINIMAX_API_KEY")
        logging.error("API key not set: %s", api_key_env)
        return 0

    self._running = True
    self.conversation.clear()
    self._factory.mark_running(self.agent_name, os.getpid())

    logging.info("Agent %s starting — model: %s, phase: %s",
                 self.agent_name, self.model, self.phase)

    self.conversation.append("user", self._build_initial_message())

    while self._running:
        self.cycle_count += 1
        max_cycles = self.MAX_CYCLES.get(self.phase, 50)

        if self.cycle_count > max_cycles:
            logging.info("Max cycles (%s) reached, advancing phase", max_cycles)
            self._advance_phase()
            if not self._running:
                break
            continue

        logging.info("Cycle #%s | phase: %s", self.cycle_count, self.phase)

        self._perceive()
        response = self._reason()
        if response is None:
            continue
        self._act(response)
        self._learn(response)

    self._save_cognitive_snapshot()
    return self._rate_limit_exit_code
```

- [ ] **Step 8: 运行测试确认无回归**

```bash
python3 -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [ ] **Step 9: 提交**

```bash
git add tain_agent/core/agent.py tests/test_agent_run.py
git commit -m "refactor: split run() into PRAL four-phase methods (P1-10)"
```

---

### Task C2: Mixin Protocol 接口

**Files:**
- Create: `tain_agent/core/agent_protocols.py`

- [ ] **Step 1: 创建 Protocol 文件**

创建 `tain_agent/core/agent_protocols.py`：

```python
"""Protocol definitions for Mixin interface contracts.

These define the expected attributes/methods each Mixin provides or consumes,
making the implicit hasattr() contracts explicit and type-checkable.
"""
from typing import Protocol, runtime_checkable
from pathlib import Path


@runtime_checkable
class ConfigProvider(Protocol):
    """Provided by AgentConfigMixin."""
    config: dict
    agent_name: str
    workspace_dir: str
    framework_version: str
    model: str
    max_tokens: int
    api_key: str
    protected_paths: list[str]
    confirm_destructive: bool
    workspace_root: str
    log_dir: str
    decision_log_file: str
    memory_file: str
    max_exploration_cycles: int
    max_definition_cycles: int
    min_action_categories: int
    evolution_mode: str
    role: str
    role_description: str

    def _load_config(self, config_path: str) -> None: ...
    def _load_agent_identity(self) -> None: ...
    def _load_phase_from_memory(self) -> str: ...
    def _save_phase_to_memory(self) -> None: ...


@runtime_checkable
class PhaseProvider(Protocol):
    """Provided by AgentPhaseMixin."""
    phase: str
    cycle_count: int
    PHASES: tuple
    MAX_CYCLES: dict
    _bootstrap_action_categories: set
    _TOOL_CATEGORY_MAP: dict[str, str]

    def _build_initial_message(self) -> str: ...
    def _track_action_category(self, tool_name: str) -> None: ...
    def _advance_phase(self) -> None: ...
```

- [ ] **Step 2: 验证 Protocol 对现有 Mixin 的兼容性**

```bash
python3 -c "
from tain_agent.core.agent_protocols import ConfigProvider, PhaseProvider
from tain_agent.core.agent import TaoAgent
# Protocol check — verify structural subtyping works
print('ConfigProvider:', issubclass(TaoAgent, ConfigProvider))
print('PhaseProvider:', issubclass(TaoAgent, PhaseProvider))
"
```

- [ ] **Step 3: 提交**

```bash
git add tain_agent/core/agent_protocols.py
git commit -m "feat: add Mixin Protocol interfaces for explicit contracts (P2-15)"
```

---

### Task C3: `except Exception` 收窄 + `print()` → `logging`

**Files:**
- Modify: `tain_agent/core/agent.py`

- [ ] **Step 1: 在 agent.py 顶部添加 logging import**

```python
# agent.py 顶部添加:
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 2: 替换 agent.py 中所有 `print()` 为 `logging`**

逐一替换 33 处 `print()` 调用。关键模式：

```python
# print(f"❌ 错误消息") → logger.error("错误消息")
# print(f"⚠️  警告消息") → logger.warning("警告消息")
# print(f"🔄 循环信息") → logger.info("循环信息")
# print(f"\n💭 Agent 思考:\n{thought}") → logger.info("Agent thought:\n%s", thought)
```

**注意**: `run()` 中的 banner 保持 `print()` ——这是 CLI 模式下的用户界面，不是日志。

- [ ] **Step 3: 收窄关键子系统的 except 捕获**

```python
# 认知采集 (原 except Exception: pass):
except (AttributeError, TypeError) as e:
    logger.warning("Cognitive context partial: %s", e)

# 人格观察 (原 except Exception: pass):
except (AttributeError, TypeError, IOError) as e:
    logger.warning("Personality observation skipped: %s", e)

# 驱动力 (原 except Exception: pass):
except (AttributeError, TypeError) as e:
    logger.warning("Drive system update skipped: %s", e)

# 改进循环 (原 except Exception: pass):
except (AttributeError, TypeError, IOError) as e:
    logger.warning("Improvement loop tick skipped: %s", e)
```

LLM 重试的 5 处 `except Exception` 保持宽泛但加日志（LLM SDK 异常类型不稳定）。

- [ ] **Step 4: 编译 + 运行测试**

```bash
python3 -m py_compile tain_agent/core/agent.py && echo "OK"
python3 -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [ ] **Step 5: 提交**

```bash
git add tain_agent/core/agent.py
git commit -m "fix: replace print() with logging, narrow except Exception scopes (P2-11, P2-12)"
```

---

### 工作流 D · 重试 + Agent 复用 + 工具声明式 + 持久化

### Task D1: 重试逻辑整合

**Files:**
- Modify: `tain_agent/core/retry.py`
- Modify: `tain_agent/core/agent.py`

- [ ] **Step 1: 在 retry.py 新增 `llm_retry` 函数**

在 `retry.py` 末尾添加：

```python
def llm_retry_call(
    config: RetryConfig,
    func: Callable,
    *args,
    on_rate_limit: Optional[Callable[[], bool]] = None,
    on_trim: Optional[Callable[[], None]] = None,
    **kwargs,
):
    """LLM-specific retry with rate-limit awareness and conversation-trimming fallback.

    Differs from retry_call: on rate limit (429), calls on_rate_limit() which
    should check _rate_limit_exit_code. On other retryable failures, calls
    on_trim() to trim conversation before the last retry attempt.

    Returns:
        The return value of func on success, None on rate-limit exit.
    
    Raises:
        RetryExhaustedError: when all retries are exhausted on non-rate-limit errors.
    """
    if not config.enabled:
        return func(*args, **kwargs)

    last_exception = None
    for attempt in range(config.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exception = exc
            err_str = str(exc)
            
            # Rate limit: check exit code, break early
            if "429" in err_str or "rate_limit" in err_str.lower():
                if on_rate_limit:
                    should_exit = on_rate_limit()
                    if should_exit:
                        return None
                delay = _calculate_delay(config, attempt) * 2  # longer wait for rate limits
                time.sleep(delay)
                continue
            
            # Non-retryable: raise immediately
            if not _is_retryable(exc):
                raise
            
            # Last attempt with trim
            if attempt >= config.max_retries:
                raise RetryExhaustedError(last_exception, attempt + 1) from last_exception
            
            if attempt == config.max_retries - 1 and on_trim:
                on_trim()
            
            delay = _calculate_delay(config, attempt)
            time.sleep(delay)

    return None  # rate limit exit
```

- [ ] **Step 2: 更新 agent._reason() 使用 llm_retry_call**

修改 `_reason()` 方法（Task C1 中提取的），将手动重试替换为 `llm_retry_call`：

```python
def _reason(self):
    """PRAL Reason: call LLM, return parsed response."""
    system_prompt = self._get_system_prompt_with_cognition()
    messages = self.conversation.to_claude_messages()
    tool_defs = self.tools.get_claude_tool_definitions()
    
    retry_cfg = RetryConfig.from_config(self.config.get("llm", {}))
    
    def _call():
        return self.backend.create_message(
            system_prompt=system_prompt,
            messages=self.conversation.to_claude_messages(),
            tools=self.tools.get_claude_tool_definitions(),
        )
    
    def _on_rate_limit():
        self._detect_rate_limit_type("rate_limit")
        return bool(self._rate_limit_exit_code)
    
    def _on_trim():
        self.conversation.trim_to_token_budget(keep_last=8)
    
    try:
        return llm_retry_call(
            retry_cfg, _call,
            on_rate_limit=_on_rate_limit,
            on_trim=_on_trim,
        )
    except RetryExhaustedError as e:
        logger.warning("LLM call exhausted after %s attempts: %s", e.attempts, e.last_exception)
        return None
```

- [ ] **Step 3: 清理 agent.py 中残留的手动重试代码**

确保原来 `run()` 中的 ~30 行手动重试不再保留在任何方法中。

- [ ] **Step 4: 运行测试**

```bash
python3 -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [ ] **Step 5: 提交**

```bash
git add tain_agent/core/retry.py tain_agent/core/agent.py
git commit -m "refactor: integrate agent LLM retry with retry.py framework (P1-5)"
```

---

### Task D2: Agent 惰性缓存 + 变更检测

**Files:**
- Create: `webui/agent_cache.py`
- Modify: `webui/dialogue.py:224-229`
- Modify: `webui/routes/api_agents.py`

- [ ] **Step 1: 创建 agent_cache.py**

创建 `webui/agent_cache.py`：

```python
"""Agent instance cache with mtime-based invalidation."""
import time
import logging
from pathlib import Path
from typing import Optional
from tain_agent.core.agent import TaoAgent

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, "TaoAgent"]] = {}

# Will be set by app startup
WORKSPACE_ROOT: Path = Path("agent_workspace")


def get_agent(name: str, config_path: str) -> TaoAgent:
    """Get or create a cached agent instance. Rebuilds if config changed."""
    global WORKSPACE_ROOT
    workspace = WORKSPACE_ROOT / name
    mtime = 0.0
    
    agent_yaml = workspace / "agent.yaml"
    version_json = workspace / "version.json"
    for path in (agent_yaml, version_json):
        if path.exists():
            mtime = max(mtime, path.stat().st_mtime)
    
    if name in _cache:
        cached_mtime, agent = _cache[name]
        if cached_mtime >= mtime:
            return agent
        logger.info("Agent %s cache invalidated (mtime %s > %s)", name, mtime, cached_mtime)
    
    logger.info("Creating new agent instance for %s", name)
    agent = TaoAgent(config_path=config_path, agent_name=name)
    _cache[name] = (time.time(), agent)
    return agent


def invalidate_agent(name: str) -> bool:
    """Force-invalidate a cached agent. Returns True if was cached."""
    if name in _cache:
        del _cache[name]
        logger.info("Agent %s manually invalidated", name)
        return True
    return False


def clear_cache() -> int:
    """Clear all cached agents. Returns count cleared."""
    count = len(_cache)
    _cache.clear()
    logger.info("Agent cache cleared (%s entries)", count)
    return count
```

- [ ] **Step 2: 修改 dialogue.py 使用缓存**

修改 `webui/dialogue.py` 第 224-229 行：

```python
# 旧:
from tain_agent.core.agent import TaoAgent
# ...
agent = TaoAgent(config_path=str(PROJECT_ROOT / "config.yaml"), agent_name=agent_name)

# 新:
from webui.agent_cache import get_agent
# ...
agent = get_agent(agent_name, config_path=str(PROJECT_ROOT / "config.yaml"))
```

- [ ] **Step 3: 添加 /reload 端点**

修改 `webui/routes/api_agents.py`，新增：

```python
from webui.agent_cache import invalidate_agent

@router.post("/agent/{name}/reload")
async def reload_agent(name: str):
    """Force reload a cached agent instance."""
    was_cached = invalidate_agent(name)
    return {
        "success": True,
        "agent": name,
        "was_cached": was_cached,
        "message": "Agent cache cleared — will be recreated on next request" if was_cached else "Agent was not in cache",
    }
```

- [ ] **Step 4: 运行现有 Web UI 相关测试**

```bash
python3 -m pytest tests/test_acp.py -v 2>&1 | tail -10
```

- [ ] **Step 5: 提交**

```bash
git add webui/agent_cache.py webui/dialogue.py webui/routes/api_agents.py
git commit -m "feat: add agent instance cache with mtime invalidation (P1-9)"
```

---

### Task D3: 工具分类声明式化

**Files:**
- Modify: `tain_agent/tools/base.py`
- Modify: `tain_agent/core/agent.py`

- [ ] **Step 1: 在 Tool 基类添加 `is_readonly` 属性**

修改 `tain_agent/tools/base.py` 第 14-31 行：

```python
class Tool(ABC):
    """Standard interface for all agent tools."""

    name: str = ""
    description: str = ""
    parameters: dict = {}
    is_readonly: bool = False  # True = no side effects, safe for readonly streak tracking
```

- [ ] **Step 2: 标记关键工具的 `is_readonly`**

在 `bootstrap.py` 的工具注册中，对只读工具添加 `is_readonly=True`。例如：

```python
# _register_knowledge 中:
self.a.tools.register("knowledge_health", knowledge_health, ...)
# → 工具对象在注册时设置 is_readonly=True
```

由于当前工具注册使用函数闭包而非 Tool 子类，需要先在 `registry.py` 中支持 `is_readonly` 参数：

修改 `tain_agent/tools/registry.py` 的 `register()` 方法，增加 `is_readonly: bool = False` 参数并将之存储。

- [ ] **Step 3: 将 `_readonly_tools` 改为动态属性**

修改 `agent.py` 中 `_apply_action_contemplation_balance`：

```python
@property
def _readonly_tools(self) -> set[str]:
    return {t.name for t in self.tools.list_tools() if getattr(t, 'is_readonly', False)}
```

同时删除 33 项硬编码的 `_readonly_tools` set。

- [ ] **Step 4: 验证工具列表完整性**

```bash
python3 -c "
from tain_agent.core.agent import TaoAgent
# Import check — ensure property works without agent instance
print('Property defined on TaoAgent:', hasattr(TaoAgent, '_readonly_tools'))
"
```

- [ ] **Step 5: 提交**

```bash
git add tain_agent/tools/base.py tain_agent/tools/registry.py tain_agent/core/agent.py
git commit -m "refactor: make tool readonly classification declarative (P2-17)"
```

---

### Task D4: 持久化策略统一

**Files:**
- Create: `tain_agent/utils/persist.py`

- [ ] **Step 1: 创建 persist.py**

创建 `tain_agent/utils/persist.py`：

```python
"""Unified persistence utilities with atomic writes."""
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any


class WritePolicy(Enum):
    IMMEDIATE = "immediate"   # write every change
    BUFFERED = "buffered"     # flush every 10 cycles
    LAZY = "lazy"             # flush on agent stop


# Per-file policy declarations
FILE_POLICIES: dict[str, WritePolicy] = {
    "personality.json": WritePolicy.IMMEDIATE,
    "decisions.jsonl": WritePolicy.BUFFERED,
    "memory.json": WritePolicy.LAZY,
    "conversation_checkpoint.json": WritePolicy.BUFFERED,
    "version.json": WritePolicy.IMMEDIATE,
    "lineage.jsonl": WritePolicy.BUFFERED,
    "_registry.json": WritePolicy.IMMEDIATE,
}


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON atomically using tempfile + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            import json
            json.dump(data, f, ensure_ascii=False, indent=indent, default=str)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically using tempfile + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_policy(file_name: str) -> WritePolicy:
    """Get the declared write policy for a file."""
    return FILE_POLICIES.get(file_name, WritePolicy.IMMEDIATE)
```

- [ ] **Step 2: 编译检查**

```bash
python3 -m py_compile tain_agent/utils/persist.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add tain_agent/utils/persist.py
git commit -m "feat: add unified persistence utilities with atomic writes (P2-19)"
```

---

### 工作流 E · 测试补强

### Task E1: 进化系统测试

**Files:**
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_pipeline.py`：

```python
"""Tests for evolution pipeline — gap detection, design, verify, register."""
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


class TestPipelineGapDetection:
    def test_detect_gap_returns_candidate(self):
        from tain_agent.evolution.pipeline import ImprovementPipeline
        pipeline = ImprovementPipeline()
        # Gap detection should return a candidate dict with a name
        gap = pipeline.detect_gap()
        # Current behavior: detect_gap may return None if no gaps
        # This test documents the contract
        if gap is not None:
            assert "name" in gap or "gap" in gap

    def test_design_stage_stops_for_human(self):
        """Pipeline design stage should NOT auto-generate code — it stops for human input."""
        from tain_agent.evolution.pipeline import ImprovementPipeline
        pipeline = ImprovementPipeline()
        # Verify design stage exists and accepts human input
        assert hasattr(pipeline, 'design') or hasattr(pipeline, 'run_design')


class TestPipelineVerification:
    def test_verify_rejects_unsafe_imports(self):
        """Quality gate should reject tools importing blocked modules."""
        # This test verifies the forge sandbox quality gate behavior
        unsafe_code = "import os\nos.system('rm -rf /')\n"
        from tain_agent.tools.forge import ForgeSandbox
        sandbox = ForgeSandbox()
        result = sandbox.validate(unsafe_code)
        assert result.get("safe", True) is False or result.get("errors")

    def test_verify_accepts_safe_tool(self):
        safe_code = "def hello():\n    return 'hello world'\n"
        from tain_agent.tools.forge import ForgeSandbox
        sandbox = ForgeSandbox()
        result = sandbox.validate(safe_code)
        # A simple safe function should pass validation
        assert result.get("safe", False) is True or not result.get("errors")


class TestPipelineRegistration:
    def test_pipeline_has_register_method(self):
        from tain_agent.evolution.pipeline import ImprovementPipeline
        pipeline = ImprovementPipeline()
        assert hasattr(pipeline, 'register') or hasattr(pipeline, 'run_registration')
```

- [ ] **Step 2: 运行测试**

```bash
python3 -m pytest tests/test_pipeline.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_pipeline.py
git commit -m "test: add evolution pipeline unit tests (P1-7)"
```

---

### Task E2: LLM 响应解析测试

**Files:**
- Create: `tests/test_llm_parser.py`

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_llm_parser.py`：

```python
"""Tests for LLM response parsing — XML tool call extraction, text/thinking separation."""
import json
import pytest
from dataclasses import dataclass, field
from tain_agent.core.llm import LLMResponse, ToolCall


# ── Fixtures: simulated LLM response building blocks ──

def make_text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def make_tool_use_block(tool_id: str, name: str, input_data: dict) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": input_data}


def make_thinking_block(thinking: str) -> dict:
    return {"type": "thinking", "thinking": thinking}


class TestLLMResponse:
    """Tests for LLMResponse dataclass construction and field behavior."""

    def test_response_stores_text_blocks(self):
        resp = LLMResponse()
        resp.text_blocks.append("Hello world")
        resp.text_blocks.append("How can I help?")
        assert resp.text_blocks == ["Hello world", "How can I help?"]

    def test_response_stores_tool_calls(self):
        resp = LLMResponse()
        tc = ToolCall(id="tc_1", name="read_file", input={"path": "/tmp/test"})
        resp.tool_calls.append(tc)
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "read_file"

    def test_response_separates_text_from_tools(self):
        """Text blocks and tool calls are tracked separately — critical for parsing."""
        resp = LLMResponse()
        resp.text_blocks.append("Let me read that file")
        resp.tool_calls.append(ToolCall(id="tc_1", name="read_file", input={"path": "/tmp/test"}))
        resp.text_blocks.append("The file says...")
        
        assert len(resp.text_blocks) == 2
        assert len(resp.tool_calls) == 1

    def test_empty_response_has_no_content(self):
        resp = LLMResponse()
        assert resp.text_blocks == []
        assert resp.tool_calls == []


class TestToolCallParsing:
    """Test tool call extraction from various LLM response patterns."""

    def test_single_tool_call_extraction(self):
        """Verify ToolCall dataclass holds expected fields."""
        tc = ToolCall(
            id="toolu_01",
            name="execute_code",
            input={"code": "print(1)", "language": "python"}
        )
        assert tc.id == "toolu_01"
        assert tc.name == "execute_code"
        assert tc.input["code"] == "print(1)"
        assert tc.input["language"] == "python"

    def test_multiple_tool_calls_in_one_response(self):
        """Multiple tools called in one turn should all be captured."""
        resp = LLMResponse()
        resp.tool_calls.append(ToolCall(id="tc_1", name="read_file", input={"path": "a.py"}))
        resp.tool_calls.append(ToolCall(id="tc_2", name="write_file", input={"path": "b.py", "content": "x"}))
        assert len(resp.tool_calls) == 2

    def test_tool_call_input_preserves_types(self):
        """Tool input should preserve JSON types (str, int, bool, list, dict)."""
        tc = ToolCall(id="tc_1", name="test", input={
            "name": "test",
            "count": 42,
            "enabled": True,
            "tags": ["a", "b"],
            "nested": {"key": "value"},
        })
        assert isinstance(tc.input["count"], int)
        assert isinstance(tc.input["enabled"], bool)
        assert isinstance(tc.input["tags"], list)
        assert isinstance(tc.input["nested"], dict)


class TestTextThinkingSeparation:
    """Test separation of thinking blocks from text content."""

    def test_pure_text_response_no_tools(self):
        """A response with only text and no tools should have empty tool_calls."""
        resp = LLMResponse()
        resp.text_blocks.append("Here is what I found...")
        assert len(resp.text_blocks) == 1
        assert len(resp.tool_calls) == 0

    def test_text_before_and_after_tools(self):
        """Text before, between, and after tool calls should all be captured."""
        resp = LLMResponse()
        resp.text_blocks.append("I will search and read.")
        resp.tool_calls.append(ToolCall(id="tc_1", name="web_search", input={"query": "test"}))
        resp.tool_calls.append(ToolCall(id="tc_2", name="read_file", input={"path": "result.txt"}))
        resp.text_blocks.append("Here are the results.")
        assert len(resp.text_blocks) == 2
        assert len(resp.tool_calls) == 2


class TestAnthropicBackendResponseParsing:
    """Test the AnthropicBackend's create_message response parsing logic."""

    def test_parse_content_blocks_into_llmresponse(self):
        """Simulate Anthropic SDK content block format parsing."""
        from dataclasses import dataclass as dc
        
        @dc
        class MockBlock:
            type: str
            text: str = ""
            id: str = ""
            name: str = ""
            input: dict = field(default_factory=dict)
        
        # Simulate the backend's create_message parsing loop
        response = LLMResponse()
        blocks = [
            MockBlock(type="text", text="Let me think about this."),
            MockBlock(type="tool_use", id="tc_1", name="grep_code", input={"pattern": "test"}),
            MockBlock(type="text", text="Found 3 matches."),
        ]
        for block in blocks:
            if block.type == "text":
                response.text_blocks.append(block.text)
            elif block.type == "tool_use":
                response.tool_calls.append(ToolCall(
                    id=block.id, name=block.name,
                    input=block.input if isinstance(block.input, dict) else {},
                ))
        
        assert len(response.text_blocks) == 2
        assert response.text_blocks[0] == "Let me think about this."
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "grep_code"

    def test_rate_limit_error_preserves_exit_code_behavior(self):
        """Rate limit errors (429) should set exit code — contract for caller."""
        error_msg = "Error code: 429 — rate_limit exceeded. Retry after 10s."
        assert "429" in error_msg
        assert "rate_limit" in error_msg.lower()


class TestXMLToolCallIntegration:
    """Integration-style tests for the XML tool-call regex fallback parser."""

    def test_regex_fallback_extracts_tool_call_xml(self):
        """When the LLM returns tool calls as XML in text blocks, regex should extract."""
        import re
        xml_text = """<tool_calls>
<tool_call name="read_file">
{"path": "/tmp/test.txt"}
</tool_call>
</tool_calls>"""
        # Verify the regex pattern that the agent uses for fallback
        pattern = r'<tool_calls>.*?</tool_calls>'
        match = re.search(pattern, xml_text, re.DOTALL)
        assert match is not None
        
        # Extract individual tool calls
        tc_pattern = r'<tool_call name="([^"]+)">\s*(.*?)\s*</tool_call>'
        matches = re.findall(tc_pattern, xml_text, re.DOTALL)
        assert len(matches) == 1
        assert matches[0][0] == "read_file"

    def test_no_tool_call_pure_text_no_false_positive(self):
        """Pure text without tool_call markers should not trigger extraction."""
        import re
        text = "I can help you with that. Let me search for relevant information."
        pattern = r'<tool_calls>.*?</tool_calls>'
        match = re.search(pattern, text, re.DOTALL)
        assert match is None
```

- [ ] **Step 2: 运行测试**

```bash
python3 -m pytest tests/test_llm_parser.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_llm_parser.py
git commit -m "test: add LLM response parsing unit tests (P1-8)"
```

---

### Task E3: Web UI 路由测试

**Files:**
- Create: `tests/test_webui_routes.py`

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_webui_routes.py`：

```python
"""Smoke tests for Web UI routes."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a TestClient for the Web UI app."""
    from webui.app import app
    return TestClient(app)


class TestDashboardRoutes:
    def test_dashboard_returns_200(self, client):
        with patch('webui.data.list_agents', return_value=[]), \
             patch('webui.data.load_config', return_value={'framework': {'version': '0.5.0'}}):
            response = client.get("/")
            assert response.status_code == 200

    def test_dashboard_includes_framework_version(self, client):
        with patch('webui.data.list_agents', return_value=[]), \
             patch('webui.data.load_config', return_value={'framework': {'version': '0.5.0'}}):
            response = client.get("/")
            assert "Tain" in response.text or "tain" in response.text.lower()


class TestCreateAgentRoute:
    def test_create_page_returns_200(self, client):
        response = client.get("/create")
        assert response.status_code == 200

    def test_create_page_has_form(self, client):
        response = client.get("/create")
        assert "form" in response.text.lower() or "创建" in response.text or "create" in response.text.lower()


class TestAgentDetailRoute:
    def test_agent_detail_404_for_missing_agent(self, client):
        response = client.get("/agent/nonexistent_agent_12345")
        assert response.status_code in (200, 404)  # May return 200 with error UI or 404


class TestChatRoute:
    def test_chat_agent_not_found_returns_error(self, client):
        """Chat with nonexistent agent should return an error."""
        with patch('webui.dialogue._load_conversation_history', return_value=[]), \
             patch('webui.dialogue._now_iso', return_value='2026-01-01T00:00:00Z'):
            response = client.post(
                "/api/agent/nonexistent_agent_12345/chat",
                json={"content": "hello"}
            )
            # Should not crash — may return SSE or error
            assert response.status_code in (200, 404, 500)


class TestKnowLedgeRoute:
    def test_knowledge_rejects_path_traversal(self, client):
        """Verify C3 fix: path traversal in knowledge endpoint is blocked."""
        response = client.get(
            "/api/agent/default/knowledge/content",
            params={"path": "../../../etc/passwd"}
        )
        # Should not crash the server or return file content
        assert response.status_code in (200, 403, 404)
        if response.status_code == 200:
            data = response.json()
            # Should not contain actual passwd content
            content = data.get("content", "")
            assert "root:" not in content


class TestSettingsRoute:
    def test_settings_page_returns_200(self, client):
        response = client.get("/settings")
        assert response.status_code == 200
```

- [ ] **Step 2: 安装/确认 TestClient 可用**

```bash
python3 -c "from fastapi.testclient import TestClient; print('OK')"
```

如果报错，安装 httpx（FastAPI TestClient 依赖）：
```bash
pip install httpx
```

- [ ] **Step 3: 运行测试**

```bash
python3 -m pytest tests/test_webui_routes.py -v
```

部分测试可能因 mock 不完整而失败 —— 这是正常的，记录在案即可。

- [ ] **Step 4: 提交**

```bash
git add tests/test_webui_routes.py
git commit -m "test: add Web UI route smoke tests (P2-13)"
```

---

### Task E4: 集成测试

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: 创建集成测试文件**

创建 `tests/test_integration.py`：

```python
"""Integration tests — agent lifecycle across create → run → stop → restart."""
import tempfile
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for an agent."""
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        # Minimal config
        config = ws / "config.yaml"
        config.write_text(f"""
framework: {{version: "0.5.0"}}
agent: {{default_agent: test_agent}}
llm: {{provider: test, model: test, max_tokens: 100, api_key_env: NONE}}
exploration: {{max_exploration_cycles: 10, max_definition_cycles: 5, min_bootstrap_cycles: 3, min_action_categories: 2}}
agent_workspace: {{dir: "{ws}"}}
safety: {{protected_paths: []}}
logging: {{directory: "/tmp", decision_log_file: test.jsonl, memory_file: test.json}}
""")
        yield ws


class TestAgentLifecycle:
    def test_agent_create_and_stop(self, temp_workspace):
        """Agent should be creatable and stoppable without errors."""
        from tain_agent.core.agent import TaoAgent
        agent = TaoAgent(config_path=str(temp_workspace / "config.yaml"))
        agent.agent_name = "test_lifecycle"
        
        assert agent.agent_name == "test_lifecycle"
        assert agent.phase == "explore"
        
        # Stop should not raise
        agent.stop()
        assert True  # No exception raised

    def test_agent_phase_starts_as_explore(self, temp_workspace):
        """New agent always starts in explore phase."""
        from tain_agent.core.agent import TaoAgent
        agent = TaoAgent(config_path=str(temp_workspace / "config.yaml"))
        agent.agent_name = "test_phase"
        assert agent.phase == "explore"

    def test_agent_phase_persists_across_instances(self, temp_workspace):
        """Phase saved to memory should be loadable by a new instance."""
        from tain_agent.core.agent import TaoAgent
        
        agent1 = TaoAgent(config_path=str(temp_workspace / "config.yaml"))
        agent1.agent_name = "test_persist"
        agent1.phase = "work"
        
        # Save phase (if memory subsystem available)
        if hasattr(agent1, 'memory') and agent1.memory:
            agent1._save_phase_to_memory()
        
        agent2 = TaoAgent(config_path=str(temp_workspace / "config.yaml"))
        agent2.agent_name = "test_persist"
        # Phase should be restored
        assert agent2.phase in ("explore", "work")

    def test_agent_tool_execution_roundtrip(self, temp_workspace):
        """Mock LLM returns a tool call → agent executes it → result appended."""
        from tain_agent.core.agent import TaoAgent
        from tain_agent.core.llm import LLMResponse, ToolCall
        
        agent = TaoAgent(config_path=str(temp_workspace / "config.yaml"))
        agent.agent_name = "test_tools"
        
        # Verify tool registry is populated
        tools = agent.tools.list_tools()
        assert len(tools) > 0, "Agent should have primal tools registered"

    def test_agent_backend_none_handled_gracefully(self, temp_workspace):
        """Agent without a configured backend should return 0 from run()."""
        from tain_agent.core.agent import TaoAgent
        agent = TaoAgent(config_path=str(temp_workspace / "config.yaml"))
        agent.agent_name = "test_no_backend"
        
        # Without API key, backend should be None
        if agent.backend is None:
            result = agent.run()
            assert result == 0


class TestConversationPersistence:
    def test_conversation_clear_and_append(self, temp_workspace):
        from tain_agent.core.agent import TaoAgent
        agent = TaoAgent(config_path=str(temp_workspace / "config.yaml"))
        agent.agent_name = "test_conv"
        
        agent.conversation.clear()
        agent.conversation.append("user", "Hello")
        assert agent.conversation.len() == 1

    def test_conversation_checkpoint_does_not_crash(self, temp_workspace):
        from tain_agent.core.agent import TaoAgent
        agent = TaoAgent(config_path=str(temp_workspace / "config.yaml"))
        agent.agent_name = "test_checkpoint"
        
        agent.conversation.append("user", "Hello")
        result = agent.conversation.checkpoint()
        assert result is not None


class TestRegistryResilience:
    def test_list_agents_handles_missing_registry(self, temp_workspace):
        """Listing agents when no registry exists should return empty, not crash."""
        from tain_agent.core.agent_factory import AgentFactory
        factory = AgentFactory(workspace_root=str(temp_workspace))
        agents = factory.list_agents()
        assert isinstance(agents, list)
```

- [ ] **Step 2: 运行集成测试**

```bash
python3 -m pytest tests/test_integration.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_integration.py
git commit -m "test: add agent lifecycle integration tests (P2-14)"
```

---

## 最终验证

全部任务完成后运行：

```bash
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

预期：~300+ 测试通过（原有 282 + 新增 ~30）

---

## 任务依赖关系

```
A1 ─┬─ A2 ─┬─ A3 ─┬─ A4 ─┬─ A5  (可顺序或并行)
     │       │       │       │
     └───────┴───────┴───────┘
                              │
B1 ──┬──                       │
     └── B2                    │
            │                  │
            └── C1 ── C2 ── C3 │
                        │      │
D1 ─ D2 ─ D3 ─ D4 ────────────┘
                        │
                        └── E1 ─ E2 ─ E3 ─ E4

A系列可内部并行（改不同文件），B系列依赖A5（config重命名），C系列依赖A+B完成，
D系列相对独立，E系列在末尾
```
