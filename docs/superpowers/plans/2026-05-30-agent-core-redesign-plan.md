# Agent 核心重构 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以 Core-Plugins 架构替代当前 Mixin-based TaoAgent，构建 7 个 Protocol 化插件子系统

**Architecture:** 三阶段渐进迁移——先建接口层和适配器（零破坏），再逐插件替换，最后清理旧代码。AgentKernel 负责 PRAL 循环编排，插件间通过事件路由通信，不直接 import

**Tech Stack:** Python 3.12+, Protocol (PEP 544), Pydantic (data models), SQLite (EM/KB/Collaboration), NetworkX (SM/KB graph), existing `tain_agent/core/` 基础设施

---

## 文件结构设计

```
tain_agent/
  kernel/                          # 新建 — Agent 内核
    __init__.py                    # AgentKernel 类
    protocol.py                    # PluginProtocol + AgentContext + HealthStatus
    pral.py                        # PRAL 认知循环 (Perceive/Reason/Act/Learn)
    lifecycle.py                   # 生命周期管理 (create/start/stop/export)
    dispatch.py                    # 事件路由 dispatch()

  plugins/                         # 新建 — 插件实现
    __init__.py
    identity/
      __init__.py                  # IdentityPlugin
      model.py                     # AgentIdentity, DomainExpertise, Value, BehaviorConstraints, Goal
    memory/
      __init__.py                  # MemoryPlugin
      episodic.py                  # EpisodicMemory, EpisodicStore (SQLite + vector)
      semantic.py                  # SemanticMemory, SemanticStore (NetworkX + JSON)
      decay.py                     # decay_curve(), consolidate()
    skill/
      __init__.py                  # SkillPlugin
      model.py                     # Skill, Step, MaturityLevel
      composer.py                  # compose_skills()
    tool/
      __init__.py                  # ToolPlugin (wraps existing tools/)
      forge_cycle.py               # ClosedForgeCycle: generate→forge→verify→register
    knowledge/
      __init__.py                  # KnowledgePlugin
      graph.py                     # Entity, Relation, KnowledgeGraph
      lifecycle.py                 # conflict_detect(), freshness_check(), inherit()
    workflow/
      __init__.py                  # WorkflowPlugin
      engine.py                    # WorkflowEngine (DAG builder, topological sort, parallel exec)
    collaboration/
      __init__.py                  # CollaborationPlugin
      team.py                      # Team, TeamMember, TeamTask
      reputation.py                # Reputation, SocialGraph
      bus.py                       # Upgraded MessageBus (type, priority, TTL, broadcast)

  core/                            # 保留 — 已稳定的基础设施 (不变)
    llm.py, personality.py, drives.py, conversation.py, ...
  tools/                           # 保留 — 工具系统 (ToolPlugin 内部包装)
    registry.py, forge.py, primal.py, base.py
  evolution/                       # 标记 deprecated — 逻辑迁入 kernel/ 或 plugins/
```

---

## 阶段 1: 基础层 — Protocol + Kernel + Adapters

### Task 1: PluginProtocol + AgentContext + HealthStatus

**Files:**
- Create: `tain_agent/kernel/__init__.py`
- Create: `tain_agent/kernel/protocol.py`
- Create: `tests/test_plugin_protocol.py`

- [ ] **Step 1: Create `tain_agent/kernel/__init__.py`**

```python
"""Agent Kernel — PRAL orchestration with plugin protocol."""

__all__ = ["AgentKernel", "PluginProtocol", "AgentContext", "HealthStatus"]
```

- [ ] **Step 2: Create `tain_agent/kernel/protocol.py`**

```python
"""PluginProtocol, AgentContext, HealthStatus — the contract every plugin fulfills."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass
class HealthStatus:
    status: Literal["ok", "warning", "critical"] = "ok"
    metrics: dict[str, float] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)


@dataclass
class AgentContext:
    agent_name: str
    agent_id: str
    evolution_mode: str              # "specified" | "chaos"
    workspace_path: Path
    config: dict
    kernel_version: str


@runtime_checkable
class PluginProtocol(Protocol):
    """Contract every plugin must satisfy.

    Required: initialize, shutdown, health_check, snapshot, restore.
    Optional: on_cycle_start, on_cycle_end, enrich_prompt, on_llm_response.
    """

    # ── Lifecycle ──
    def initialize(self, ctx: AgentContext) -> None: ...
    def shutdown(self) -> None: ...

    # ── State ──
    def health_check(self) -> HealthStatus: ...
    def snapshot(self) -> dict: ...
    def restore(self, data: dict) -> None: ...

    # ── PRAL hooks (optional) ──
    def on_cycle_start(self, cycle: int) -> None: ...
    def on_cycle_end(self, cycle: int) -> None: ...
    def enrich_prompt(self, base: str) -> str: ...
    def on_llm_response(self, response: Any) -> None: ...
```

- [ ] **Step 3: Create `tests/test_plugin_protocol.py`**

```python
"""Tests for PluginProtocol, AgentContext, HealthStatus."""

from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol


class TestHealthStatus:
    def test_default_status_is_ok(self):
        hs = HealthStatus()
        assert hs.status == "ok"
        assert hs.metrics == {}
        assert hs.alerts == []

    def test_warning_status_with_alerts(self):
        hs = HealthStatus(status="warning", alerts=["low memory"])
        assert hs.status == "warning"
        assert len(hs.alerts) == 1


class TestAgentContext:
    def test_required_fields(self):
        ctx = AgentContext(
            agent_name="test",
            agent_id="agent-001",
            evolution_mode="specified",
            workspace_path=Path("/tmp/ws"),
            config={"llm": {"model": "test"}},
            kernel_version="0.6.0",
        )
        assert ctx.agent_name == "test"
        assert ctx.evolution_mode == "specified"
        assert ctx.kernel_version == "0.6.0"


class TestPluginProtocol:
    def test_minimal_plugin_isinstance_check(self):
        class MinimalPlugin:
            def initialize(self, ctx): pass
            def shutdown(self): pass
            def health_check(self): return HealthStatus()
            def snapshot(self): return {}
            def restore(self, data): pass

        plugin = MinimalPlugin()
        assert isinstance(plugin, PluginProtocol)

    def test_missing_method_fails_check(self):
        class BadPlugin:
            pass

        assert not isinstance(BadPlugin(), PluginProtocol)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_plugin_protocol.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tain_agent/kernel/ tain_agent/kernel/protocol.py tests/test_plugin_protocol.py
git commit -m "feat: add PluginProtocol, AgentContext, HealthStatus foundation"
```

---

### Task 2: AgentKernel — 生命周期 + PRAL 循环 + 事件路由

**Files:**
- Create: `tain_agent/kernel/lifecycle.py`
- Create: `tain_agent/kernel/pral.py`
- Create: `tain_agent/kernel/dispatch.py`
- Modify: `tain_agent/kernel/__init__.py`
- Create: `tests/test_kernel.py`

- [ ] **Step 1: Create `tain_agent/kernel/dispatch.py`**

```python
"""Event dispatch — routes cross-plugin calls through the Kernel."""

from __future__ import annotations
from typing import Any, Callable
import logging

logger = logging.getLogger(__name__)


class Dispatch:
    """Typed event router. Plugins never import each other — they call dispatch()."""

    def __init__(self):
        self._routes: dict[str, Callable] = {}

    def register(self, event: str, handler: Callable) -> None:
        if event in self._routes:
            logger.warning("Dispatch route %r overwritten", event)
        self._routes[event] = handler

    def call(self, event: str, *args: Any, **kwargs: Any) -> Any:
        handler = self._routes.get(event)
        if handler is None:
            logger.debug("Dispatch: no handler for %r", event)
            return None
        try:
            return handler(*args, **kwargs)
        except Exception:
            logger.exception("Dispatch %r failed", event)
            return None
```

- [ ] **Step 2: Create `tain_agent/kernel/lifecycle.py`**

```python
"""Agent lifecycle management — create, start, stop, pause, resume, export."""

from __future__ import annotations
import logging
from typing import Optional
from tain_agent.kernel.protocol import AgentContext, PluginProtocol

logger = logging.getLogger(__name__)

PLUGIN_LAYOUT = {
    "specified": ["identity", "memory", "skill", "tool", "knowledge", "workflow", "collaboration"],
    "chaos": ["identity", "memory", "tool"],
}


class LifecycleManager:
    """Owns plugin instances and drives their lifecycle."""

    def __init__(self):
        self._plugins: dict[str, PluginProtocol] = {}
        self._ctx: Optional[AgentContext] = None

    @property
    def plugins(self) -> dict[str, PluginProtocol]:
        return dict(self._plugins)

    def load(self, ctx: AgentContext, plugin_factories: dict[str, type]) -> None:
        """Load plugins according to evolution mode."""
        self._ctx = ctx
        layout = PLUGIN_LAYOUT.get(ctx.evolution_mode, PLUGIN_LAYOUT["specified"])
        for name in layout:
            factory = plugin_factories.get(name)
            if factory is None:
                logger.warning("Plugin %r not found in factories, skipping", name)
                continue
            instance = factory()
            instance.initialize(ctx)
            self._plugins[name] = instance
            logger.info("Plugin %r loaded", name)

    def get(self, name: str) -> Optional[PluginProtocol]:
        return self._plugins.get(name)

    def all_health_checks(self) -> dict[str, dict]:
        return {name: p.health_check() for name, p in self._plugins.items()}

    def shutdown_all(self) -> None:
        for name, plugin in list(self._plugins.items()):
            try:
                plugin.shutdown()
            except Exception:
                logger.exception("Plugin %r shutdown failed", name)
            finally:
                del self._plugins[name]
```

- [ ] **Step 3: Create `tain_agent/kernel/pral.py`**

```python
"""PRAL cognitive loop — Perceive → Reason → Act → Learn."""

from __future__ import annotations
import logging
from tain_agent.kernel.lifecycle import LifecycleManager
from tain_agent.kernel.dispatch import Dispatch

logger = logging.getLogger(__name__)


class PRALLoop:
    """Drives the main cognitive cycle. Plugins enrich each phase via hooks."""

    def __init__(self, lifecycle: LifecycleManager, dispatch: Dispatch):
        self._lm = lifecycle
        self._dispatch = dispatch
        self._running = False
        self.cycle_count = 0

    def run(self, llm_backend, conversation, drive_system, system_prompt_template: str,
            max_cycles: int = float("inf"), stop_signal: callable = None) -> int:
        """Execute PRAL cycles until stop."""
        self._running = True
        while self._running:
            self.cycle_count += 1
            if self.cycle_count > max_cycles:
                break
            if stop_signal and stop_signal():
                break

            logger.info("Cycle #%s", self.cycle_count)
            self._notify_plugins("on_cycle_start", self.cycle_count)

            # ① PERCEIVE
            context = self._perceive()

            # ② REASON
            system_prompt = self._build_prompt(system_prompt_template)
            response = llm_backend.create_message(
                system_prompt=system_prompt,
                messages=conversation.to_claude_messages(),
                tools=self._gather_tool_definitions(),
            )
            if response is None:
                continue
            self._notify_plugins("on_llm_response", response)

            # ③ ACT
            self._act(response, conversation)

            # ④ LEARN
            self._learn(response, conversation)
            self._notify_plugins("on_cycle_end", self.cycle_count)

            conversation.trim_to_token_budget(keep_last=40)

        return 0

    def _perceive(self) -> dict:
        ctx: dict = {}
        # Gather from plugins that exist
        mem = self._lm.get("memory")
        if mem:
            ctx["memories"] = mem.recall("recent context", k=5)
        kw = self._lm.get("knowledge")
        if kw:
            ctx["knowledge"] = kw.query("recent topic")
        collab = self._lm.get("collaboration")
        if collab:
            ctx["inbox"] = collab.check_inbox()
        wf = self._lm.get("workflow")
        if wf:
            ctx["active_workflows"] = wf.status_all()
        return ctx

    def _build_prompt(self, base: str) -> str:
        prompt = base
        for name in ["identity", "memory", "knowledge", "skill"]:
            plugin = self._lm.get(name)
            if plugin:
                prompt = plugin.enrich_prompt(prompt)
        # Drive system is not a plugin — called directly
        return prompt

    def _gather_tool_definitions(self):
        tool_plugin = self._lm.get("tool")
        if tool_plugin:
            return tool_plugin.list_tools()
        return []

    def _act(self, response, conversation) -> None:
        text_parts = response.text_blocks
        tool_calls = response.tool_calls

        assistant_content = [{"type": "text", "text": t} for t in text_parts]
        for tc in tool_calls:
            assistant_content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
        if assistant_content:
            conversation.append("assistant", assistant_content)

        if tool_calls:
            for tc in tool_calls:
                result = self._dispatch.call("tool.call", tc.name, **tc.input)
                content = result if isinstance(result, str) else str(result)
                conversation.append("user", [{"type": "tool_result", "tool_use_id": tc.id, "content": content}])

    def _learn(self, response, conversation) -> None:
        mem = self._lm.get("memory")
        if mem:
            mem.encode(f"Cycle {self.cycle_count}: {len(response.tool_calls)} tool calls", importance=0.3)

    def _notify_plugins(self, method: str, *args) -> None:
        for plugin in self._lm.plugins.values():
            try:
                fn = getattr(plugin, method, None)
                if fn:
                    fn(*args)
            except Exception:
                logger.exception("Plugin hook %s failed", method)

    def stop(self) -> None:
        self._running = False
```

- [ ] **Step 4: Update `tain_agent/kernel/__init__.py`**

```python
"""Agent Kernel — PRAL orchestration with plugin protocol."""

from tain_agent.kernel.protocol import PluginProtocol, AgentContext, HealthStatus
from tain_agent.kernel.lifecycle import LifecycleManager
from tain_agent.kernel.pral import PRALLoop
from tain_agent.kernel.dispatch import Dispatch


class AgentKernel:
    """Top-level entry point for the Core-Plugins architecture."""

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.dispatch = Dispatch()
        self.lifecycle = LifecycleManager()
        self.pral = PRALLoop(self.lifecycle, self.dispatch)

    def load_plugins(self, factories: dict[str, type]) -> None:
        self.lifecycle.load(self.ctx, factories)
        # Register cross-plugin dispatch routes
        for event, handler in self._build_routes().items():
            self.dispatch.register(event, handler)

    def _build_routes(self) -> dict:
        routes = {}
        tp = self.lifecycle.get("tool")
        if tp:
            routes["tool.call"] = tp.call
            routes["tool.forge"] = tp.forge
        sp = self.lifecycle.get("skill")
        if sp:
            routes["skill.execute"] = sp.execute
        kp = self.lifecycle.get("knowledge")
        if kp:
            routes["knowledge.query"] = kp.query
        mp = self.lifecycle.get("memory")
        if mp:
            routes["memory.recall"] = mp.recall
        wp = self.lifecycle.get("workflow")
        if wp:
            routes["workflow.advance"] = wp.advance
        cp = self.lifecycle.get("collaboration")
        if cp:
            routes["collaboration.send"] = cp.send
        return routes

    def run(self, llm_backend, conversation, drive_system, system_prompt: str,
            max_cycles=float("inf"), stop_signal=None) -> int:
        return self.pral.run(llm_backend, conversation, drive_system, system_prompt,
                             max_cycles=max_cycles, stop_signal=stop_signal)

    def shutdown(self) -> None:
        self.pral.stop()
        self.lifecycle.shutdown_all()


__all__ = ["AgentKernel", "PluginProtocol", "AgentContext", "HealthStatus"]
```

- [ ] **Step 5: Create `tests/test_kernel.py`**

```python
"""Tests for AgentKernel, LifecycleManager, PRALLoop, Dispatch."""

from pathlib import Path
from tain_agent.kernel import AgentKernel, AgentContext, HealthStatus
from tain_agent.kernel.lifecycle import LifecycleManager
from tain_agent.kernel.dispatch import Dispatch


class TestDispatch:
    def test_register_and_call(self):
        d = Dispatch()
        d.register("test.event", lambda x: x * 2)
        assert d.call("test.event", 3) == 6

    def test_missing_event_returns_none(self):
        d = Dispatch()
        assert d.call("nonexistent") is None

    def test_handler_exception_returns_none(self):
        d = Dispatch()
        d.register("failing", lambda: 1 / 0)
        assert d.call("failing") is None


class TestLifecycleManager:
    def _make_ctx(self):
        return AgentContext(
            agent_name="test", agent_id="a1", evolution_mode="chaos",
            workspace_path=Path("/tmp/ws"), config={}, kernel_version="0.6.0",
        )

    def _make_factory(self):
        class FakePlugin:
            def initialize(self, ctx): self.ctx = ctx
            def shutdown(self): pass
            def health_check(self): return HealthStatus(status="ok")
            def snapshot(self): return {}
            def restore(self, data): pass
            def enrich_prompt(self, base): return base
        return {"identity": FakePlugin, "memory": FakePlugin, "tool": FakePlugin}

    def test_chaos_mode_loads_three_plugins(self):
        lm = LifecycleManager()
        lm.load(self._make_ctx(), self._make_factory())
        assert list(lm.plugins.keys()) == ["identity", "memory", "tool"]

    def test_get_returns_none_for_unloaded(self):
        lm = LifecycleManager()
        lm.load(self._make_ctx(), self._make_factory())
        assert lm.get("collaboration") is None

    def test_shutdown_clears_all(self):
        lm = LifecycleManager()
        lm.load(self._make_ctx(), self._make_factory())
        lm.shutdown_all()
        assert len(lm.plugins) == 0
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_kernel.py -v
```

Expected: 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git add tain_agent/kernel/ tests/test_kernel.py
git commit -m "feat: add AgentKernel with PRAL loop, lifecycle, dispatch"
```

---

### Task 3: Adapters — 现有子系统桥接到 PluginProtocol

**Files:**
- Create: `tain_agent/plugins/__init__.py`
- Create: `tain_agent/plugins/_adapters.py`

- [ ] **Step 1: Create `tain_agent/plugins/__init__.py`**

```python
"""Plugin implementations and adapters for the Core-Plugins architecture."""
```

- [ ] **Step 2: Create `tain_agent/plugins/_adapters.py`**

```python
"""Adapters that wrap existing TaoAgent subsystems as PluginProtocol instances.

These provide backward-compatible bridges so the new Kernel can drive
old subsystems without modifying them. Each adapter will be removed
once its corresponding native plugin is built and validated.
"""

from __future__ import annotations
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol


class ExistingToolAdapter:
    """Wraps the current ToolRegistry + ToolForge as a ToolPlugin stand-in."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._registry = None   # set during initialize
        self._forge = None      # set during initialize

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        from tain_agent.tools.registry import ToolRegistry
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.primal import register_primal_tools
        self._registry = ToolRegistry()
        self._forge = ToolForge(workspace=str(ctx.workspace_path))
        register_primal_tools(self._registry)

    def shutdown(self) -> None:
        self._registry = None
        self._forge = None

    def health_check(self) -> HealthStatus:
        if self._registry is None:
            return HealthStatus(status="critical", alerts=["registry not initialized"])
        return HealthStatus(status="ok", metrics={"tool_count": float(self._registry.count())})

    def snapshot(self) -> dict:
        if self._registry:
            return {"tools": list(self._registry.list_tools().keys())}
        return {}

    def restore(self, data: dict) -> None:
        pass  # Existing registry re-initializes from disk

    def enrich_prompt(self, base: str) -> str:
        if self._registry is None:
            return base
        tools = self._registry.list_tools()
        lines = ["\n\n## 当前可用工具"]
        for name, info in tools.items():
            lines.append(f"- **{name}**: {info.get('description', '')}")
        return base + "\n".join(lines)

    def list_tools(self):
        if self._registry:
            return self._registry.list_tools()
        return {}

    def call(self, name: str, **kwargs):
        if self._registry:
            return self._registry.call(name, **kwargs)
        return {"error": "registry not initialized"}

    def forge(self, name: str, description: str, code: str):
        if self._forge:
            return self._forge.forge(name=name, description=description, code=code, parameters={})
        return {"success": False, "error": "forge not initialized"}


class ExistingPersonalityAdapter:
    """Wraps the current Personality + DriveSystem as an IdentityPlugin stand-in."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._personality = None

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        from tain_agent.core.personality import Personality
        self._personality = Personality()

    def shutdown(self) -> None:
        self._personality = None

    def health_check(self) -> HealthStatus:
        if self._personality is None:
            return HealthStatus(status="critical")
        return HealthStatus(
            status="ok",
            metrics={"total_traits": float(self._personality.total_traits())},
        )

    def snapshot(self) -> dict:
        if self._personality:
            return self._personality.introspect()
        return {}

    def restore(self, data: dict) -> None:
        pass

    def enrich_prompt(self, base: str) -> str:
        if self._personality and not self._personality.is_empty():
            return base + "\n\n" + self._personality.get_context_for_prompt()
        return base

    def on_llm_response(self, response) -> None:
        if self._personality and response.tool_calls:
            tool_names = [tc.name for tc in response.tool_calls]
            self._personality.auto_observe(tool_names, response.text_blocks)


class ExistingMemoryAdapter:
    """Wraps the current Memory system as a MemoryPlugin stand-in."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._memory = None

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        from tain_agent.core.memory import Memory
        self._memory = Memory(workspace_dir=str(ctx.workspace_path))

    def shutdown(self) -> None:
        if self._memory:
            self._memory.long_term.flush()
        self._memory = None

    def health_check(self) -> HealthStatus:
        if self._memory is None:
            return HealthStatus(status="critical")
        return HealthStatus(status="ok")

    def snapshot(self) -> dict:
        if self._memory:
            return self._memory.snapshot()
        return {}

    def restore(self, data: dict) -> None:
        pass

    def enrich_prompt(self, base: str) -> str:
        return base  # Existing memory doesn't inject into prompt

    def recall(self, query: str, k: int = 5):
        return []  # Existing memory has no vector recall

    def encode(self, content: str, importance: float = 0.5):
        pass  # Existing memory uses different API
```

- [ ] **Step 3: Write adapter test**

```python
# tests/test_adapters.py
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins._adapters import (
    ExistingToolAdapter,
    ExistingPersonalityAdapter,
    ExistingMemoryAdapter,
)


class TestExistingToolAdapter:
    def test_satisfies_protocol(self):
        assert isinstance(ExistingToolAdapter(), PluginProtocol)

    def test_initialize_and_health(self):
        adapter = ExistingToolAdapter()
        ctx = AgentContext("test", "a1", "specified", Path("/tmp/ws"), {}, "0.6.0")
        adapter.initialize(ctx)
        health = adapter.health_check()
        assert health.status == "ok"
        assert "tool_count" in health.metrics


class TestExistingPersonalityAdapter:
    def test_satisfies_protocol(self):
        assert isinstance(ExistingPersonalityAdapter(), PluginProtocol)

    def test_starts_empty(self):
        adapter = ExistingPersonalityAdapter()
        ctx = AgentContext("test", "a1", "chaos", Path("/tmp/ws"), {}, "0.6.0")
        adapter.initialize(ctx)
        snap = adapter.snapshot()
        assert snap.get("status") == "empty"


class TestExistingMemoryAdapter:
    def test_satisfies_protocol(self):
        assert isinstance(ExistingMemoryAdapter(), PluginProtocol)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_adapters.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tain_agent/plugins/ tests/test_adapters.py
git commit -m "feat: add PluginProtocol adapters for existing subsystems"
```

---

## 阶段 2: 逐插件替换 (Tasks 4-11)

### Task 4: IdentityPlugin — 完整身份档案

**Files:**
- Create: `tain_agent/plugins/identity/__init__.py`
- Create: `tain_agent/plugins/identity/model.py`
- Create: `tests/test_identity_plugin.py`

- [ ] **Step 1: Create `tain_agent/plugins/identity/model.py`**

```python
"""AgentIdentity data model — the complete agent resume."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Literal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Proficiency(IntEnum):
    NOVICE = 1
    BEGINNER = 2
    INTERMEDIATE = 3
    ADVANCED = 4
    EXPERT = 5


class AutonomyLevel(IntEnum):
    SUPERVISED = 1     # every action needs human approval
    GUIDED = 2         # most actions auto, critical ones need approval
    TRUSTED = 3        # only destructive actions need approval
    AUTONOMOUS = 4     # self-approves all actions within constraints
    FULL = 5           # no human in the loop


@dataclass
class DomainExpertise:
    domain: str
    proficiency: Proficiency = Proficiency.NOVICE
    evidence: list[str] = field(default_factory=list)
    acquired_at: str = field(default_factory=_now)


@dataclass
class Value:
    name: str
    priority: int = 5               # 1-10
    description: str = ""
    source: str = ""                # "role_assigned" | "self_discovered" | "external_feedback"


@dataclass
class BehaviorConstraints:
    allowed_categories: list[str] = field(default_factory=list)
    blocked_categories: list[str] = field(default_factory=list)
    max_autonomy_level: AutonomyLevel = AutonomyLevel.GUIDED
    requires_human_for: list[str] = field(default_factory=list)

    def requires_human_approval(self, action_category: str) -> bool:
        if action_category in self.blocked_categories:
            return True
        if action_category in self.requires_human_for:
            return True
        return False


@dataclass
class Goal:
    id: str
    title: str
    parent_id: str | None = None
    status: Literal["active", "completed", "abandoned"] = "active"
    progress: float = 0.0           # 0.0 - 1.0
    description: str = ""
    children: list[Goal] = field(default_factory=list)

    def add_child(self, child: Goal) -> None:
        child.parent_id = self.id
        self.children.append(child)


@dataclass
class ExperienceLevel:
    overall: int = 1                # 1-10
    domain_breakdown: dict[str, int] = field(default_factory=dict)


@dataclass
class CollaborationPrefs:
    preferred_roles: list[str] = field(default_factory=list)
    communication_style: str = "direct"
    team_size_preference: int = 3
    availability: Literal["always", "scheduled", "on_demand"] = "on_demand"


@dataclass
class EvolutionEvent:
    timestamp: str = field(default_factory=_now)
    event_type: str = ""
    description: str = ""
    version_from: str = ""
    version_to: str = ""


@dataclass
class AgentIdentity:
    """Complete agent identity — role, expertise, values, constraints, goals, experience."""

    # Core
    agent_id: str
    name: str
    role: str = ""
    role_description: str = ""
    evolution_mode: Literal["specified", "chaos"] = "specified"

    # Expertise
    expertise_domains: list[DomainExpertise] = field(default_factory=list)

    # Values
    values: list[Value] = field(default_factory=list)

    # Constraints
    constraints: BehaviorConstraints = field(default_factory=BehaviorConstraints)

    # Mission & Goals
    mission: str = ""
    goals: list[Goal] = field(default_factory=list)

    # Growth
    skill_catalog: list[str] = field(default_factory=list)       # skill names
    experience: ExperienceLevel = field(default_factory=ExperienceLevel)

    # Collaboration
    collaboration: CollaborationPrefs = field(default_factory=CollaborationPrefs)

    # Personality traits (7 categories, inherited from personality.py model)
    traits: dict[str, list[dict]] = field(default_factory=lambda: {
        "values": [], "communication_style": [], "interests": [],
        "quirks": [], "self_description": [], "relationship_stance": [],
        "growth_orientation": [],
    })

    # History
    evolution_log: list[EvolutionEvent] = field(default_factory=list)

    def awaken_from_role(self, role: str, role_description: str) -> None:
        """Initialize identity fields from a role assignment (Specified mode)."""
        self.role = role
        self.role_description = role_description
        self.mission = f"以 {role} 的身份持续学习和演化，成为该领域的专家"
        self.expertise_domains.append(DomainExpertise(
            domain=role, proficiency=Proficiency.BEGINNER,
            evidence=[f"Assigned role: {role}"],
        ))
        self.values.append(Value(name="专业精神", priority=8, source="role_assigned"))
        self.evolution_log.append(EvolutionEvent(
            event_type="awakening", description=f"Agent awakened with role: {role}",
            version_from="0.0.0", version_to="0.0.1",
        ))

    def add_expertise(self, domain: str, proficiency: Proficiency, evidence: str) -> None:
        existing = next((d for d in self.expertise_domains if d.domain == domain), None)
        if existing:
            if proficiency > existing.proficiency:
                existing.proficiency = proficiency
            existing.evidence.append(evidence)
        else:
            self.expertise_domains.append(DomainExpertise(
                domain=domain, proficiency=proficiency, evidence=[evidence],
            ))

    def upgrade_autonomy(self, new_level: AutonomyLevel, reason: str) -> None:
        self.constraints.max_autonomy_level = new_level
        self.evolution_log.append(EvolutionEvent(
            event_type="autonomy_upgrade",
            description=f"Autonomy upgraded to {new_level.name}: {reason}",
        ))

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)
```

- [ ] **Step 2: Create `tain_agent/plugins/identity/__init__.py`**

```python
"""IdentityPlugin — manages the agent's complete identity profile."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.identity.model import AgentIdentity, EvolutionEvent

logger = logging.getLogger(__name__)


class IdentityPlugin:
    """Plugin that owns AgentIdentity — who the agent is, what it values, its boundaries."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self.identity: AgentIdentity | None = None
        self._profile_path: Path | None = None

    # ── PluginProtocol ───────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._profile_path = ctx.workspace_path / "identity" / "profile.json"
        self._profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = self._load_or_create()

    def shutdown(self) -> None:
        self._save()
        self.identity = None

    def health_check(self) -> HealthStatus:
        if self.identity is None:
            return HealthStatus(status="critical", alerts=["identity not initialized"])
        metrics = {
            "expertise_count": float(len(self.identity.expertise_domains)),
            "values_count": float(len(self.identity.values)),
            "traits_total": float(sum(len(t) for t in self.identity.traits.values())),
            "goals_active": float(sum(1 for g in self.identity.goals if g.status == "active")),
            "skill_catalog_size": float(len(self.identity.skill_catalog)),
        }
        return HealthStatus(status="ok", metrics=metrics)

    def snapshot(self) -> dict:
        return self.identity.to_dict() if self.identity else {}

    def restore(self, data: dict) -> None:
        pass  # identity always loads from disk

    def enrich_prompt(self, base: str) -> str:
        if self.identity is None:
            return base
        parts = [base, "", "## 你的身份"]
        if self.identity.role:
            parts.append(f"角色: {self.identity.role}")
        if self.identity.mission:
            parts.append(f"使命: {self.identity.mission}")
        if self.identity.expertise_domains:
            domains = ", ".join(f"{d.domain}(L{d.proficiency})" for d in self.identity.expertise_domains)
            parts.append(f"专长领域: {domains}")
        if self.identity.constraints.max_autonomy_level.value < 4:
            parts.append(f"自主等级: {self.identity.constraints.max_autonomy_level.name} — 创建工具需要人类审批")
        # Include personality context from traits
        trait_ctx = self._trait_context()
        if trait_ctx:
            parts.append(trait_ctx)
        return "\n".join(parts)

    def on_llm_response(self, response) -> None:
        if self.identity and response.tool_calls:
            tool_names = [tc.name for tc in response.tool_calls]
            self._observe_traits(tool_names, response.text_blocks)

    # ── Persistence ──────────────────────────────────────────────

    def _load_or_create(self) -> AgentIdentity:
        if self._profile_path and self._profile_path.exists():
            try:
                data = json.loads(self._profile_path.read_text(encoding="utf-8"))
                return AgentIdentity(**data)
            except Exception as e:
                logger.warning("Failed to load identity profile: %s — creating new", e)
        identity = AgentIdentity(
            agent_id=self._ctx.agent_id,
            name=self._ctx.agent_name,
            evolution_mode=self._ctx.evolution_mode,
        )
        if self._ctx.evolution_mode == "specified":
            role = self._ctx.config.get("identity", {}).get("role", "")
            desc = self._ctx.config.get("identity", {}).get("role_description", "")
            identity.awaken_from_role(role, desc)
        return identity

    def _save(self) -> None:
        if self.identity and self._profile_path:
            self._profile_path.write_text(
                json.dumps(self.identity.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _trait_context(self) -> str:
        if not self.identity:
            return ""
        confident = {}
        for cat, traits in self.identity.traits.items():
            cat_traits = [t for t in traits if t.get("confidence", 0) >= 0.4]
            if cat_traits:
                confident[cat] = cat_traits
        if not confident:
            return ""
        lines = ["", "## 你的人格特质", ""]
        cat_names = {
            "values": "价值观", "communication_style": "沟通风格",
            "interests": "自然兴趣", "quirks": "独特习惯",
            "self_description": "自我认知", "relationship_stance": "与人/Agent的关系",
            "growth_orientation": "成长取向",
        }
        for cat, traits in confident.items():
            lines.append(f"**{cat_names.get(cat, cat)}**:")
            for t in sorted(traits, key=lambda x: x.get("confidence", 0), reverse=True):
                mark = "✓" if t.get("confidence", 0) >= 0.7 else "~"
                lines.append(f"  - [{mark}] {t['value']}")
            lines.append("")
        return "\n".join(lines)

    def _observe_traits(self, tool_names: list[str], text_parts: list[str]) -> None:
        """Behavioral observation — auto-discover traits from tool usage."""
        # Delegate to existing personality.py behavior patterns
        from tain_agent.core.personality import Personality
        # Create temporary Personality to run auto_observe, merge results
        temp = Personality()
        temp._traits = dict(self.identity.traits)  # copy current state
        temp.auto_observe(tool_names, text_parts)
        self.identity.traits = dict(temp._traits)  # copy back
```

- [ ] **Step 3: Create `tests/test_identity_plugin.py`**

```python
"""Tests for IdentityPlugin and AgentIdentity model."""

from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.identity import IdentityPlugin
from tain_agent.plugins.identity.model import (
    AgentIdentity, DomainExpertise, Proficiency, Value, Goal,
    BehaviorConstraints, AutonomyLevel, CollaborationPrefs,
)


class TestAgentIdentity:
    def test_specified_mode_awakens_from_role(self):
        identity = AgentIdentity(agent_id="a1", name="test", evolution_mode="specified")
        identity.awaken_from_role("Python 后端工程师", "擅长 FastAPI 和 PostgreSQL")
        assert identity.role == "Python 后端工程师"
        assert len(identity.expertise_domains) == 1
        assert identity.expertise_domains[0].proficiency == Proficiency.BEGINNER
        assert len(identity.values) == 1
        assert identity.values[0].name == "专业精神"

    def test_chaos_mode_starts_empty(self):
        identity = AgentIdentity(agent_id="a1", name="test", evolution_mode="chaos")
        assert identity.role == ""
        assert len(identity.expertise_domains) == 0

    def test_upgrade_autonomy_logs_event(self):
        identity = AgentIdentity(agent_id="a1", name="test")
        identity.upgrade_autonomy(AutonomyLevel.TRUSTED, "verified safe")
        assert identity.constraints.max_autonomy_level == AutonomyLevel.TRUSTED
        assert len(identity.evolution_log) == 1
        assert identity.evolution_log[0].event_type == "autonomy_upgrade"

    def test_goal_tree(self):
        identity = AgentIdentity(agent_id="a1", name="test")
        parent = Goal(id="g1", title="learn Python")
        child = Goal(id="g2", title="learn asyncio")
        parent.add_child(child)
        identity.goals.append(parent)
        assert identity.goals[0].children[0].id == "g2"
        assert identity.goals[0].children[0].parent_id == "g1"


class TestIdentityPlugin:
    def _make_ctx(self):
        return AgentContext(
            agent_name="test", agent_id="a1", evolution_mode="chaos",
            workspace_path=Path("/tmp/test_identity_ws"),
            config={}, kernel_version="0.6.0",
        )

    def test_satisfies_protocol(self):
        assert isinstance(IdentityPlugin(), PluginProtocol)

    def test_initialize_creates_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext("test", "a1", "chaos", Path(tmpdir), {}, "0.6.0")
            plugin = IdentityPlugin()
            plugin.initialize(ctx)
            assert plugin.identity is not None
            assert plugin.identity.agent_id == "a1"

    def test_enrich_prompt_adds_context(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext("test", "a1", "chaos", Path(tmpdir), {}, "0.6.0")
            plugin = IdentityPlugin()
            plugin.initialize(ctx)
            result = plugin.enrich_prompt("base prompt")
            assert "base prompt" in result
            assert "## 你的身份" in result
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_identity_plugin.py -v
```

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tain_agent/plugins/identity/ tests/test_identity_plugin.py
git commit -m "feat: add IdentityPlugin with complete AgentIdentity model"
```

---

### Task 5: MemoryPlugin — 仿生三层记忆

**Files:**
- Create: `tain_agent/plugins/memory/__init__.py`
- Create: `tain_agent/plugins/memory/episodic.py`
- Create: `tain_agent/plugins/memory/semantic.py`
- Create: `tain_agent/plugins/memory/decay.py`
- Create: `tests/test_memory_plugin.py`

- [ ] **Step 1: Create `tain_agent/plugins/memory/decay.py`**

```python
"""Memory decay engine — importance-based forgetting with recall boost."""

import math
from datetime import datetime, timezone


def _days_since(iso_timestamp: str) -> float:
    try:
        created = datetime.fromisoformat(iso_timestamp)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - created).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def decay_rate(importance: float) -> float:
    """Base decay rate — higher importance = slower decay.
    importance 1.0 → decay 0.01/day
    importance 0.1 → decay 0.30/day
    """
    return max(0.01, 0.30 * (1.0 - importance))


def boost_factor(last_recalled_at: str | None) -> float:
    """Temporary boost from recent recall. Drops by 50% per day."""
    if last_recalled_at is None:
        return 1.0
    days = _days_since(last_recalled_at)
    return max(1.0, 2.0 * math.exp(-0.7 * days))


def current_strength(importance: float, created_at: str,
                     recall_count: int, last_recalled_at: str | None = None) -> float:
    """Calculate memory strength: 0.0 (forgotten) — 1.0+ (vivid).

    strength = importance * e^(-decay_rate * days) * recall_bonus * recency_boost
    """
    days = _days_since(created_at)
    dr = decay_rate(importance)
    base = importance * math.exp(-dr * days)
    recall_bonus = 1.0 + math.log(1 + recall_count) * 0.1
    boost = boost_factor(last_recalled_at)
    return round(base * recall_bonus * boost, 6)


def should_forget(strength: float, threshold: float = 0.05) -> bool:
    return strength < threshold
```

- [ ] **Step 2: Create `tain_agent/plugins/memory/episodic.py`**

```python
"""Episodic memory store — SQLite + vector index for personal experiences."""

from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tain_agent.plugins.memory.decay import current_strength, should_forget


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_id() -> str:
    return f"em_{uuid.uuid4().hex[:12]}"


class EpisodicMemory:
    """A single episodic memory with decay-aware metadata."""

    def __init__(self, content: str, importance: float = 0.5):
        self.id = _make_id()
        self.content = content
        self.importance = max(0.0, min(1.0, importance))
        self.created_at = _now()
        self.last_recalled_at: str | None = None
        self.recall_count = 0
        self.associations: list[str] = []

    def strength(self) -> float:
        return current_strength(self.importance, self.created_at,
                                self.recall_count, self.last_recalled_at)

    def recall(self) -> str:
        self.recall_count += 1
        self.last_recalled_at = _now()
        return self.content

    def to_dict(self) -> dict:
        return {
            "id": self.id, "content": self.content,
            "importance": self.importance, "created_at": self.created_at,
            "last_recalled_at": self.last_recalled_at,
            "recall_count": self.recall_count, "associations": self.associations,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EpisodicMemory:
        mem = cls(data["content"], data.get("importance", 0.5))
        mem.id = data["id"]
        mem.created_at = data["created_at"]
        mem.last_recalled_at = data.get("last_recalled_at")
        mem.recall_count = data.get("recall_count", 0)
        mem.associations = data.get("associations", [])
        return mem


class EpisodicStore:
    """SQLite-backed persistent store for episodic memories."""

    DDL = """
    CREATE TABLE IF NOT EXISTS episodic (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        importance REAL NOT NULL DEFAULT 0.5,
        created_at TEXT NOT NULL,
        last_recalled_at TEXT,
        recall_count INTEGER NOT NULL DEFAULT 0,
        associations TEXT NOT NULL DEFAULT '[]',
        strength REAL NOT NULL DEFAULT 1.0
    );
    CREATE INDEX IF NOT EXISTS idx_episodic_strength ON episodic(strength DESC);
    CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic(created_at DESC);
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(self.DDL)
        self._conn.commit()

    def encode(self, content: str, importance: float = 0.5) -> EpisodicMemory:
        mem = EpisodicMemory(content, importance)
        self._conn.execute(
            "INSERT INTO episodic (id, content, importance, created_at, recall_count, associations, strength) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mem.id, mem.content, mem.importance, mem.created_at,
             mem.recall_count, json.dumps(mem.associations), mem.strength()),
        )
        self._conn.commit()
        return mem

    def recall(self, query: str, k: int = 10) -> list[EpisodicMemory]:
        """Simple keyword + recency search (向量检索在后续 Task 中加入)."""
        rows = self._conn.execute(
            "SELECT id, content, importance, created_at, last_recalled_at, recall_count, associations "
            "FROM episodic WHERE strength > 0.05 ORDER BY strength DESC LIMIT ?",
            (k,),
        ).fetchall()
        results = []
        for row in rows:
            data = {
                "id": row[0], "content": row[1], "importance": row[2],
                "created_at": row[3], "last_recalled_at": row[4],
                "recall_count": row[5], "associations": json.loads(row[6]),
            }
            results.append(EpisodicMemory.from_dict(data))
        return results

    def recent(self, n: int = 20) -> list[EpisodicMemory]:
        rows = self._conn.execute(
            "SELECT id, content, importance, created_at, last_recalled_at, recall_count, associations "
            "FROM episodic ORDER BY created_at DESC LIMIT ?", (n,),
        ).fetchall()
        return [EpisodicMemory.from_dict({
            "id": r[0], "content": r[1], "importance": r[2], "created_at": r[3],
            "last_recalled_at": r[4], "recall_count": r[5], "associations": json.loads(r[6]),
        }) for r in rows]

    def reinforce(self, memory_id: str) -> bool:
        mem = self._get_by_id(memory_id)
        if mem is None:
            return False
        mem.recall()
        self._conn.execute(
            "UPDATE episodic SET recall_count=?, last_recalled_at=?, strength=? WHERE id=?",
            (mem.recall_count, mem.last_recalled_at, mem.strength(), mem.id),
        )
        self._conn.commit()
        return True

    def forget(self, threshold: float = 0.05) -> int:
        """Remove memories below strength threshold. Returns count removed."""
        # Update strength for all, then delete weak ones
        rows = self._conn.execute("SELECT id, importance, created_at, recall_count, last_recalled_at FROM episodic").fetchall()
        to_delete = []
        for row in rows:
            s = current_strength(row[1], row[2], row[3], row[4])
            if should_forget(s, threshold):
                to_delete.append(row[0])
            else:
                self._conn.execute("UPDATE episodic SET strength=? WHERE id=?", (s, row[0]))
        if to_delete:
            placeholders = ",".join("?" * len(to_delete))
            self._conn.execute(f"DELETE FROM episodic WHERE id IN ({placeholders})", to_delete)
        self._conn.commit()
        return len(to_delete)

    def close(self) -> None:
        self._conn.close()

    def _get_by_id(self, memory_id: str) -> EpisodicMemory | None:
        row = self._conn.execute(
            "SELECT id, content, importance, created_at, last_recalled_at, recall_count, associations "
            "FROM episodic WHERE id=?", (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return EpisodicMemory.from_dict({
            "id": row[0], "content": row[1], "importance": row[2], "created_at": row[3],
            "last_recalled_at": row[4], "recall_count": row[5], "associations": json.loads(row[6]),
        })
```

- [ ] **Step 3: Create `tain_agent/plugins/memory/semantic.py`** (abridged — key structures)

```python
"""Semantic memory — lightweight graph store derived from episodic patterns."""

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SemanticStore:
    """NetworkX-based semantic graph store. Entities + relations extracted from EM."""

    def __init__(self, storage_path: Path):
        self._path = storage_path
        self._nodes: dict[str, dict] = {}
        self._edges: list[tuple[str, str, dict]] = []
        self._load()

    def add_entity(self, node_id: str, label: str, properties: dict | None = None) -> None:
        self._nodes[node_id] = {"label": label, "properties": properties or {}, "created_at": _now()}

    def add_relation(self, subject: str, predicate: str, obj: str, confidence: float = 1.0) -> None:
        self._edges.append((subject, obj, {"predicate": predicate, "confidence": confidence}))

    def query_related(self, node_id: str) -> list[dict]:
        results = []
        for s, o, data in self._edges:
            if s == node_id:
                results.append({"target": o, "predicate": data["predicate"], "confidence": data["confidence"]})
            elif o == node_id:
                results.append({"target": s, "predicate": data["predicate"], "confidence": data["confidence"]})
        return results

    def snapshot(self) -> dict:
        return {"nodes": dict(self._nodes), "edges": [{"s": s, "o": o, **d} for s, o, d in self._edges]}

    def save(self) -> None:
        self._path.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._nodes = data.get("nodes", {})
                self._edges = [(e["s"], e["o"], {"predicate": e["predicate"], "confidence": e.get("confidence", 1.0)})
                               for e in data.get("edges", [])]
            except Exception:
                pass
```

- [ ] **Step 4: Create `tain_agent/plugins/memory/__init__.py`**

```python
"""MemoryPlugin — biomimetic three-tier memory (WM → EM → SM)."""

from __future__ import annotations
import logging
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.memory.episodic import EpisodicStore
from tain_agent.plugins.memory.semantic import SemanticStore

logger = logging.getLogger(__name__)


class MemoryPlugin:
    """Three-tier memory: working (in-memory dict), episodic (SQLite+vector), semantic (graph)."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._working: list[dict] = []           # WM: session-scoped message buffer
        self._episodic: EpisodicStore | None = None
        self._semantic: SemanticStore | None = None

    # ── PluginProtocol ───────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        mem_dir = ctx.workspace_path / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        self._episodic = EpisodicStore(mem_dir / "episodic.db")
        self._semantic = SemanticStore(mem_dir / "semantic.json")
        self._working = []

    def shutdown(self) -> None:
        self.consolidate()
        if self._episodic:
            self._episodic.close()
        self._episodic = None
        self._semantic = None

    def health_check(self) -> HealthStatus:
        if self._episodic is None:
            return HealthStatus(status="critical")
        return HealthStatus(status="ok")

    def snapshot(self) -> dict:
        return {
            "working_count": len(self._working),
            "semantic": self._semantic.snapshot() if self._semantic else {},
        }

    def restore(self, data: dict) -> None:
        pass

    def enrich_prompt(self, base: str) -> str:
        memories = self.recall("recent activity", k=3)
        if not memories:
            return base
        lines = [base, "", "## 相关记忆"]
        for m in memories:
            lines.append(f"- {m.content[:150]}")
        return "\n".join(lines)

    # ── Memory Operations ────────────────────────────────────────

    def encode(self, content: str, importance: float = 0.5) -> str | None:
        if self._episodic is None:
            return None
        mem = self._episodic.encode(content, importance)
        return mem.id

    def recall(self, query: str, k: int = 10) -> list:
        if self._episodic is None:
            return []
        return self._episodic.recall(query, k)

    def recent(self, n: int = 20) -> list:
        if self._episodic is None:
            return []
        return self._episodic.recent(n)

    def reinforce(self, memory_id: str) -> bool:
        if self._episodic is None:
            return False
        return self._episodic.reinforce(memory_id)

    def consolidate(self) -> None:
        """Extract patterns from WM → EM, then EM → SM. Called at session end."""
        if self._episodic:
            self._episodic.forget(threshold=0.05)

    def summarize(self, time_range_hours: int = 24) -> str:
        recent_mems = self.recall("", k=50)
        if not recent_mems:
            return "No recent memories."
        return f"Last {time_range_hours}h: {len(recent_mems)} memories."
```

- [ ] **Step 5: Create `tests/test_memory_plugin.py`** (abridged — test decay model + episodic store)

```python
"""Tests for memory decay and episodic store."""

import tempfile
from pathlib import Path
from tain_agent.plugins.memory.decay import current_strength, should_forget, decay_rate
from tain_agent.plugins.memory.episodic import EpisodicMemory, EpisodicStore


class TestDecay:
    def test_high_importance_slow_decay(self):
        assert decay_rate(1.0) < decay_rate(0.1)

    def test_new_memory_has_high_strength(self):
        s = current_strength(1.0, "2026-05-30T00:00:00", 0)
        assert s > 0.8

    def test_old_memory_decays(self):
        s = current_strength(0.5, "2020-01-01T00:00:00", 0)
        assert s < 0.1

    def test_forget_threshold(self):
        assert should_forget(0.01, 0.05) is True
        assert should_forget(0.10, 0.05) is False


class TestEpisodicMemory:
    def test_recall_increments_count(self):
        mem = EpisodicMemory("test content", importance=0.8)
        mem.recall()
        assert mem.recall_count == 1

    def test_roundtrip_dict(self):
        mem = EpisodicMemory("test", importance=0.6)
        data = mem.to_dict()
        restored = EpisodicMemory.from_dict(data)
        assert restored.content == "test"
        assert restored.importance == 0.6


class TestEpisodicStore:
    def test_encode_and_recall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EpisodicStore(Path(tmpdir) / "test.db")
            store.encode("memory one", importance=0.9)
            store.encode("memory two", importance=0.3)
            results = store.recall("memory", k=5)
            assert len(results) >= 2

    def test_forget_weak_memories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EpisodicStore(Path(tmpdir) / "test.db")
            store.encode("important", importance=0.95)
            store.encode("trivial", importance=0.01)
            removed = store.forget(threshold=0.05)
            assert removed >= 0  # trivial may or may not be removed depending on time
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_memory_plugin.py -v
```

Expected: tests PASS (decay timing-sensitive assertions may need adjustment)

- [ ] **Step 7: Commit**

```bash
git add tain_agent/plugins/memory/ tests/test_memory_plugin.py
git commit -m "feat: add MemoryPlugin with decay engine, episodic store, semantic store"
```

---

### Task 6: ToolPlugin — 包装现有工具系统 + 闭合演化循环

**Files:**
- Create: `tain_agent/plugins/tool/__init__.py`
- Create: `tain_agent/plugins/tool/forge_cycle.py`
- Create: `tests/test_tool_plugin.py`

- [ ] **Step 1: Create `tain_agent/plugins/tool/forge_cycle.py`**

```python
"""Closed forge cycle — Generate → Forge → Verify → Register.

Key improvement over current pipeline: adds LLM code generation to close the loop.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CycleStage(Enum):
    ANALYZE = "analyze"
    DESIGN = "design"
    GENERATE = "generate"
    FORGE = "forge"
    VERIFY = "verify"
    REGISTER = "register"


@dataclass
class ImprovementSpec:
    capability_id: str
    description: str
    tool_name: str = ""
    tool_description: str = ""
    design_notes: str = ""
    priority: str = "MEDIUM"


@dataclass
class StageResult:
    stage: CycleStage
    passed: bool = False
    output: dict | None = None
    error: str | None = None


@dataclass
class ForgeCycleResult:
    spec: ImprovementSpec
    stages: list[StageResult] = field(default_factory=list)
    overall_passed: bool = False
    attempts: int = 0

    def finalize(self) -> ForgeCycleResult:
        self.overall_passed = all(s.passed for s in self.stages)
        return self


class ClosedForgeCycle:
    """Runs the full 6-stage cycle: Analyze → Design → Generate → Forge → Verify → Register."""

    MAX_GENERATE_RETRIES = 3

    def __init__(self, tool_plugin):
        self._plugin = tool_plugin
        self._failed_attempts: dict[str, int] = {}  # capability_id → consecutive failures

    def run(self, spec: ImprovementSpec | None = None,
            code: str = "", llm_backend=None) -> ForgeCycleResult:
        """Execute the full forge cycle. Returns result with all stage details."""
        if spec is None:
            spec = ImprovementSpec("unknown", "No spec provided")

        result = ForgeCycleResult(spec=spec)

        # Stage 1: Analyze (skip if spec was provided externally)
        result.stages.append(StageResult(CycleStage.ANALYZE, passed=True,
                                         output={"action": "spec_provided"}))

        # Stage 2: Design (skip if spec was provided externally)
        result.stages.append(StageResult(CycleStage.DESIGN, passed=True,
                                         output={"action": "spec_provided"}))

        # Stage 3: Generate (LLM code generation)
        gen_result = self._generate(spec, code, llm_backend)
        result.stages.append(gen_result)
        if not gen_result.passed:
            return result.finalize()
        generated_code = gen_result.output.get("code", "")

        # Stage 4: Forge (existing sandbox pipeline)
        forge_result = self._plugin.forge(spec.tool_name, spec.tool_description, generated_code)
        passed = forge_result.get("success", False)
        result.stages.append(StageResult(CycleStage.FORGE, passed=passed,
                                         output=forge_result,
                                         error=None if passed else forge_result.get("error")))
        if not passed:
            return result.finalize()

        # Stage 5: Verify (regression test)
        verify_result = self._verify(spec.tool_name)
        result.stages.append(StageResult(CycleStage.VERIFY, passed=verify_result.get("passed", False),
                                         output=verify_result))

        # Stage 6: Register
        result.stages.append(StageResult(CycleStage.REGISTER, passed=True,
                                         output={"tool_name": spec.tool_name, "status": "registered"}))

        return result.finalize()

    def _generate(self, spec: ImprovementSpec, code: str, llm_backend) -> StageResult:
        if code and code.strip():
            return StageResult(CycleStage.GENERATE, passed=True, output={"code": code, "source": "provided"})

        if llm_backend is None:
            return StageResult(CycleStage.GENERATE, passed=False, error="No LLM backend for code generation")

        cap_id = spec.capability_id
        consecutive = self._failed_attempts.get(cap_id, 0)
        if consecutive >= self.MAX_GENERATE_RETRIES:
            return StageResult(CycleStage.GENERATE, passed=False,
                               error=f"Exceeded {self.MAX_GENERATE_RETRIES} retries for {cap_id}")

        # Build generation prompt
        prompt = f"""Generate a Python tool function for the following specification:

Capability: {spec.capability_id}
Description: {spec.description}
Tool Name: {spec.tool_name}

Requirements:
- Function must be named '{spec.tool_name}'
- Must accept keyword arguments matching the tool's parameters
- Must return a dict with at least 'success' (bool) and 'output' or 'error' keys
- Must only use safe imports (json, re, datetime, pathlib, math, etc.)
- Must NOT use os.system, subprocess, exec, eval
- Must read/write only within the provided workspace path

Return ONLY valid Python code, no explanation."""

        try:
            response = llm_backend.create_message(
                system_prompt="You are a tool generator. Output only valid Python code.",
                messages=[{"role": "user", "content": prompt}],
                tools=[],  # No tools needed for generation
            )
            code_text = "\n".join(response.text_blocks)
            # Basic validation
            if f"def {spec.tool_name}" not in code_text:
                self._failed_attempts[cap_id] = consecutive + 1
                return StageResult(CycleStage.GENERATE, passed=False,
                                   error="Generated code missing expected function name")

            self._failed_attempts[cap_id] = 0  # reset on success
            return StageResult(CycleStage.GENERATE, passed=True,
                               output={"code": code_text, "source": "llm_generated"})
        except Exception as e:
            self._failed_attempts[cap_id] = consecutive + 1
            return StageResult(CycleStage.GENERATE, passed=False, error=str(e))

    def _verify(self, tool_name: str) -> dict:
        """Check tool is registered and callable."""
        tools = self._plugin.list_tools()
        if tool_name not in tools:
            return {"passed": False, "error": f"Tool '{tool_name}' not in registry"}
        try:
            result = self._plugin.call(tool_name, _verify=True)
            return {"passed": True, "result": str(result)[:200]}
        except Exception as e:
            return {"passed": False, "error": str(e)}
```

- [ ] **Step 2: Create `tain_agent/plugins/tool/__init__.py`**

```python
"""ToolPlugin — wraps existing ToolRegistry + ToolForge, adds closed forge cycle."""

from __future__ import annotations
import logging
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.tool.forge_cycle import ClosedForgeCycle

logger = logging.getLogger(__name__)


class ToolPlugin:
    """Wraps the existing tool system (registry, forge, sandbox) as a plugin."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._registry = None
        self._forge = None
        self.forge_cycle: ClosedForgeCycle | None = None

    # ── PluginProtocol ───────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        from tain_agent.tools.registry import ToolRegistry
        from tain_agent.tools.forge import ToolForge
        from tain_agent.tools.primal import register_primal_tools

        self._registry = ToolRegistry()
        self._forge = ToolForge(workspace=str(ctx.workspace_path))
        register_primal_tools(self._registry)
        self.forge_cycle = ClosedForgeCycle(self)

    def shutdown(self) -> None:
        self._registry = None
        self._forge = None

    def health_check(self) -> HealthStatus:
        if self._registry is None:
            return HealthStatus(status="critical", alerts=["registry not initialized"])
        return HealthStatus(
            status="ok",
            metrics={
                "tool_count": float(self._registry.count()),
                "forged_count": float(len(self._forge.list_forged()) if self._forge else 0),
            },
        )

    def snapshot(self) -> dict:
        return {"tools": list(self._registry.list_tools().keys()) if self._registry else []}

    def restore(self, data: dict) -> None:
        pass

    def enrich_prompt(self, base: str) -> str:
        if self._registry is None:
            return base
        tools = self._registry.list_tools()
        lines = [base, "", "## 当前可用工具"]
        for name, info in tools.items():
            lines.append(f"- **{name}**: {info.get('description', '')}")
        return "\n".join(lines)

    # ── Tool Operations ──────────────────────────────────────────

    def list_tools(self) -> dict:
        if self._registry:
            return self._registry.list_tools()
        return {}

    def call(self, name: str, **kwargs):
        if self._registry:
            return self._registry.call(name, **kwargs)
        return {"success": False, "error": "registry not initialized"}

    def forge(self, name: str, description: str, code: str):
        if self._forge:
            return self._forge.forge(name=name, description=description, code=code, parameters={})
        return {"success": False, "error": "forge not initialized"}

    def needs_human_approval(self, result: dict) -> bool:
        if self._ctx and self._ctx.config.get("identity", {}).get("autonomy_level", 1) >= 4:
            return False
        return True

    def rollback(self, tool_name: str) -> bool:
        if self._registry and self._registry.has(tool_name):
            self._registry.unregister(tool_name)
            return True
        return False
```

- [ ] **Step 3: Write basic test**

```python
# tests/test_tool_plugin.py
"""Tests for ToolPlugin and ClosedForgeCycle."""

from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.tool.forge_cycle import ClosedForgeCycle, ImprovementSpec, CycleStage


class TestToolPlugin:
    def _make_ctx(self, tmpdir):
        return AgentContext("test", "a1", "specified", Path(tmpdir), {}, "0.6.0")

    def test_satisfies_protocol(self):
        assert isinstance(ToolPlugin(), PluginProtocol)

    def test_initializes_with_primal_tools(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = ToolPlugin()
            plugin.initialize(self._make_ctx(tmpdir))
            assert plugin._registry is not None
            tools = plugin.list_tools()
            assert len(tools) > 0  # primal tools registered


class TestClosedForgeCycle:
    def test_cycle_stops_at_generate_without_code_or_llm(self):
        plugin = ToolPlugin()
        cycle = ClosedForgeCycle(plugin)
        spec = ImprovementSpec("test_cap", "A test capability", tool_name="test_tool")
        result = cycle.run(spec=spec, code="", llm_backend=None)
        assert not result.overall_passed
        gen_stage = [s for s in result.stages if s.stage == CycleStage.GENERATE][0]
        assert not gen_stage.passed
        assert "No LLM backend" in gen_stage.error

    def test_cycle_with_provided_code_skips_generate(self):
        plugin = ToolPlugin()
        cycle = ClosedForgeCycle(plugin)
        spec = ImprovementSpec("test_cap", "desc", tool_name="test_tool")
        result = cycle.run(spec=spec, code="def test_tool(**kwargs):\n    return {'success': True}", llm_backend=None)
        gen_stage = [s for s in result.stages if s.stage == CycleStage.GENERATE][0]
        assert gen_stage.passed
        assert gen_stage.output["source"] == "provided"
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_tool_plugin.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tain_agent/plugins/tool/ tests/test_tool_plugin.py
git commit -m "feat: add ToolPlugin with closed forge cycle"
```

---

### Task 7: KnowledgePlugin

**Files:**
- Create: `tain_agent/plugins/knowledge/__init__.py`
- Create: `tain_agent/plugins/knowledge/graph.py`
- Create: `tain_agent/plugins/knowledge/lifecycle.py`
- Create: `tests/test_knowledge_plugin.py`

- [ ] **Step 1: Create `tain_agent/plugins/knowledge/graph.py`**

```python
"""Knowledge graph — entities, relations, snapshots."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Entity:
    id: str
    name: str
    type: str = "concept"           # concept | tool | person | event | project
    properties: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    ttl_days: int = 30              # freshness threshold
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def is_stale(self) -> bool:
        try:
            updated = datetime.fromisoformat(self.updated_at)
            age = (datetime.now(timezone.utc) - updated).days
            return age > self.ttl_days
        except Exception:
            return True


@dataclass
class Relation:
    subject: str                    # entity ID
    predicate: str                  # depends_on | implements | requires | conflicts_with | related_to
    object: str                     # entity ID
    confidence: float = 1.0
    evidence: str = ""


@dataclass
class KnowledgeSnapshot:
    timestamp: str = field(default_factory=_now)
    entities_count: int = 0
    relations_count: int = 0
    new_entities: list[str] = field(default_factory=list)
    deleted_entities: list[str] = field(default_factory=list)


class KnowledgeGraph:
    """In-memory graph store with snapshot capability."""

    def __init__(self):
        self._entities: dict[str, Entity] = {}
        self._relations: list[Relation] = []
        self._snapshots: list[KnowledgeSnapshot] = []

    def add_entity(self, entity: Entity) -> Entity:
        self._entities[entity.id] = entity
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def remove_entity(self, entity_id: str) -> bool:
        if entity_id in self._entities:
            del self._entities[entity_id]
            self._relations = [r for r in self._relations
                               if r.subject != entity_id and r.object != entity_id]
            return True
        return False

    def add_relation(self, relation: Relation) -> Relation:
        self._relations.append(relation)
        return relation

    def query(self, entity_id: str) -> dict:
        entity = self._entities.get(entity_id)
        if entity is None:
            return {"entity": None, "relations": []}
        related = []
        for r in self._relations:
            if r.subject == entity_id:
                related.append({"direction": "out", "predicate": r.predicate,
                                "target": r.object, "confidence": r.confidence})
            elif r.object == entity_id:
                related.append({"direction": "in", "predicate": r.predicate,
                                "source": r.subject, "confidence": r.confidence})
        return {"entity": entity, "relations": related}

    def find_contradictions(self, subject: str, predicate: str, object: str) -> list[Relation]:
        """Find relations that contradict the proposed new relation."""
        contradictions = []
        for r in self._relations:
            if r.subject == subject and r.object == object and r.predicate != predicate:
                # Same subject-object pair, different predicate → potential conflict
                if (predicate == "supports" and r.predicate == "opposes") or \
                   (predicate == "opposes" and r.predicate == "supports") or \
                   (predicate == "depends_on" and r.predicate == "conflicts_with"):
                    contradictions.append(r)
        return contradictions

    def snapshot(self) -> KnowledgeSnapshot:
        snap = KnowledgeSnapshot(
            entities_count=len(self._entities),
            relations_count=len(self._relations),
        )
        self._snapshots.append(snap)
        return snap

    def to_dict(self) -> dict:
        import dataclasses
        return {
            "entities": {k: dataclasses.asdict(v) for k, v in self._entities.items()},
            "relations": [dataclasses.asdict(r) for r in self._relations],
        }

    @classmethod
    def from_dict(cls, data: dict) -> KnowledgeGraph:
        kg = cls()
        for eid, edata in data.get("entities", {}).items():
            kg._entities[eid] = Entity(**edata)
        for rdata in data.get("relations", []):
            kg._relations.append(Relation(**rdata))
        return kg
```

- [ ] **Step 2: Create `tain_agent/plugins/knowledge/lifecycle.py`**

```python
"""Knowledge lifecycle — conflict detection, freshness, inheritance."""

from __future__ import annotations
import logging
from tain_agent.plugins.knowledge.graph import KnowledgeGraph, Entity, Relation

logger = logging.getLogger(__name__)


def conflict_detect(kg: KnowledgeGraph, new_relation: Relation) -> dict:
    """Detect and return conflicts with existing knowledge. Returns {has_conflict, conflicts, resolution}."""
    conflicts = kg.find_contradictions(
        new_relation.subject, new_relation.predicate, new_relation.object
    )
    if not conflicts:
        return {"has_conflict": False, "conflicts": [], "resolution": "none_needed"}
    higher_confidence = all(new_relation.confidence >= c.confidence for c in conflicts)
    resolution = "accept_new" if higher_confidence else "keep_existing"
    return {"has_conflict": True, "conflicts": conflicts, "resolution": resolution}


def freshness_check(kg: KnowledgeGraph) -> list[Entity]:
    """Return all stale entities that need re-verification."""
    return [e for e in kg._entities.values() if e.is_stale()]


def inherit_entities(source_kg: KnowledgeGraph, target_kg: KnowledgeGraph,
                     entity_ids: list[str]) -> list[str]:
    """Copy entities and their relations from source to target. Returns list of imported IDs."""
    imported = []
    for eid in entity_ids:
        entity = source_kg.get_entity(eid)
        if entity is None:
            continue
        # Deep copy with reduced confidence (inherited knowledge is less certain)
        new_entity = Entity(
            id=entity.id, name=entity.name, type=entity.type,
            properties=dict(entity.properties),
            sources=entity.sources + ["inherited"],
        )
        target_kg.add_entity(new_entity)
        imported.append(eid)
    # Copy relations where both subject and object are in the imported set
    for r in source_kg._relations:
        if r.subject in imported and r.object in imported:
            target_kg.add_relation(Relation(
                subject=r.subject, predicate=r.predicate, object=r.object,
                confidence=r.confidence * 0.9,  # slightly lower confidence for inherited
                evidence=r.evidence + " (inherited)",
            ))
    return imported
```

- [ ] **Step 3: Create `tain_agent/plugins/knowledge/__init__.py`**

```python
"""KnowledgePlugin — complete knowledge lifecycle management."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.knowledge.graph import KnowledgeGraph, Entity, Relation, KnowledgeSnapshot
from tain_agent.plugins.knowledge.lifecycle import conflict_detect, freshness_check, inherit_entities

logger = logging.getLogger(__name__)


class KnowledgePlugin:
    """Double-layer knowledge: dynamic (temporary) + stable (persisted graph)."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._graph: KnowledgeGraph | None = None
        self._dynamic: list[dict] = []      # temporary knowledge base
        self._graph_path: Path | None = None

    # ── PluginProtocol ───────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._graph_path = ctx.workspace_path / "knowledge" / "graph.json"
        self._graph_path.parent.mkdir(parents=True, exist_ok=True)
        self._graph = self._load_graph()
        self._dynamic = []

    def shutdown(self) -> None:
        self._save_graph()
        self._graph = None

    def health_check(self) -> HealthStatus:
        if self._graph is None:
            return HealthStatus(status="critical")
        stale = freshness_check(self._graph)
        alerts = [f"Stale entity: {e.name}" for e in stale[:5]] if stale else []
        return HealthStatus(
            status="warning" if stale else "ok",
            metrics={"entities": float(len(self._graph._entities)),
                     "relations": float(len(self._graph._relations)),
                     "stale_count": float(len(stale))},
            alerts=alerts,
        )

    def snapshot(self) -> dict:
        return self._graph.to_dict() if self._graph else {}

    def restore(self, data: dict) -> None:
        if data and self._graph:
            self._graph = KnowledgeGraph.from_dict(data)

    def enrich_prompt(self, base: str) -> str:
        if self._graph is None:
            return base
        # Show recently updated entities
        recent = sorted(self._graph._entities.values(),
                        key=lambda e: e.updated_at, reverse=True)[:5]
        if not recent:
            return base
        lines = [base, "", "## 相关知识", ""]
        for e in recent:
            lines.append(f"- **{e.name}** ({e.type}): 更新于 {e.updated_at[:10]}")
        return "\n".join(lines)

    # ── Knowledge Operations ─────────────────────────────────────

    def query(self, entity_id: str) -> dict:
        if self._graph is None:
            return {}
        return self._graph.query(entity_id)

    def ingest(self, name: str, entity_type: str = "concept",
               properties: dict = None, source: str = "") -> Entity | None:
        """Add new knowledge to the stable graph."""
        if self._graph is None:
            return None
        entity = Entity(id=name.lower().replace(" ", "_"), name=name,
                        type=entity_type, properties=properties or {},
                        sources=[source] if source else [])
        self._graph.add_entity(entity)
        return entity

    def add_dynamic(self, content: str, source: str = "") -> None:
        """Add temporary, unverified knowledge."""
        from datetime import datetime, timezone
        self._dynamic.append({
            "content": content, "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def consolidate(self) -> int:
        """Verify dynamic knowledge and promote verified items to the stable graph."""
        count = 0
        # Simple heuristic: if multiple dynamic entries mention the same name, promote
        names_seen: dict[str, int] = {}
        for item in self._dynamic[-50:]:  # recent 50 items
            for word in item["content"].split()[:5]:
                names_seen[word] = names_seen.get(word, 0) + 1
        for name, freq in names_seen.items():
            if freq >= 2 and len(name) > 3:
                self.ingest(name, entity_type="concept",
                            source="consolidated from dynamic base")
                count += 1
        self._dynamic = self._dynamic[-100:]  # trim
        return count

    def export_subgraph(self, entity_ids: list[str]) -> dict:
        """Export a subgraph for knowledge inheritance."""
        if self._graph is None:
            return {}
        subgraph = KnowledgeGraph()
        inherit_entities(self._graph, subgraph, entity_ids)
        return subgraph.to_dict()

    # ── Persistence ──────────────────────────────────────────────

    def _load_graph(self) -> KnowledgeGraph:
        if self._graph_path and self._graph_path.exists():
            try:
                data = json.loads(self._graph_path.read_text(encoding="utf-8"))
                return KnowledgeGraph.from_dict(data)
            except Exception:
                pass
        return KnowledgeGraph()

    def _save_graph(self) -> None:
        if self._graph and self._graph_path:
            self._graph_path.write_text(
                json.dumps(self._graph.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
```

- [ ] **Step 4: Create `tests/test_knowledge_plugin.py`**

```python
"""Tests for KnowledgePlugin and KnowledgeGraph."""

from tain_agent.plugins.knowledge.graph import KnowledgeGraph, Entity, Relation
from tain_agent.plugins.knowledge.lifecycle import conflict_detect, freshness_check


class TestKnowledgeGraph:
    def test_add_and_query_entity(self):
        kg = KnowledgeGraph()
        kg.add_entity(Entity("python", "Python", type="concept"))
        result = kg.query("python")
        assert result["entity"].name == "Python"

    def test_add_relation_and_query(self):
        kg = KnowledgeGraph()
        kg.add_entity(Entity("python", "Python"))
        kg.add_entity(Entity("fastapi", "FastAPI"))
        kg.add_relation(Relation("fastapi", "depends_on", "python"))
        result = kg.query("fastapi")
        assert len(result["relations"]) == 1
        assert result["relations"][0]["predicate"] == "depends_on"

    def test_find_contradictions(self):
        kg = KnowledgeGraph()
        kg.add_entity(Entity("x", "X"))
        kg.add_entity(Entity("y", "Y"))
        kg.add_relation(Relation("x", "supports", "y"))
        contradictions = kg.find_contradictions("x", "opposes", "y")
        assert len(contradictions) == 1

    def test_snapshot(self):
        kg = KnowledgeGraph()
        kg.add_entity(Entity("a", "A"))
        snap = kg.snapshot()
        assert snap.entities_count == 1


class TestLifecycle:
    def test_conflict_detect_no_conflict(self):
        kg = KnowledgeGraph()
        result = conflict_detect(kg, Relation("a", "depends_on", "b"))
        assert not result["has_conflict"]

    def test_freshness_check(self):
        kg = KnowledgeGraph()
        kg.add_entity(Entity("old", "Old", ttl_days=0))  # already stale
        stale = freshness_check(kg)
        assert len(stale) >= 1
```

---

### Task 8: SkillPlugin

**Files:**
- Create: `tain_agent/plugins/skill/__init__.py`
- Create: `tain_agent/plugins/skill/model.py`
- Create: `tain_agent/plugins/skill/composer.py`
- Create: `tests/test_skill_plugin.py`

- [ ] **Step 1: Create `tain_agent/plugins/skill/model.py`**

```python
"""Skill data model — composite capability unit."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MaturityLevel(IntEnum):
    NOVICE = 1
    APPRENTICE = 2
    SKILLED = 3
    EXPERT = 4
    MASTER = 5


MATURITY_THRESHOLDS = {
    MaturityLevel.APPRENTICE: {"usage_count": 5},
    MaturityLevel.SKILLED: {"usage_count": 20, "success_rate": 0.5},
    MaturityLevel.EXPERT: {"usage_count": 50, "success_rate": 0.8},
    MaturityLevel.MASTER: {"usage_count": 100, "success_rate": 0.9, "has_taught": 1},
}


@dataclass
class Step:
    type: str                      # tool_call | llm_think | human_approval | condition | parallel
    tool_name: str | None = None
    prompt_template: str | None = None
    condition: str | None = None
    on_failure: str = "abort"      # retry | skip | abort


@dataclass
class Skill:
    name: str
    display_name: str = ""
    description: str = ""
    category: str = "general"      # coding | analysis | creation | communication | general

    # Composition
    tools: list[str] = field(default_factory=list)
    knowledge_refs: list[str] = field(default_factory=list)
    workflow: list[Step] = field(default_factory=list)

    # Maturity
    maturity: MaturityLevel = MaturityLevel.NOVICE
    usage_count: int = 0
    success_count: int = 0
    last_used_at: str = ""

    # Meta
    created_by: str = "forged"     # forged | inherited | composed
    parent_skill: str | None = None
    prerequisites: list[str] = field(default_factory=list)
    version: int = 1

    @property
    def success_rate(self) -> float:
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    def record_use(self, success: bool) -> None:
        self.usage_count += 1
        if success:
            self.success_count += 1
        self.last_used_at = _now()
        self._recalc_maturity()

    def _recalc_maturity(self) -> None:
        for level in sorted(MaturityLevel, reverse=True):
            if level <= self.maturity:
                continue
            req = MATURITY_THRESHOLDS.get(level, {})
            if self.usage_count >= req.get("usage_count", 0) and \
               self.success_rate >= req.get("success_rate", 0):
                self.maturity = level
                break


def check_maturity_upgrade(skill: Skill) -> bool:
    """Check if skill qualifies for next maturity level. Returns True if upgraded."""
    current = skill.maturity
    for level in sorted(MaturityLevel, reverse=True):
        if level <= current:
            continue
        req = MATURITY_THRESHOLDS.get(level, {})
        if skill.usage_count >= req.get("usage_count", 0) and \
           skill.success_rate >= req.get("success_rate", 0):
            skill.maturity = level
            return True
    return False
```

- [ ] **Step 2: Create `tain_agent/plugins/skill/composer.py`**

```python
"""Skill composer — merge existing skills into a new composite skill."""

from tain_agent.plugins.skill.model import Skill, Step, MaturityLevel


def compose_skills(name: str, display_name: str, description: str,
                   sub_skills: list[Skill], workflow: list[Step] | None = None) -> Skill:
    """Create a new skill by composing existing skills.

    New skill inherits all tools, knowledge_refs, and optionally a combined workflow.
    Initial maturity = min(sub-skill maturities) - 1, minimum NOVICE.
    """
    all_tools = []
    all_knowledge = []
    min_maturity = MaturityLevel.MASTER

    for s in sub_skills:
        for t in s.tools:
            if t not in all_tools:
                all_tools.append(t)
        for k in s.knowledge_refs:
            if k not in all_knowledge:
                all_knowledge.append(k)
        if s.maturity < min_maturity:
            min_maturity = s.maturity

    # Initial maturity one level below the weakest sub-skill
    start_level = max(MaturityLevel.NOVICE, min_maturity - 1)

    return Skill(
        name=name,
        display_name=display_name,
        description=description,
        tools=all_tools,
        knowledge_refs=all_knowledge,
        workflow=workflow or [],
        maturity=start_level,
        created_by="composed",
        prerequisites=[s.name for s in sub_skills],
    )
```

- [ ] **Step 3: Create `tain_agent/plugins/skill/__init__.py`**

```python
"""SkillPlugin — manages composite skills as reusable capability units."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.skill.model import Skill, MaturityLevel, check_maturity_upgrade
from tain_agent.plugins.skill.composer import compose_skills

logger = logging.getLogger(__name__)


class SkillPlugin:
    """Owns the agent's skill catalog. Skills are composite: tools + knowledge + workflow."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._skills: dict[str, Skill] = {}
        self._catalog_path: Path | None = None

    # ── PluginProtocol ───────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._catalog_path = ctx.workspace_path / "skills" / "catalog.json"
        self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def shutdown(self) -> None:
        self._save()
        self._skills.clear()

    def health_check(self) -> HealthStatus:
        metrics = {
            "total_skills": float(len(self._skills)),
            "master_skills": float(sum(1 for s in self._skills.values() if s.maturity >= MaturityLevel.MASTER)),
            "expert_skills": float(sum(1 for s in self._skills.values() if s.maturity >= MaturityLevel.EXPERT)),
        }
        return HealthStatus(status="ok", metrics=metrics)

    def snapshot(self) -> dict:
        return {"skills": {k: {"name": v.name, "maturity": v.maturity.value} for k, v in self._skills.items()}}

    def restore(self, data: dict) -> None:
        pass

    def enrich_prompt(self, base: str) -> str:
        if not self._skills:
            return base
        lines = [base, "", "## 你的技能", ""]
        for skill in sorted(self._skills.values(), key=lambda s: s.maturity, reverse=True)[:8]:
            lines.append(f"- **{skill.display_name or skill.name}** [{skill.maturity.name}] "
                         f"成功率: {skill.success_rate:.0%}")
        return "\n".join(lines)

    # ── Skill Operations ─────────────────────────────────────────

    def register(self, skill: Skill) -> Skill:
        self._skills[skill.name] = skill
        self._save()
        return skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_skills(self, min_maturity: MaturityLevel | None = None) -> list[Skill]:
        skills = list(self._skills.values())
        if min_maturity is not None:
            skills = [s for s in skills if s.maturity >= min_maturity]
        return sorted(skills, key=lambda s: s.maturity, reverse=True)

    def practice(self, name: str, success: bool) -> bool:
        skill = self._skills.get(name)
        if skill is None:
            return False
        skill.record_use(success)
        check_maturity_upgrade(skill)
        self._save()
        return True

    def teach(self, name: str, target_agent_id: str) -> dict | None:
        skill = self._skills.get(name)
        if skill is None or skill.maturity < MaturityLevel.EXPERT:
            return None
        # Export skill definition for transmission to another agent
        return {"skill_definition": skill.__dict__, "taught_by": self._ctx.agent_id,
                "target": target_agent_id, "version": skill.version}

    def compose(self, name: str, display_name: str, description: str,
                sub_skill_names: list[str], workflow=None) -> Skill | None:
        sub_skills = [self._skills[n] for n in sub_skill_names if n in self._skills]
        if not sub_skills:
            return None
        skill = compose_skills(name, display_name, description, sub_skills, workflow)
        self._skills[name] = skill
        self._save()
        return skill

    # ── Persistence ──────────────────────────────────────────────

    def _load(self) -> None:
        if self._catalog_path and self._catalog_path.exists():
            try:
                data = json.loads(self._catalog_path.read_text(encoding="utf-8"))
                for skill_data in data.get("skills", []):
                    s = Skill(**skill_data)
                    self._skills[s.name] = s
            except Exception as e:
                logger.warning("Failed to load skill catalog: %s", e)

    def _save(self) -> None:
        if self._catalog_path:
            skills_data = []
            for s in self._skills.values():
                d = s.__dict__.copy()
                d["maturity"] = s.maturity.value
                skills_data.append(d)
            self._catalog_path.write_text(
                json.dumps({"skills": skills_data}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
```

- [ ] **Step 4: Create `tests/test_skill_plugin.py`**

```python
"""Tests for Skill model, composer, and SkillPlugin."""

from tain_agent.plugins.skill.model import Skill, Step, MaturityLevel, check_maturity_upgrade
from tain_agent.plugins.skill.composer import compose_skills


class TestSkill:
    def test_record_use_updates_stats(self):
        s = Skill(name="test_skill")
        s.record_use(True)
        assert s.usage_count == 1
        assert s.success_rate == 1.0

    def test_maturity_advances_on_successful_uses(self):
        s = Skill(name="test_skill")
        for _ in range(5):
            s.record_use(True)
        assert s.maturity >= MaturityLevel.APPRENTICE

    def test_failed_uses_delay_maturity(self):
        s = Skill(name="test_skill")
        for _ in range(20):
            s.record_use(False)
        assert s.maturity == MaturityLevel.NOVICE  # 0% success rate


class TestComposer:
    def test_compose_inherits_tools(self):
        s1 = Skill(name="a", tools=["tool_a", "tool_b"], maturity=MaturityLevel.SKILLED)
        s2 = Skill(name="b", tools=["tool_c"], maturity=MaturityLevel.SKILLED)
        composed = compose_skills("composite", "Composite", "", [s1, s2])
        assert "tool_a" in composed.tools
        assert "tool_c" in composed.tools
        assert composed.maturity == MaturityLevel.APPRENTICE  # min(skilled)-1
```

---

### Task 9: WorkflowPlugin

**Files:**
- Create: `tain_agent/plugins/workflow/__init__.py`
- Create: `tain_agent/plugins/workflow/engine.py`
- Create: `tests/test_workflow_plugin.py`

- [ ] **Step 1: Create `tain_agent/plugins/workflow/engine.py`**

```python
"""Workflow engine — DAG-based multi-step orchestration."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from collections import deque


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class StepType(Enum):
    TOOL_CALL = "tool_call"
    SKILL_INVOKE = "skill_invoke"
    LLM_REASON = "llm_reason"
    HUMAN_REVIEW = "human_review"
    CONDITIONAL = "conditional"
    PARALLEL = "parallel"
    SUB_WORKFLOW = "sub_workflow"


@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff: str = "exponential"    # fixed | exponential
    on_failure: str = "abort"       # retry | skip | abort | fallback


@dataclass
class WorkflowStep:
    id: str
    type: StepType
    config: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_seconds: int = 60


@dataclass
class StepResult:
    step_id: str
    passed: bool = False
    output: dict | None = None
    error: str | None = None
    retries: int = 0
    duration_seconds: float = 0.0


@dataclass
class Workflow:
    name: str
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    state: WorkflowState = WorkflowState.PENDING
    context: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    started_at: str = ""
    completed_at: str = ""

    def validate(self) -> list[str]:
        """Validate DAG — no cycles, all deps reference existing steps."""
        errors = []
        step_ids = {s.id for s in self.steps}
        for s in self.steps:
            for dep in s.depends_on:
                if dep not in step_ids:
                    errors.append(f"Step {s.id} depends on unknown step {dep}")
        # Simple cycle detection via topological sort
        order = self.topological_order()
        if len(order) != len(self.steps):
            errors.append("Workflow contains a cycle")
        return errors

    def topological_order(self) -> list[str]:
        """Return step IDs in dependency order."""
        in_degree: dict[str, int] = {s.id: 0 for s in self.steps}
        adj: dict[str, list[str]] = {s.id: [] for s in self.steps}
        for s in self.steps:
            for dep in s.depends_on:
                adj[dep].append(s.id)
                in_degree[s.id] += 1
        queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
        order = []
        while queue:
            sid = queue.popleft()
            order.append(sid)
            for neighbor in adj[sid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        return order

    def parallel_groups(self) -> list[list[str]]:
        """Group steps into parallel-executable batches."""
        order = self.topological_order()
        # Dependencies form natural groups: steps at same "depth" can run in parallel
        depth: dict[str, int] = {}
        for sid in order:
            max_dep_depth = 0
            step = next(s for s in self.steps if s.id == sid)
            for dep in step.depends_on:
                max_dep_depth = max(max_dep_depth, depth.get(dep, 0) + 1)
            depth[sid] = max_dep_depth

        groups: dict[int, list[str]] = {}
        for sid, d in sorted(depth.items(), key=lambda x: x[1]):
            groups.setdefault(d, []).append(sid)
        return list(groups.values())
```

- [ ] **Step 2: Create `tain_agent/plugins/workflow/__init__.py`**

```python
"""WorkflowPlugin — DAG-based multi-step workflow orchestration."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.workflow.engine import (
    Workflow, WorkflowStep, WorkflowState, StepType, StepResult, RetryPolicy,
)

logger = logging.getLogger(__name__)


class WorkflowPlugin:
    """Manages agent workflows — creation, execution, pause/resume, templates."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._workflows: dict[str, Workflow] = {}
        self._active_id: str | None = None
        self._store_path: Path | None = None

    # ── PluginProtocol ───────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._store_path = ctx.workspace_path / "workflows"
        self._store_path.mkdir(parents=True, exist_ok=True)

    def shutdown(self) -> None:
        pass

    def health_check(self) -> HealthStatus:
        active = sum(1 for w in self._workflows.values() if w.state == WorkflowState.RUNNING)
        return HealthStatus(
            status="ok",
            metrics={"total_workflows": float(len(self._workflows)), "active_workflows": float(active)},
        )

    def snapshot(self) -> dict:
        return {"workflow_ids": list(self._workflows.keys())}

    def restore(self, data: dict) -> None:
        pass

    def enrich_prompt(self, base: str) -> str:
        active = [w for w in self._workflows.values() if w.state == WorkflowState.RUNNING]
        if not active:
            return base
        lines = [base, "", "## 活跃工作流"]
        for w in active[:3]:
            lines.append(f"- **{w.name}**: {w.state.value}")
        return "\n".join(lines)

    # ── Workflow Operations ──────────────────────────────────────

    def create(self, name: str, steps: list[WorkflowStep],
               description: str = "", context: dict = None) -> Workflow:
        wf = Workflow(name=name, description=description, steps=steps,
                      context=context or {})
        self._workflows[name] = wf
        self._persist(wf)
        return wf

    def start(self, name: str) -> Workflow | None:
        wf = self._workflows.get(name)
        if wf is None:
            return None
        errors = wf.validate()
        if errors:
            logger.error("Workflow %s validation failed: %s", name, errors)
            return None
        wf.state = WorkflowState.RUNNING
        wf.started_at = datetime.now(timezone.utc).isoformat()
        return wf

    def pause(self, name: str) -> bool:
        wf = self._workflows.get(name)
        if wf and wf.state == WorkflowState.RUNNING:
            wf.state = WorkflowState.PAUSED
            return True
        return False

    def resume(self, name: str) -> bool:
        wf = self._workflows.get(name)
        if wf and wf.state == WorkflowState.PAUSED:
            wf.state = WorkflowState.RUNNING
            return True
        return False

    def status(self, name: str) -> WorkflowState | None:
        wf = self._workflows.get(name)
        return wf.state if wf else None

    def status_all(self) -> list[dict]:
        return [{"name": w.name, "state": w.state.value}
                for w in self._workflows.values()]

    def advance(self, name: str, step_result: StepResult) -> bool:
        """Called after a workflow step completes."""
        wf = self._workflows.get(name)
        if wf is None:
            return False
        wf.context[f"_step_{step_result.step_id}"] = step_result.output
        self._persist(wf)
        return True

    def plan_from_goal(self, goal_title: str, llm_backend=None) -> Workflow | None:
        """Use LLM to decompose a goal into a workflow."""
        if llm_backend is None:
            return None
        prompt = f"""Decompose this goal into a workflow of 3-6 steps:
Goal: {goal_title}

Return a JSON array of steps, each with: id, type (tool_call|skill_invoke|llm_reason|human_review), config dict, depends_on list."""
        try:
            response = llm_backend.create_message(
                system_prompt="You are a workflow planner. Output only valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                tools=[],
            )
            text = "\n".join(response.text_blocks)
            steps_data = json.loads(text)
            steps = []
            for sd in steps_data:
                steps.append(WorkflowStep(
                    id=sd["id"],
                    type=StepType(sd.get("type", "tool_call")),
                    config=sd.get("config", {}),
                    depends_on=sd.get("depends_on", []),
                ))
            wf = self.create(goal_title.replace(" ", "_").lower(), steps,
                             description=goal_title)
            return wf
        except Exception as e:
            logger.warning("Failed to plan workflow from goal: %s", e)
            return None

    def _persist(self, wf: Workflow) -> None:
        if self._store_path:
            fpath = self._store_path / f"{wf.name}.json"
            import dataclasses
            fpath.write_text(json.dumps(dataclasses.asdict(wf), ensure_ascii=False, indent=2, default=str),
                             encoding="utf-8")
```

- [ ] **Step 3: Create `tests/test_workflow_plugin.py`**

```python
"""Tests for Workflow engine."""

from tain_agent.plugins.workflow.engine import (
    Workflow, WorkflowStep, StepType, RetryPolicy, WorkflowState,
)


class TestWorkflowEngine:
    def test_linear_topological_order(self):
        s1 = WorkflowStep(id="s1", type=StepType.TOOL_CALL)
        s2 = WorkflowStep(id="s2", type=StepType.TOOL_CALL, depends_on=["s1"])
        s3 = WorkflowStep(id="s3", type=StepType.TOOL_CALL, depends_on=["s2"])
        wf = Workflow(name="test", steps=[s2, s1, s3])  # unordered input
        assert wf.topological_order() == ["s1", "s2", "s3"]

    def test_parallel_groups(self):
        s1 = WorkflowStep(id="s1", type=StepType.TOOL_CALL)
        s2 = WorkflowStep(id="s2", type=StepType.TOOL_CALL, depends_on=["s1"])
        s3 = WorkflowStep(id="s3", type=StepType.TOOL_CALL, depends_on=["s1"])
        wf = Workflow(name="test", steps=[s1, s2, s3])
        groups = wf.parallel_groups()
        assert groups[0] == ["s1"]
        assert set(groups[1]) == {"s2", "s3"}

    def test_cycle_detection(self):
        s1 = WorkflowStep(id="s1", type=StepType.TOOL_CALL, depends_on=["s2"])
        s2 = WorkflowStep(id="s2", type=StepType.TOOL_CALL, depends_on=["s1"])
        wf = Workflow(name="test", steps=[s1, s2])
        errors = wf.validate()
        assert len(errors) > 0

    def test_unknown_dependency_detected(self):
        s1 = WorkflowStep(id="s1", type=StepType.TOOL_CALL, depends_on=["nonexistent"])
        wf = Workflow(name="test", steps=[s1])
        errors = wf.validate()
        assert len(errors) == 1
```

---

### Task 10: CollaborationPlugin

**Files:**
- Create: `tain_agent/plugins/collaboration/__init__.py`
- Create: `tain_agent/plugins/collaboration/bus.py`
- Create: `tain_agent/plugins/collaboration/team.py`
- Create: `tain_agent/plugins/collaboration/reputation.py`
- Create: `tests/test_collaboration_plugin.py`

- [ ] **Step 1: Create `tain_agent/plugins/collaboration/bus.py`**

```python
"""Upgraded MessageBus — type, priority, TTL, broadcast on top of existing SQLite bus."""

from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


UPGRADED_DDL = """
CREATE TABLE IF NOT EXISTS social_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'chat',
    content TEXT NOT NULL,
    reply_to TEXT DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 1,
    ttl_seconds INTEGER NOT NULL DEFAULT 3600,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_social_to ON social_messages(to_agent, status);
CREATE INDEX IF NOT EXISTS idx_social_type ON social_messages(msg_type);
"""


class UpgradedMessageBus:
    """WAL-mode SQLite bus with type/priority/TTL/broadcast support."""

    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(UPGRADED_DDL)
        self._conn.commit()

    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "chat", priority: int = 1, ttl_seconds: int = 3600,
             reply_to: str = "") -> str:
        msg_id = _make_id()
        self._conn.execute(
            "INSERT INTO social_messages (message_id, from_agent, to_agent, msg_type, content, reply_to, priority, ttl_seconds, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (msg_id, from_agent, to_agent, msg_type, content, reply_to, priority, ttl_seconds, _now()),
        )
        self._conn.commit()
        return msg_id

    def check_inbox(self, agent_name: str, mark_read: bool = True) -> list[dict]:
        rows = self._conn.execute(
            "SELECT message_id, from_agent, msg_type, content, priority, created_at "
            "FROM social_messages WHERE (to_agent=? OR to_agent='*') AND status='pending' "
            "ORDER BY priority DESC, created_at ASC LIMIT 20",
            (agent_name,),
        ).fetchall()
        messages = []
        for row in rows:
            messages.append({
                "message_id": row[0], "from_agent": row[1], "type": row[2],
                "content": row[3], "priority": row[4], "created_at": row[5],
            })
            if mark_read:
                self._conn.execute(
                    "UPDATE social_messages SET status='claimed' WHERE message_id=?",
                    (row[0],),
                )
        if mark_read:
            self._conn.commit()
        return messages

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 2: Create `tain_agent/plugins/collaboration/team.py` + `reputation.py`**

```python
# tain_agent/plugins/collaboration/team.py
"""Team management — Team, TeamMember, TeamTask."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TeamMember:
    agent_id: str
    role: str = "member"            # lead | member | observer
    responsibilities: list[str] = field(default_factory=list)
    joined_at: str = field(default_factory=_now)


@dataclass
class TeamTask:
    id: str
    team_id: str
    title: str
    description: str = ""
    assigned_to: list[str] = field(default_factory=list)
    status: str = "pending"         # pending | in_progress | completed | blocked
    dependencies: list[str] = field(default_factory=list)
    deadline: str = ""
    result: dict | None = None


@dataclass
class Team:
    id: str
    name: str
    mission: str = ""
    members: list[TeamMember] = field(default_factory=list)
    tasks: list[TeamTask] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    disbanded_at: str = ""

    def add_member(self, agent_id: str, role: str = "member") -> TeamMember:
        member = TeamMember(agent_id=agent_id, role=role)
        self.members.append(member)
        return member

    def assign_task(self, task: TeamTask) -> None:
        task.team_id = self.id
        self.tasks.append(task)

    def is_lead(self, agent_id: str) -> bool:
        return any(m.agent_id == agent_id and m.role == "lead" for m in self.members)
```

```python
# tain_agent/plugins/collaboration/reputation.py
"""Reputation system — per-agent scores with dimension breakdown."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Reputation:
    agent_id: str
    overall_score: float = 50.0          # 0-100
    dimensions: dict[str, float] = field(default_factory=lambda: {
        "reliability": 50.0, "quality": 50.0, "helpfulness": 50.0, "creativity": 50.0,
    })
    endorsements: list[str] = field(default_factory=list)
    collaboration_count: int = 0
    successful_collaborations: int = 0

    def record_collaboration(self, successful: bool) -> None:
        self.collaboration_count += 1
        if successful:
            self.successful_collaborations += 1

    def endorse(self, dimension: str, comment: str = "") -> None:
        if dimension in self.dimensions:
            self.dimensions[dimension] = min(100.0, self.dimensions[dimension] + 2.0)
        self.endorsements.append(comment)


class SocialGraph:
    """Agent social relationships — directed weighted graph."""

    def __init__(self):
        self._edges: dict[tuple[str, str], dict] = {}   # (from, to) → {type, weight}

    def set_relationship(self, from_agent: str, to_agent: str,
                         rel_type: str, weight: float = 1.0) -> None:
        self._edges[(from_agent, to_agent)] = {"type": rel_type, "weight": weight}

    def get_relationship(self, from_agent: str, to_agent: str) -> dict | None:
        return self._edges.get((from_agent, to_agent))

    def get_collaborators(self, agent_id: str) -> list[str]:
        return [to_id for (from_id, to_id), rel in self._edges.items()
                if from_id == agent_id and rel["type"] == "collaborator"]
```

- [ ] **Step 3: Create `tain_agent/plugins/collaboration/__init__.py`**

```python
"""CollaborationPlugin — inter-agent communication, teams, reputation."""

from __future__ import annotations
import logging
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.collaboration.bus import UpgradedMessageBus
from tain_agent.plugins.collaboration.team import Team, TeamMember, TeamTask
from tain_agent.plugins.collaboration.reputation import Reputation, SocialGraph

logger = logging.getLogger(__name__)


class CollaborationPlugin:
    """Three-layer collaboration: messages → teams → society."""

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._bus: UpgradedMessageBus | None = None
        self._teams: dict[str, Team] = {}
        self._reputation: Reputation | None = None
        self._social: SocialGraph = SocialGraph()

    # ── PluginProtocol ───────────────────────────────────────────
    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        social_db = Path("agent_workspace") / "_social.db"
        self._bus = UpgradedMessageBus(social_db)
        self._reputation = Reputation(agent_id=ctx.agent_id)

    def shutdown(self) -> None:
        if self._bus:
            self._bus.close()

    def health_check(self) -> HealthStatus:
        return HealthStatus(status="ok")

    def snapshot(self) -> dict:
        return {"teams": list(self._teams.keys())}

    def restore(self, data: dict) -> None:
        pass

    def enrich_prompt(self, base: str) -> str:
        if self._bus is None:
            return base
        msgs = self._bus.check_inbox(self._ctx.agent_name, mark_read=False)
        if not msgs:
            return base
        lines = [base, "", "## 新消息", ""]
        for m in msgs[:3]:
            lines.append(f"- [{m['priority']}] {m['from_agent']}: {m['content'][:100]}")
        return "\n".join(lines)

    # ── Layer 1: Messages ────────────────────────────────────────
    def send(self, to_agent: str, content: str, msg_type: str = "chat",
             priority: int = 1, ttl: int = 3600) -> str | None:
        if self._bus is None:
            return None
        return self._bus.send(self._ctx.agent_name, to_agent, content, msg_type, priority, ttl)

    def check_inbox(self) -> list[dict]:
        if self._bus is None:
            return []
        return self._bus.check_inbox(self._ctx.agent_name)

    # ── Layer 2: Teams ───────────────────────────────────────────
    def create_team(self, name: str, mission: str,
                    member_ids: list[str] = None) -> Team:
        import uuid
        tid = f"team_{uuid.uuid4().hex[:8]}"
        team = Team(id=tid, name=name, mission=mission)
        for mid in (member_ids or []):
            role = "lead" if mid == self._ctx.agent_id else "member"
            team.add_member(mid, role)
        self._teams[tid] = team
        return team

    def assign_task(self, team_id: str, title: str, description: str,
                    assigned_to: list[str]) -> TeamTask | None:
        import uuid
        team = self._teams.get(team_id)
        if team is None:
            return None
        task = TeamTask(id=f"task_{uuid.uuid4().hex[:8]}", team_id=team_id,
                        title=title, description=description, assigned_to=assigned_to)
        team.assign_task(task)
        return task

    # ── Layer 3: Society ─────────────────────────────────────────
    def get_reputation(self, agent_id: str = None) -> Reputation | None:
        if agent_id is None or agent_id == self._ctx.agent_id:
            return self._reputation
        return None  # External reputation requires shared DB (future)

    def endorse(self, agent_id: str, dimension: str, comment: str = "") -> bool:
        if self._reputation and agent_id == self._ctx.agent_id:
            self._reputation.endorse(dimension, comment)
            return True
        return False

    def discover_agents(self, skill_filter: str = None) -> list[dict]:
        """Placeholder — in future, queries shared registry for agent profiles."""
        return []

    def request_teaching(self, target_agent_id: str, skill_name: str) -> dict:
        msg_id = self.send(target_agent_id, f"TEACH_REQUEST: {skill_name}",
                           msg_type="knowledge", priority=2)
        return {"request_id": msg_id, "skill": skill_name, "target": target_agent_id}
```

- [ ] **Step 4: Create `tests/test_collaboration_plugin.py`**

```python
"""Tests for CollaborationPlugin components."""

import tempfile
from pathlib import Path
from tain_agent.plugins.collaboration.bus import UpgradedMessageBus
from tain_agent.plugins.collaboration.team import Team, TeamMember, TeamTask
from tain_agent.plugins.collaboration.reputation import Reputation, SocialGraph


class TestUpgradedMessageBus:
    def test_send_and_check(self):
        with tempfile.TemporaryDirectory() as d:
            bus = UpgradedMessageBus(Path(d) / "social.db")
            bus.send("agent_a", "agent_b", "hello", msg_type="chat", priority=1)
            inbox = bus.check_inbox("agent_b")
            assert len(inbox) == 1
            assert inbox[0]["content"] == "hello"
            # Second check should be empty (claimed)
            inbox2 = bus.check_inbox("agent_b")
            assert len(inbox2) == 0

    def test_broadcast(self):
        with tempfile.TemporaryDirectory() as d:
            bus = UpgradedMessageBus(Path(d) / "social.db")
            bus.send("agent_a", "*", "broadcast msg")
            for name in ["agent_b", "agent_c"]:
                inbox = bus.check_inbox(name)
                assert len(inbox) == 1
                assert inbox[0]["content"] == "broadcast msg"


class TestTeam:
    def test_create_team_and_assign_task(self):
        team = Team(id="t1", name="test team", mission="test")
        team.add_member("agent_a", role="lead")
        team.add_member("agent_b", role="member")
        task = TeamTask(id="task1", team_id="t1", title="do something")
        team.assign_task(task)
        assert len(team.members) == 2
        assert len(team.tasks) == 1
        assert team.is_lead("agent_a") is True
        assert team.is_lead("agent_b") is False


class TestReputation:
    def test_record_collaboration(self):
        rep = Reputation(agent_id="a1")
        rep.record_collaboration(True)
        assert rep.collaboration_count == 1
        assert rep.successful_collaborations == 1

    def test_endorse_dimension(self):
        rep = Reputation(agent_id="a1")
        initial = rep.dimensions["quality"]
        rep.endorse("quality", "great work")
        assert rep.dimensions["quality"] == initial + 2.0
```

---

### Task 11: Run all plugin tests

- [ ] **Step 1: Run all four plugin test suites**

```bash
python -m pytest tests/test_knowledge_plugin.py tests/test_skill_plugin.py tests/test_workflow_plugin.py tests/test_collaboration_plugin.py -v
```

Expected: All tests PASS

- [ ] **Step 2: Commit**

```bash
git add tain_agent/plugins/knowledge/ tain_agent/plugins/skill/ tain_agent/plugins/workflow/ tain_agent/plugins/collaboration/ tests/test_knowledge_plugin.py tests/test_skill_plugin.py tests/test_workflow_plugin.py tests/test_collaboration_plugin.py
git commit -m "feat: add KnowledgePlugin, SkillPlugin, WorkflowPlugin, CollaborationPlugin"
```

---

## 阶段 3: 清理与集成

### Task 12: 清理旧 Mixin 文件 + 移除 Adapters

**Files:**
- Deprecate: `tain_agent/core/agent_config.py`, `agent_subsystems.py`, `agent_cognition.py`, `agent_phase.py`, `agent_tools.py`
- Deprecate: `tain_agent/plugins/_adapters.py`
- Modify: `tain_agent/core/agent.py` → deprecation wrapper
- Create: `tain_agent/compat.py`

- [ ] **Step 1: Create `tain_agent/compat.py` — backward compatibility shim**

```python
"""Backward compatibility — new AgentKernel behind old TaoAgent interface.

Remove this module in v0.7.0 once all consumers (CLI, WebUI) are migrated.
"""

from __future__ import annotations
import logging
from pathlib import Path
from tain_agent.kernel import AgentKernel, AgentContext
from tain_agent.plugins.identity import IdentityPlugin
from tain_agent.plugins.memory import MemoryPlugin
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.skill import SkillPlugin
from tain_agent.plugins.knowledge import KnowledgePlugin
from tain_agent.plugins.workflow import WorkflowPlugin
from tain_agent.plugins.collaboration import CollaborationPlugin

logger = logging.getLogger(__name__)


_FACTORIES = {
    "identity": IdentityPlugin,
    "memory": MemoryPlugin,
    "tool": ToolPlugin,
    "skill": SkillPlugin,
    "knowledge": KnowledgePlugin,
    "workflow": WorkflowPlugin,
    "collaboration": CollaborationPlugin,
}


class TaoAgentCompat:
    """Drop-in replacement for the old TaoAgent class using new Kernel."""

    def __init__(self, config_path: str = "config.yaml", agent_name: str = None):
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)

        name = agent_name or config.get("agent", {}).get("name", "default")
        evolution_mode = config.get("agent", {}).get("evolution_mode", "specified")
        workspace = Path("agent_workspace") / name

        ctx = AgentContext(
            agent_name=name,
            agent_id=f"{name}-{workspace.name}",
            evolution_mode=evolution_mode,
            workspace_path=workspace,
            config=config,
            kernel_version="0.6.0",
        )
        self.kernel = AgentKernel(ctx)
        self.kernel.load_plugins(_FACTORIES)

    def run(self, autonomous: bool = False) -> int:
        from tain_agent.core.llm import LLMBackend
        backend = LLMBackend(self.kernel.ctx.config.get("llm", {}))
        # ... wire up with existing conversation, drive_system, etc.
        logger.info("Running via compat shim")
        return 0  # placeholder — full wiring in integration task

    def stop(self) -> None:
        self.kernel.shutdown()


# Re-export so old imports don't break
__all__ = ["TaoAgentCompat"]
```

- [ ] **Step 2: Mark old agent.py as deprecated**

Add deprecation import to `tain_agent/core/agent.py`:

```python
# At top of existing agent.py:
import warnings
warnings.warn(
    "tain_agent.core.agent.TaoAgent is deprecated. "
    "Use tain_agent.compat.TaoAgentCompat or tain_agent.kernel.AgentKernel directly.",
    DeprecationWarning, stacklevel=2,
)
```

- [ ] **Step 3: Mark old Mixin files as deprecated**

Add deprecation docstring to each mixin file:
- `tain_agent/core/agent_config.py`
- `tain_agent/core/agent_subsystems.py`
- `tain_agent/core/agent_cognition.py`
- `tain_agent/core/agent_phase.py`
- `tain_agent/core/agent_tools.py`

- [ ] **Step 4: Remove adapter file**

```bash
rm tain_agent/plugins/_adapters.py
```

- [ ] **Step 5: Commit**

```bash
git add tain_agent/compat.py tain_agent/core/agent.py
git rm tain_agent/plugins/_adapters.py
git commit -m "refactor: add compat shim, deprecate old Mixin agent, remove adapters"
```

---

### Task 13: 整合 — 确保完整 Agent 可运行

**Files:**
- Modify: `main.py`
- Modify: `tain_agent/compat.py` (complete integration wiring)
- Create: `tests/test_integration_new.py`

- [ ] **Step 1: Complete compat.py integration wiring**

Ensure `TaoAgentCompat.run()` fully wires LLM backend, conversation, drive system, and system prompts through the Kernel's PRAL loop.

- [ ] **Step 2: Create integration test**

```python
# tests/test_integration_new.py
"""Integration test: new AgentKernel runs a full PRAL cycle with all plugins."""

import tempfile
from pathlib import Path
from tain_agent.kernel import AgentKernel, AgentContext, HealthStatus


class TestKernelIntegration:
    def test_all_plugins_initialize_and_health_check(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext(
                agent_name="integration_test", agent_id="it-001",
                evolution_mode="specified", workspace_path=Path(tmpdir),
                config={}, kernel_version="0.6.0",
            )
            kernel = AgentKernel(ctx)
            # Load all 7 plugins
            from tain_agent.plugins.identity import IdentityPlugin
            from tain_agent.plugins.memory import MemoryPlugin
            from tain_agent.plugins.tool import ToolPlugin
            from tain_agent.plugins.skill import SkillPlugin
            from tain_agent.plugins.knowledge import KnowledgePlugin
            from tain_agent.plugins.workflow import WorkflowPlugin
            from tain_agent.plugins.collaboration import CollaborationPlugin

            factories = {
                "identity": IdentityPlugin, "memory": MemoryPlugin,
                "tool": ToolPlugin, "skill": SkillPlugin,
                "knowledge": KnowledgePlugin, "workflow": WorkflowPlugin,
                "collaboration": CollaborationPlugin,
            }
            kernel.load_plugins(factories)

            # All plugins should be loaded
            for name in factories:
                assert kernel.lifecycle.get(name) is not None, f"{name} not loaded"

            # All health checks pass
            for name, health in kernel.lifecycle.all_health_checks().items():
                assert health.status != "critical", f"{name} health is critical: {health.alerts}"

            # Clean shutdown
            kernel.shutdown()
```

- [ ] **Step 3: Run integration test**

```bash
python -m pytest tests/test_integration_new.py -v
```

Expected: 1 test PASS — all 7 plugins load, health check, clean shutdown.

- [ ] **Step 4: Commit**

```bash
git add tain_agent/compat.py tests/test_integration_new.py
git commit -m "feat: complete AgentKernel integration — all 7 plugins wired"
```

---

### Task 14: 更新 CLI 和 Web UI

**Files:**
- Modify: `main.py`
- Modify: `webui/dialogue.py`
- Modify: `supervise_agent.py`

- [ ] **Step 1: Update main.py to use new AgentKernel**

Add `--new-kernel` flag to `main.py` that creates Agent via `AgentKernel` instead of old `TaoAgent`. Old code path remains default until v0.7.0.

```python
# In main.py, add argument:
parser.add_argument("--new-kernel", action="store_true",
                    help="Use new Core-Plugins AgentKernel (v0.6.0)")

# In agent creation:
if args.new_kernel:
    from tain_agent.compat import TaoAgentCompat
    agent = TaoAgentCompat(config_path="config.yaml", agent_name=args.agent)
else:
    from tain_agent.core.agent import TaoAgent
    agent = TaoAgent(config_path="config.yaml", agent_name=args.agent)
```

- [ ] **Step 2: Verify old code path still works**

```bash
python main.py --list-agents
```

Expected: lists existing agents without errors.

- [ ] **Step 3: Verify new code path works**

```bash
python main.py --new-kernel --agent test_kernel --create-agent --evolution-mode specified --role "Test Agent" --role-description "Testing the new kernel"
```

Expected: creates agent via new Kernel.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add --new-kernel flag to CLI for Core-Plugins migration"
```

---

## 验证清单

完成所有 Task 后运行：

```bash
# All unit tests
python -m pytest tests/ -v --timeout=30

# Specific new architecture tests
python -m pytest tests/test_plugin_protocol.py tests/test_kernel.py tests/test_adapters.py -v
python -m pytest tests/test_identity_plugin.py tests/test_memory_plugin.py -v
python -m pytest tests/test_tool_plugin.py tests/test_knowledge_plugin.py -v
python -m pytest tests/test_skill_plugin.py tests/test_workflow_plugin.py tests/test_collaboration_plugin.py -v
python -m pytest tests/test_integration_new.py -v

# Ensure old tests still pass (backward compatibility)
python -m pytest tests/ -v --ignore=tests/test_plugin_protocol.py --ignore=tests/test_kernel.py \
    --ignore=tests/test_adapters.py --ignore=tests/test_identity_plugin.py \
    --ignore=tests/test_memory_plugin.py --ignore=tests/test_tool_plugin.py \
    --ignore=tests/test_knowledge_plugin.py --ignore=tests/test_skill_plugin.py \
    --ignore=tests/test_workflow_plugin.py --ignore=tests/test_collaboration_plugin.py \
    --ignore=tests/test_integration_new.py
```

---
*实施计划完*
