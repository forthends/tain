# Architecture Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete AgentKernel architecture migration — remove old TaoAgent + 6 Mixins + compat layer, make AgentKernel the sole entry point.

**Architecture:** Fill 4 Plugin capability gaps (Forge action param, GoalManager, Memory session interface, Personality in IdentityPlugin), migrate 6 consumers (main.py, webui, acp, dialogue.py, chat.py, agent_factory), then delete 9 old files (~2788 lines).

**Tech Stack:** Python 3.12+, pytest, AgentKernel/PluginProtocol

---

## File Structure

### Created files
| File | Responsibility |
|------|---------------|
| `kernel/factories.py` | STANDARD_FACTORIES dict — 7 Plugin factory mapping |
| `kernel/prompts.py` | System prompts migrated from bootstrap.py |
| `plugins/knowledge/goal_manager.py` | GoalManager — create/complete/list goals, persist to goals.json |

### Modified files
| File | Change |
|------|--------|
| `plugins/tool/__init__.py` | Add `list_forged()`, `get_sandbox_allowlist()`; ensure `forge()` action param |
| `plugins/knowledge/__init__.py` | Add `goals` property exposing GoalManager |
| `plugins/identity/__init__.py` | Add `personality` property with `get_context_for_prompt()`, `introspect()` |
| `plugins/memory/__init__.py` | Add `session_memory` property |
| `main.py` | Replace TaoAgent import with AgentKernel; inline LLM/conversation/drives creation |
| `webui/agent_cache.py` | Replace TaoAgent with AgentKernel caching |
| `acp/server.py` | Replace per-request TaoAgent with session-scoped AgentKernel |
| `core/dialogue.py` | Replace agent.* attribute access with lifecycle.get() Plugin queries |
| `core/chat.py` | Replace hasattr checks with lifecycle.get() calls |

### Deleted files
| File | Reason |
|------|--------|
| `core/agent.py` | Deprecated, replaced by AgentKernel |
| `core/agent_config.py` | Mixin, replaced by AgentContext |
| `core/agent_subsystems.py` | Mixin, replaced by LifecycleManager.load() |
| `core/agent_cognition.py` | Mixin, replaced by PRALLoop |
| `core/agent_phase.py` | Mixin, replaced by PRALLoop phase logic |
| `core/agent_tools.py` | Mixin, replaced by ToolPlugin |
| `core/agent_protocols.py` | Protocol definitions, no longer referenced |
| `core/bootstrap.py` | Tool closure registry, replaced by Plugin-native implementations |
| `compat.py` | Temporary compat layer, mission complete |

### Untouched files
| File | Why |
|------|-----|
| `core/conversation.py` | Interface unchanged, used by PRAL loop |
| `core/llm.py` | LLMBackend, stable interface |
| `core/drives.py` | DriveSystem, used by PRAL loop |
| `core/agent_factory.py` | Workspace management, no TaoAgent dependency — retained |
| `core/session_memory.py` | Wraps memory, dialogue.py uses it |

---

### Task 1: ToolPlugin — add list_forged() and get_sandbox_allowlist()

**Files:**
- Read: `tain_agent/plugins/tool/__init__.py`
- Read: `tain_agent/tools/forge.py` (for ToolForge API surface)
- Modify: `tain_agent/plugins/tool/__init__.py`
- Test: `tests/test_tool_plugin.py`

- [ ] **Step 1: Write failing tests for new ToolPlugin methods**

```python
# Add to tests/test_tool_plugin.py

def test_list_forged_returns_forged_tools(tool_plugin, agent_context):
    """list_forged() returns dict of tools created by forge."""
    tool_plugin.initialize(agent_context)
    result = tool_plugin.list_forged()
    assert isinstance(result, dict)
    # Initially empty — no tools forged yet
    assert result == {}


def test_get_sandbox_allowlist_returns_list(tool_plugin, agent_context):
    """get_sandbox_allowlist() returns the current sandbox allowlist."""
    tool_plugin.initialize(agent_context)
    allowlist = tool_plugin.get_sandbox_allowlist()
    assert isinstance(allowlist, list)


def test_forge_action_param_supports_update(tool_plugin, agent_context, tmp_path):
    """forge() with action='update' updates an existing forged tool."""
    tool_plugin.initialize(agent_context)
    # Forge a tool first
    code = "def hello(): return 'hello'"
    r1 = tool_plugin.forge("test_tool", "A test tool", code, {"action": "create"})
    assert r1.get("success") is True
    # Update it
    code2 = "def hello(): return 'updated'"
    r2 = tool_plugin.forge("test_tool", "Updated test tool", code2, {"action": "update"})
    assert r2.get("success") is True


def test_rollback_removes_forged_tool(tool_plugin, agent_context):
    """rollback() removes a forged tool."""
    tool_plugin.initialize(agent_context)
    code = "def temp_tool(): return 'temp'"
    tool_plugin.forge("temp_tool", "Temporary", code, {"action": "create"})
    assert "temp_tool" in tool_plugin.list_forged()
    result = tool_plugin.rollback("temp_tool")
    assert result.get("success") is True
    assert "temp_tool" not in tool_plugin.list_forged()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tool_plugin.py::test_list_forged_returns_forged_tools tests/test_tool_plugin.py::test_get_sandbox_allowlist_returns_list tests/test_tool_plugin.py::test_forge_action_param_supports_update tests/test_tool_plugin.py::test_rollback_removes_forged_tool -v`
Expected: FAIL with AttributeError

- [ ] **Step 3: Implement list_forged() and get_sandbox_allowlist() on ToolPlugin**

```python
# In tain_agent/plugins/tool/__init__.py, add after rollback() method:

    def list_forged(self) -> dict:
        """Return all forged tools and their metadata."""
        if self._forge is None:
            return {}
        return dict(self._forge._forged_tools)

    def get_sandbox_allowlist(self) -> list:
        """Return the current sandbox import/API allowlist."""
        if self._forge is None:
            return []
        return list(self._forge._sandbox_allowlist) if hasattr(self._forge, '_sandbox_allowlist') else []
```

- [ ] **Step 4: Update forge() method to handle action parameter**

```python
# In ToolPlugin.forge(), replace the method body:
    def forge(
        self,
        name: str,
        description: str,
        code: str,
        parameters: dict | None = None,
    ) -> dict:
        """Forge a new tool from source code through the safety sandbox.
        
        Args:
            name: Tool name.
            description: Human-readable description.
            code: Python source code for the tool function.
            parameters: Optional dict with 'action' key:
                - "create" (default): Create a new tool
                - "update": Update an existing forged tool
                - "rollback": Remove a forged tool
        """
        if self._forge is None:
            return {"success": False, "error": "forge not initialized"}
        
        action = (parameters or {}).get("action", "create")
        
        if action == "rollback":
            return self._forge.remove_forged(name)
        
        if action == "update":
            # Remove old version, forge new version
            if name in self._forge._forged_tools:
                self._forge.remove_forged(name)
        
        return self._forge.forge(
            name=name,
            description=description,
            code=code,
            parameters=parameters,
        )
```

- [ ] **Step 5: Register tool.forge route in AgentKernel dispatch**

```python
# In AgentKernel._build_routes(), verify this line exists (it should already):
#   if hasattr(tp, "forge"):
#       routes["tool.forge"] = tp.forge
# Also add list_forged and sandbox_allowlist routes:
        if tp:
            if hasattr(tp, "call"):
                routes["tool.call"] = tp.call
            if hasattr(tp, "forge"):
                routes["tool.forge"] = tp.forge
            if hasattr(tp, "list_forged"):
                routes["tool.list_forged"] = tp.list_forged
            if hasattr(tp, "get_sandbox_allowlist"):
                routes["tool.get_sandbox_allowlist"] = tp.get_sandbox_allowlist
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_tool_plugin.py -v`
Expected: All tool plugin tests PASS

- [ ] **Step 7: Commit**

```bash
git add tain_agent/plugins/tool/__init__.py tain_agent/kernel/__init__.py tests/test_tool_plugin.py
git commit -m "feat(tool-plugin): add list_forged, get_sandbox_allowlist, forge action param"
```

---

### Task 2: KnowledgePlugin — add GoalManager sub-component

**Files:**
- Create: `tain_agent/plugins/knowledge/goal_manager.py`
- Modify: `tain_agent/plugins/knowledge/__init__.py`
- Test: `tests/test_knowledge_plugin.py`

- [ ] **Step 1: Write GoalManager class**

```python
# tain_agent/plugins/knowledge/goal_manager.py
"""GoalManager — agent goal tracking with JSON persistence."""

from __future__ import annotations
import json
import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


class Goal:
    """A single agent goal."""
    def __init__(self, goal_id: str, description: str, success_criteria: str,
                 status: str = "active"):
        self.id = goal_id
        self.description = description
        self.success_criteria = success_criteria
        self.status = status  # "active" | "completed" | "abandoned"
        self.completed_at: str | None = None
        self.summary: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "status": self.status,
            "completed_at": self.completed_at,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        g = cls(d["id"], d["description"], d["success_criteria"], d.get("status", "active"))
        g.completed_at = d.get("completed_at")
        g.summary = d.get("summary", "")
        return g


class GoalManager:
    """Manages agent goals with JSON persistence on disk."""

    def __init__(self, persist_path: Path | None = None):
        self._goals: dict[str, Goal] = {}
        self._persist_path = persist_path

    def initialize(self, persist_path: Path) -> None:
        self._persist_path = persist_path
        self._load()

    def create(self, description: str, success_criteria: str) -> Goal:
        """Create a new active goal. Returns the Goal object."""
        goal_id = f"goal_{uuid.uuid4().hex[:8]}"
        goal = Goal(goal_id, description, success_criteria)
        self._goals[goal_id] = goal
        self._save()
        logger.info("Goal created: %s — %s", goal_id, description[:60])
        return goal

    def complete(self, goal_id: str, summary: str = "") -> bool:
        """Mark a goal as completed. Returns True if found."""
        goal = self._goals.get(goal_id)
        if goal is None:
            return False
        goal.status = "completed"
        goal.summary = summary
        goal.completed_at = self._now()
        self._save()
        return True

    def list_active(self) -> list[dict]:
        """Return all active goals as dicts."""
        return [g.to_dict() for g in self._goals.values() if g.status == "active"]

    def list_completed(self) -> list[dict]:
        """Return all completed goals as dicts."""
        return [g.to_dict() for g in self._goals.values() if g.status == "completed"]

    def get(self, goal_id: str) -> dict | None:
        """Get a specific goal by ID."""
        g = self._goals.get(goal_id)
        return g.to_dict() if g else None

    def _save(self) -> None:
        if self._persist_path is None:
            return
        try:
            data = {"goals": [g.to_dict() for g in self._goals.values()]}
            self._persist_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save goals: %s", e)

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for gd in data.get("goals", []):
                goal = Goal.from_dict(gd)
                self._goals[goal.id] = goal
        except Exception as e:
            logger.warning("Failed to load goals: %s — starting fresh", e)

    @staticmethod
    def _now() -> str:
        from tain_agent.core.time_utils import now
        return now().isoformat()
```

- [ ] **Step 2: Write failing tests for GoalManager**

```python
# Add to tests/test_knowledge_plugin.py

from tain_agent.plugins.knowledge.goal_manager import GoalManager, Goal


def test_goal_manager_create_and_list():
    """GoalManager.create() adds an active goal, list_active() returns it."""
    gm = GoalManager()
    goal = gm.create("Learn Rust", "Complete the Rust book")
    assert goal.status == "active"
    assert goal.description == "Learn Rust"
    active = gm.list_active()
    assert len(active) == 1
    assert active[0]["id"] == goal.id


def test_goal_manager_complete():
    """GoalManager.complete() marks goal as completed."""
    gm = GoalManager()
    goal = gm.create("Write tests", "95% coverage")
    assert gm.complete(goal.id, "Done")
    assert len(gm.list_active()) == 0
    assert len(gm.list_completed()) == 1
    assert gm.list_completed()[0]["summary"] == "Done"


def test_goal_manager_persist_and_load(tmp_path):
    """GoalManager persists to JSON and reloads."""
    path = tmp_path / "goals.json"
    gm1 = GoalManager()
    gm1.initialize(path)
    gm1.create("Goal A", "Criteria A")

    gm2 = GoalManager()
    gm2.initialize(path)
    assert len(gm2.list_active()) == 1
    assert gm2.list_active()[0]["description"] == "Goal A"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_knowledge_plugin.py::test_goal_manager_create_and_list tests/test_knowledge_plugin.py::test_goal_manager_complete tests/test_knowledge_plugin.py::test_goal_manager_persist_and_load -v`
Expected: FAIL with ImportError

- [ ] **Step 4: Wire GoalManager into KnowledgePlugin**

```python
# In tain_agent/plugins/knowledge/__init__.py, add to KnowledgePlugin.__init__:
from tain_agent.plugins.knowledge.goal_manager import GoalManager

# In __init__:
    def __init__(self):
        self._ctx: AgentContext | None = None
        self._dynamic: list[dict[str, Any]] = []
        self._graph: KnowledgeGraph = KnowledgeGraph()
        self._persist_path: Path | None = None
        self._goals: GoalManager = GoalManager()  # <-- add this line

# In initialize(), after self._load():
        goals_path = ctx.workspace_path / "knowledge" / "goals.json"
        self._goals.initialize(goals_path)

# In shutdown(), before self._ctx = None:
        self._goals = GoalManager()

# Add property after the KnowledgePlugin class body:
    @property
    def goals(self) -> GoalManager:
        """Access the agent's goal manager."""
        return self._goals
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_knowledge_plugin.py -v`
Expected: All knowledge plugin tests PASS

- [ ] **Step 6: Commit**

```bash
git add tain_agent/plugins/knowledge/goal_manager.py tain_agent/plugins/knowledge/__init__.py tests/test_knowledge_plugin.py
git commit -m "feat(knowledge-plugin): add GoalManager sub-component with JSON persistence"
```

---

### Task 3: MemoryPlugin — expose session_memory property

**Files:**
- Read: `tain_agent/plugins/memory/__init__.py`
- Read: `tain_agent/core/session_memory.py`
- Modify: `tain_agent/plugins/memory/__init__.py`
- Test: `tests/test_memory_plugin.py`

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_memory_plugin.py

def test_session_memory_property_accessible(memory_plugin, agent_context):
    """MemoryPlugin exposes session_memory for dialogue.py compatibility."""
    memory_plugin.initialize(agent_context)
    sm = memory_plugin.session_memory
    assert sm is not None
    assert hasattr(sm, 'start_session')
    assert hasattr(sm, 'get_user_name')
    assert hasattr(sm, 'set_user_name')
    assert hasattr(sm, 'get_context_for_prompt')
    assert hasattr(sm, 'end_session')
    assert hasattr(sm, 'recent_sessions')
    assert hasattr(sm, 'total_sessions')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_plugin.py::test_session_memory_property_accessible -v`
Expected: FAIL with AttributeError

- [ ] **Step 3: Implement session_memory property on MemoryPlugin**

```python
# In tain_agent/plugins/memory/__init__.py, add property:

    @property
    def session_memory(self):
        """Return a SessionMemory wrapper for dialogue.py compatibility.
        
        SessionMemory wraps the MemoryPlugin's recall/encode for human
        session awareness (user name, session history, context recall).
        """
        from tain_agent.core.session_memory import SessionMemory
        return SessionMemory(memory_plugin=self)
```

- [ ] **Step 4: Adapt SessionMemory to accept MemoryPlugin via separate JSON storage**

SessionMemory currently uses `self._memory.long_term.get("dialogue_sessions")` and `self._memory.remember("dialogue_sessions", data, persist=True)` — old `core/memory.py` API.

Adapt it to also accept a `memory_plugin` kwarg. When a plugin is provided, use a JSON file for persistence instead:

```python
# In tain_agent/core/session_memory.py, update __init__:

class SessionMemory:
    MAX_SESSIONS = 20

    def __init__(self, memory=None, *, memory_plugin=None):
        self._memory = memory  # legacy Memory instance (may be None)
        self._plugin = memory_plugin  # MemoryPlugin instance (may be None)
        self._persist_path: Path | None = None
        self._current_session: dict | None = None

        # If using plugin, derive persist path from workspace
        if memory_plugin is not None and memory_plugin._ctx is not None:
            self._persist_path = (
                memory_plugin._ctx.workspace_path / "memory" / "dialogue_sessions.json"
            )
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if self._plugin is not None and self._persist_path is not None:
            try:
                if self._persist_path.exists():
                    return json.loads(self._persist_path.read_text(encoding="utf-8"))
            except Exception:
                pass
            return {}
        if self._memory is not None:
            return self._memory.long_term.get("dialogue_sessions", {})
        return {}

    def _save(self, data: dict) -> None:
        if self._plugin is not None and self._persist_path is not None:
            self._persist_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return
        if self._memory is not None:
            self._memory.remember("dialogue_sessions", data, persist=True)
```

Add `import json` and `from pathlib import Path` at top of file.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_memory_plugin.py::test_session_memory_property_accessible -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tain_agent/plugins/memory/__init__.py tain_agent/core/session_memory.py tests/test_memory_plugin.py
git commit -m "feat(memory-plugin): expose session_memory property for dialogue compatibility"
```

---

### Task 4: IdentityPlugin — integrate Personality as sub-component

**Files:**
- Read: `tain_agent/plugins/identity/__init__.py`
- Read: `tain_agent/core/personality.py` (Personality class)
- Modify: `tain_agent/plugins/identity/__init__.py`
- Test: `tests/test_identity_plugin.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_identity_plugin.py

def test_personality_get_context_for_prompt(identity_plugin, agent_context):
    """IdentityPlugin.personality.get_context_for_prompt() returns trait context."""
    identity_plugin.initialize(agent_context)
    ctx = identity_plugin.personality.get_context_for_prompt()
    assert isinstance(ctx, str)


def test_personality_introspect(identity_plugin, agent_context):
    """IdentityPlugin.personality.introspect() returns trait summary."""
    identity_plugin.initialize(agent_context)
    result = identity_plugin.personality.introspect()
    assert isinstance(result, dict)
    assert "traits" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_identity_plugin.py::test_personality_get_context_for_prompt tests/test_identity_plugin.py::test_personality_introspect -v`
Expected: FAIL with AttributeError

- [ ] **Step 3: Add personality property to IdentityPlugin**

```python
# In tain_agent/plugins/identity/__init__.py, add property:

    @property
    def personality(self):
        """Return a Personality adapter backed by IdentityPlugin's trait data.
        
        Provides get_context_for_prompt() and introspect() for dialogue.py
        compatibility. Reads/writes traits through self.identity.traits.
        """
        return _PersonalityAdapter(self)

# Add adapter class at module level:

class _PersonalityAdapter:
    """Adapter that exposes Personality-like API from IdentityPlugin traits."""
    
    def __init__(self, plugin: "IdentityPlugin"):
        self._plugin = plugin

    def get_context_for_prompt(self) -> str:
        """Build a prompt context string from confident traits."""
        return self._plugin._trait_context()

    def introspect(self) -> dict:
        """Return a summary of current personality traits."""
        if self._plugin.identity is None:
            return {"traits": {}}
        result = {"traits": {}}
        for cat, traits in self._plugin.identity.traits.items():
            result["traits"][cat] = [
                {"value": t.get("value", ""), "confidence": t.get("confidence", 0)}
                for t in traits
            ]
        return result

    def auto_observe(self, tool_names: list[str], text_parts: list[str]) -> None:
        """Behavioral observation of tool usage to auto-discover traits."""
        self._plugin._observe_traits(tool_names, text_parts)
```

- [ ] **Step 4: IdentityPlugin._observe_traits already exists — verify it works**

```python
# The existing _observe_traits() in IdentityPlugin creates a temporary
# Personality(), copies traits, calls auto_observe, copies back.
# This already works. The _PersonalityAdapter wraps it cleanly.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_identity_plugin.py -v`
Expected: All identity plugin tests PASS

- [ ] **Step 6: Commit**

```bash
git add tain_agent/plugins/identity/__init__.py tests/test_identity_plugin.py
git commit -m "feat(identity-plugin): add personality adapter with get_context_for_prompt and introspect"
```

---

### Task 5: Create kernel/factories.py and kernel/prompts.py

**Files:**
- Create: `tain_agent/kernel/factories.py`
- Create: `tain_agent/kernel/prompts.py`
- Read: `tain_agent/core/bootstrap.py` (lines 1-153 for system prompts)

- [ ] **Step 1: Create kernel/factories.py**

```python
# tain_agent/kernel/factories.py
"""Standard Plugin factory mapping for AgentKernel initialization."""

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

- [ ] **Step 2: Create kernel/prompts.py with three system prompts from bootstrap.py**

```python
# tain_agent/kernel/prompts.py
"""System prompts migrated from bootstrap.py.

These are the three core prompts used by the AgentKernel depending on
evolution mode and context.
"""

# Read the exact prompt strings from bootstrap.py
# and replicate them here verbatim.
```

To extract the prompts:
Run: `grep -n "BOOTSTRAP_SYSTEM_PROMPT\|SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT\|EVOLVE_SYSTEM_PROMPT" tain_agent/core/bootstrap.py`
Expected: Line numbers for the three prompt variable definitions.

Copy the three prompt string assignments from bootstrap.py:21-153 into kernel/prompts.py.

- [ ] **Step 3: Update AgentKernel exports**

```python
# In tain_agent/kernel/__init__.py, add to __all__:
from tain_agent.kernel.factories import STANDARD_FACTORIES
from tain_agent.kernel.prompts import BOOTSTRAP_SYSTEM_PROMPT, SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT, EVOLVE_SYSTEM_PROMPT

__all__ = ["AgentKernel", "PluginProtocol", "AgentContext", "HealthStatus",
           "STANDARD_FACTORIES", "BOOTSTRAP_SYSTEM_PROMPT",
           "SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT", "EVOLVE_SYSTEM_PROMPT"]
```

- [ ] **Step 4: Verify kernel module imports cleanly**

Run: `python -c "from tain_agent.kernel import STANDARD_FACTORIES, EVOLVE_SYSTEM_PROMPT; print('OK')" 2>/dev/null || python -c "from tain_agent.kernel.factories import STANDARD_FACTORIES; from tain_agent.kernel.prompts import EVOLVE_SYSTEM_PROMPT; print('OK')"`
Expected: "OK"

- [ ] **Step 5: Commit**

```bash
git add tain_agent/kernel/factories.py tain_agent/kernel/prompts.py tain_agent/kernel/__init__.py
git commit -m "feat(kernel): add STANDARD_FACTORIES and migrated system prompts"
```

---

### Task 6: Migrate main.py — TaoAgent → AgentKernel

**Files:**
- Modify: `main.py`
- Read: `tain_agent/compat.py` (for AgentKernel usage pattern reference)

- [ ] **Step 1: Replace imports**

```python
# In main.py, replace lines 31-32:
# OLD:
# from tain_agent.core.agent import TaoAgent
# from tain_agent.core.agent_factory import AgentFactory
#
# NEW:
from tain_agent.core.agent_factory import AgentFactory
from tain_agent.kernel import AgentKernel, AgentContext, STANDARD_FACTORIES
from tain_agent.kernel.prompts import EVOLVE_SYSTEM_PROMPT
from tain_agent.core.llm import LLMBackend
from tain_agent.core.conversation import ConversationManager
from tain_agent.core.drives import DriveSystem
from tain_agent import __version__
```

- [ ] **Step 2: Replace agent creation block (lines 328-333)**

```python
# OLD lines 328-333:
#     if args.new_kernel:
#         from tain_agent.compat import TaoAgentCompat
#         agent = TaoAgentCompat(config_path=args.config, agent_name=agent_name)
#     else:
#         agent = TaoAgent(config_path=args.config, agent_name=agent_name)

# NEW: Replace with AgentKernel direct creation
    import yaml
    config_path = args.config
    cfg = {}
    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    evolution_mode = cfg.get("agent", {}).get("evolution_mode", "specified")
    workspace = Path("agent_workspace") / agent_name

    ctx = AgentContext(
        agent_name=agent_name,
        agent_id=f"{agent_name}-{workspace.name}",
        evolution_mode=evolution_mode,
        workspace_path=workspace,
        config=cfg,
        kernel_version=__version__,
    )
    kernel = AgentKernel(ctx)
    kernel.load_plugins(STANDARD_FACTORIES)

    # Create LLM backend, conversation, drives (same pattern as compat.py)
    backend_config = cfg.get("llm", {})
    backend = LLMBackend(backend_config)
    conversation = ConversationManager(
        workspace=str(workspace),
        agent_name=agent_name,
    )
    drives = DriveSystem()

    system_prompt = EVOLVE_SYSTEM_PROMPT.format(
        agent_name=agent_name,
        role=cfg.get("identity", {}).get("role", ""),
        role_description=cfg.get("identity", {}).get("role_description", ""),
    )
```

- [ ] **Step 3: Add a lightweight compat wrapper for state/log/export commands**

main.py uses `agent.print_state()`, `agent.decision_log.read_all()`, `agent.version`, `agent.phase`. Create a minimal adapter:

```python
# After the kernel creation block, add:
    class _AgentStateAdapter:
        """Minimal adapter so main.py's state/log commands work with AgentKernel."""
        def __init__(self, kernel, agent_name, framework_version, phase="explore"):
            self.kernel = kernel
            self.agent_name = agent_name
            self.version = framework_version
            self.phase = phase
            self.decision_log = _DecisionLogShim([])

        def print_state(self):
            print(f"\n  Agent: {self.agent_name}")
            print(f"  Version: {self.version}")
            print(f"  Phase: {self.phase}")
            print(f"  Cycle: {self.kernel.pral.cycle_count}")
            print()
            for name, health in self.kernel.lifecycle.all_health_checks().items():
                status = getattr(health, 'status', str(health))
                print(f"  [{name}] {status}")
            print()

        def stop(self):
            self.kernel.shutdown()

        def run(self):
            return self.kernel.run(backend, conversation, drives, system_prompt)

    agent = _AgentStateAdapter(kernel, agent_name, __version__)
    # Backend and conversation are captured by closure; attach for dialogue
    agent.backend = backend
    agent.config = cfg
    agent.conversation = conversation
    agent.tools = kernel.lifecycle.get("tool")
    agent.memory = kernel.lifecycle.get("memory")
    agent.personality = (
        kernel.lifecycle.get("identity").personality
        if kernel.lifecycle.get("identity") else None
    )
```

Reuse `_DecisionLogShim` from compat.py (copy the 8-line class inline).

- [ ] **Step 4: Update dialogue mode to pass kernel to DialogueBridge**

```python
# In main.py line 443, replace:
#   dialogue = DialogueBridge(agent)
# with:
    dialogue = DialogueBridge(agent, kernel=kernel)
```

- [ ] **Step 5: Run main.py --state to verify**

Run: `python main.py --agent test_migration --state 2>&1`
Expected: Shows agent state using kernel.lifecycle.all_health_checks()

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -q --ignore=tests/test_dialogue.py 2>&1 | tail -5`
Expected: All tests except possibly dialogue tests PASS

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "refactor(main): migrate CLI from TaoAgent to AgentKernel direct"
```

---

### Task 7: Migrate webui/agent_cache.py — AgentKernel caching

**Files:**
- Modify: `webui/agent_cache.py`

- [ ] **Step 1: Replace imports and cache type**

```python
# In webui/agent_cache.py, replace:
# from tain_agent.core.agent import TaoAgent
# with:
from tain_agent.kernel import AgentKernel, AgentContext, STANDARD_FACTORIES

# Change cache type annotation:
_cache: dict[str, tuple[float, "AgentKernel"]] = {}
```

- [ ] **Step 2: Replace get_agent() with get_kernel()**

```python
def get_kernel(name: str, config_path: str) -> "AgentKernel":
    """Get or create a cached AgentKernel instance. Rebuilds if config changed."""
    import yaml
    global WORKSPACE_ROOT
    workspace = WORKSPACE_ROOT / name
    mtime = 0.0

    for path in (workspace / "agent.yaml", workspace / "version.json"):
        if path.exists():
            mtime = max(mtime, path.stat().st_mtime)

    if name in _cache:
        cached_mtime, kernel = _cache[name]
        if cached_mtime >= mtime:
            return kernel
        logger.info("Agent %s kernel cache invalidated", name)

    logger.info("Creating new AgentKernel for %s", name)
    with open(config_path) as f:
        config = yaml.safe_load(f)

    evolution_mode = config.get("agent", {}).get("evolution_mode", "specified")
    ctx = AgentContext(
        agent_name=name,
        agent_id=f"{name}-{workspace.name}",
        evolution_mode=evolution_mode,
        workspace_path=workspace,
        config=config,
        kernel_version=__version__,
    )
    kernel = AgentKernel(ctx)
    kernel.load_plugins(STANDARD_FACTORIES)
    _cache[name] = (time.time(), kernel)
    return kernel


def get_agent(name: str, config_path: str) -> "AgentKernel":
    """Backward-compatible alias — returns AgentKernel."""
    return get_kernel(name, config_path)
```

- [ ] **Step 3: Add __version__ import**

```python
from tain_agent import __version__
```

- [ ] **Step 4: Verify import**

Run: `python -c "from webui.agent_cache import get_kernel, get_agent; print('OK')"`
Expected: "OK"

- [ ] **Step 5: Commit**

```bash
git add webui/agent_cache.py
git commit -m "refactor(webui): migrate agent_cache from TaoAgent to AgentKernel caching"
```

---

### Task 8: Migrate acp/server.py — session-scoped AgentKernel

**Files:**
- Modify: `tain_agent/acp/server.py`

- [ ] **Step 1: Replace per-request TaoAgent creation**

```python
# In the prompt handler (around line 198-202), replace:
#     from tain_agent.core.chat import ChatEngine
#     from tain_agent.core.agent import TaoAgent
#     agent_name = f"acp_session_{session_id[:8]}"
#     agent = TaoAgent(config_path=self.config_path, agent_name=agent_name)
#     engine = ChatEngine(agent)

# With:
    from tain_agent.core.chat import ChatEngine
    from tain_agent.kernel import AgentKernel, AgentContext, STANDARD_FACTORIES
    from tain_agent import __version__
    import yaml

    # Session-scoped kernel cache
    agent_name = f"acp_session_{session_id[:8]}"
    workspace = Path("agent_workspace") / agent_name
    workspace.mkdir(parents=True, exist_ok=True)

    with open(self.config_path) as f:
        config = yaml.safe_load(f) or {}

    ctx = AgentContext(
        agent_name=agent_name,
        agent_id=f"{agent_name}-{workspace.name}",
        evolution_mode=config.get("agent", {}).get("evolution_mode", "specified"),
        workspace_path=workspace,
        config=config,
        kernel_version=__version__,
    )
    kernel = AgentKernel(ctx)
    kernel.load_plugins(STANDARD_FACTORIES)

    # Wrap kernel as chat-compatible adapter
    agent = _ACPAgentAdapter(kernel, agent_name, config)
    engine = ChatEngine(agent)
```

- [ ] **Step 2: Add _ACPAgentAdapter class at module level**

```python
class _ACPAgentAdapter:
    """Minimal adapter so ChatEngine can use AgentKernel."""
    def __init__(self, kernel, agent_name, config):
        self.kernel = kernel
        self.agent_name = agent_name
        self.config = config
        tool_plugin = kernel.lifecycle.get("tool")
        self.tools = tool_plugin
        identity_plugin = kernel.lifecycle.get("identity")
        self.personality = identity_plugin.personality if identity_plugin else None
        # LLM backend created per-request for isolation
        from tain_agent.core.llm import LLMBackend
        self.backend = LLMBackend(config.get("llm", {}))

    def _execute_tool_calls(self, tool_calls):
        results = []
        for tc in tool_calls:
            result = self.kernel.dispatch.call("tool.call", tc.name, **tc.input)
            content = str(result) if result is not None else f"Tool '{tc.name}' returned no result"
            results.append({"tool_use_id": tc.id, "content": content})
        return results
```

- [ ] **Step 3: Add Path import if not present**

```python
from pathlib import Path
```

- [ ] **Step 4: Commit**

```bash
git add tain_agent/acp/server.py
git commit -m "refactor(acp): migrate from per-request TaoAgent to session-scoped AgentKernel"
```

---

### Task 9: Migrate dialogue.py — largest consumer

**Files:**
- Modify: `tain_agent/core/dialogue.py`

- [ ] **Step 1: Audit all agent.* attribute accesses**

Run a full audit to list every access:
```bash
grep -n "self\.agent\." tain_agent/core/dialogue.py
```

Expected output (verified against the file read above):
```
Line 138: self.session_memory = SessionMemory(agent.memory)
Line 144: self.agent.backend
Line 145: self.agent.config
Line 169: self.agent.conversation.load_checkpoint()
Line 174: self.agent.conversation.clear()
Line 175: self.agent.conversation.append(...)
Line 177: self.agent.conversation.clear()
Line 179: self.agent.conversation.append(...)
Line 181: self.agent.conversation.clear()
Line 194: self.agent.conversation.append(...)
Line 226: self.agent.version
Line 239: self.agent.conversation
Line 243: self.agent.conversation.len()
Line 244: self.agent.conversation.checkpoint()
Line 301: self.agent.conversation
Line 319: self.agent.backend.create_message(...)
Line 347: self.agent.goals.create_goal(...)
Line 358: self._evolve_handler()
Line 361: self.agent.stop()
Line 362: self.agent.print_state()
Line 369: self._evolve_handler()
Line 372: self.agent.stop()
Line 373: self.agent.print_state()
Line 379: self.agent.conversation.append(...)
Line 383: self.agent.conversation.len()
Line 384: self.agent.conversation.keep_first_and_last(...)
Line 387: self.agent.conversation.to_claude_messages()
Line 388: self.agent.tools.get_claude_tool_definitions()
Line 392: self.agent.backend.stream_message(...)
Line 399: self.agent.conversation.len()
Line 400: self.agent.conversation.keep_first_and_last(...)
Line 402: self.agent.conversation.to_claude_messages()
Line 403: self.agent.backend.stream_message(...)
Line 483: self.agent.conversation.append(...)
Line 492: self.agent._execute_tool_calls(...)
Line 497: self.agent.conversation.append(...)
Line 519: self.agent.conversation.append(...)
Line 528: self.agent.conversation.append(...)
Line 553: self.agent.print_state()
Line 613: self.agent.tools.list_tools()
Line 659: self.agent.personality
Line 660: self.agent.personality.get_context_for_prompt()
Line 664: self.agent.tools.list_tools()
Line 687: self.agent.version
Line 688: self.agent.phase
Line 689: self.agent.forge.list_forged()
Line 690: self.agent.goals.list_active()
Line 692: self.agent.capability
Line 694: self.agent.capability.assess()
```

Total: ~30 unique access patterns across 6 subsystems.

- [ ] **Step 2: Add kernel parameter to DialogueBridge.__init__**

```python
# In tain_agent/core/dialogue.py, modify __init__:
    def __init__(self, agent, kernel=None):
        self.agent = agent  # Keep for backward compat, will be the adapter
        self.kernel = kernel  # New: AgentKernel reference for Plugin access
        self._running = False
        self._dialogue_system_prompt = DIALOGUE_SYSTEM_PROMPT
        self._evolve_handler = agent.run if hasattr(agent, 'run') else (lambda: 0)
        agent._dialogue = self

        # Session memory — use Plugin or legacy path
        if kernel:
            mem_plugin = kernel.lifecycle.get("memory")
            if mem_plugin:
                self.session_memory = SessionMemory(memory_plugin=mem_plugin)
            else:
                self.session_memory = SessionMemory(agent.memory if hasattr(agent, 'memory') else None)
        else:
            self.session_memory = SessionMemory(agent.memory if hasattr(agent, 'memory') else None)
```

- [ ] **Step 3: Create convenience property accessors via kernel**

```python
# Add to DialogueBridge:

    @property
    def _tools(self):
        """Get ToolPlugin (kernel) or fall back to agent.tools."""
        if self.kernel:
            tp = self.kernel.lifecycle.get("tool")
            if tp:
                return tp
        return self.agent.tools if hasattr(self.agent, 'tools') else None

    @property
    def _personality(self):
        """Get Personality adapter (kernel) or fall back to agent.personality."""
        if self.kernel:
            ip = self.kernel.lifecycle.get("identity")
            if ip:
                return ip.personality
        return self.agent.personality if hasattr(self.agent, 'personality') else None

    @property
    def _goals(self):
        """Get GoalManager (kernel) or fall back to agent.goals."""
        if self.kernel:
            kp = self.kernel.lifecycle.get("knowledge")
            if kp:
                return kp.goals
        return self.agent.goals if hasattr(self.agent, 'goals') else None

    @property
    def _forge(self):
        """Get ToolPlugin forge (kernel) or fall back to agent.forge."""
        if self.kernel:
            tp = self.kernel.lifecycle.get("tool")
            if tp:
                return tp  # ToolPlugin itself has list_forged()
        return self.agent.forge if hasattr(self.agent, 'forge') else None
```

- [ ] **Step 4: Update all access points to use the new adapters**

Systematically replace each access pattern:

| Old | New |
|-----|-----|
| `self.agent.tools.list_tools()` | `self._tools.list_tools()` |
| `self.agent.tools.get_claude_tool_definitions()` | `self._tools.get_claude_tool_definitions()` |
| `self.agent.personality` | `self._personality` |
| `self.agent.personality.get_context_for_prompt()` | `self._personality.get_context_for_prompt()` |
| `self.agent.goals.create_goal(...)` | `self._goals.create(...)` (GoalManager API) |
| `self.agent.goals.list_active()` | `self._goals.list_active()` |
| `self.agent.forge.list_forged()` | `self._forge.list_forged()` |
| `self.agent.capability.assess()` | Real-time aggregation from plugins |
| `self.agent._execute_tool_calls(tcs)` | Kernel dispatch or ToolPlugin.call() |

For `capability.assess()`, inline a simple replacement:
```python
def _assess_capability(self) -> dict:
    """Compute capability assessment from available plugins."""
    tools = self._tools.list_tools() if self._tools else {}
    knowledge = self.kernel.lifecycle.get("knowledge")
    goals = self._goals
    return {
        "coverage_pct": len(tools),
        "tools_count": len(tools),
        "forged_count": len(self._forge.list_forged() if self._forge else {}),
        "active_goals": len(goals.list_active() if goals else []),
        "knowledge_entities": knowledge._graph.entity_count if knowledge else 0,
    }
```

- [ ] **Step 5: Update _trigger_evolution_from_dialogue to use GoalManager API**

```python
# Line 347: self.agent.goals.create_goal(...) becomes:
    goal = self._goals.create(
        description=goal_text,
        success_criteria=f"完成目标: {goal_text}",
    )
    # GoalManager.create() returns a Goal object with .id attribute
    print(f"\n🎯 新目标已创建: [{goal.id}] {goal_text}")
```

- [ ] **Step 6: Run dialogue-related tests**

Run: `pytest tests/test_dialogue.py -v 2>&1 | tail -15`
Expect: Some may fail until full migration is complete — note failures for adjustment.

- [ ] **Step 7: Commit**

```bash
git add tain_agent/core/dialogue.py
git commit -m "refactor(dialogue): migrate from TaoAgent attribute access to kernel Plugin queries"
```

---

### Task 10: Migrate chat.py — hasattr → lifecycle.get()

**Files:**
- Modify: `tain_agent/core/chat.py`

- [ ] **Step 1: Replace hasattr-based subsystem access**

The file uses `agent.personality`, `agent.tools.list_tools()`, `agent.tools.get_claude_tool_definitions()`, `agent.agent_name`, `agent.backend.stream_message`, `agent._execute_tool_calls`.

ChatEngine receives `agent` in `__init__`. If agent is the adapter from main.py or ACP, it should already have these attributes. The key change is making it work with both old TaoAgent and new adapter:

```python
# In ChatEngine.__init__, store kernel reference if available:
    def __init__(self, agent):
        self.agent = agent
        self._kernel = getattr(agent, 'kernel', None)

# In build_system_prompt(), replace hasattr checks:
# OLD (line 123): if hasattr(agent, 'personality') and agent.personality:
# NEW:
    personality = None
    if self._kernel:
        ip = self._kernel.lifecycle.get("identity")
        if ip:
            personality = ip.personality
    else:
        personality = getattr(agent, 'personality', None)
    if personality:
        try:
            ctx = personality.get_context_for_prompt()
            if ctx:
                lines.append("\n" + ctx)
        except Exception:
            pass

# OLD (line 130): tools = agent.tools.list_tools() if hasattr(agent.tools, 'list_tools') else {}
# NEW:
    tools = {}
    if self._kernel:
        tp = self._kernel.lifecycle.get("tool")
        if tp:
            tools = tp.list_tools()
    elif hasattr(agent, 'tools') and hasattr(agent.tools, 'list_tools'):
        tools = agent.tools.list_tools()

# OLD (line 147): if not hasattr(self.agent.tools, 'get_claude_tool_definitions'):
# NEW:
    def _get_tool_defs(self):
        if self._kernel:
            tp = self._kernel.lifecycle.get("tool")
            if tp and hasattr(tp, 'get_claude_tool_definitions'):
                return tp.get_claude_tool_definitions()
        if hasattr(self.agent, 'tools') and hasattr(self.agent.tools, 'get_claude_tool_definitions'):
            return self.agent.tools.get_claude_tool_definitions()
        return None
```

- [ ] **Step 2: Update _build_tool_defs()**

```python
    def _build_tool_defs(self) -> list | None:
        all_tools = self._get_tool_defs()
        if not all_tools:
            return None
        safe = [t for t in all_tools
                if not t["name"].startswith(("test_", "forge_", "_"))]
        priority = [t for t in safe
                    if any(t["name"].startswith(p)
                           for p in ("web_search", "web_fetch", "knowledge_fetch", "wikipedia"))]
        others = [t for t in safe if t not in priority]
        return (priority + others)[:20] if safe else None
```

- [ ] **Step 3: Handle _execute_tool_calls via kernel dispatch**

```python
# In ChatEngine.run_turn(), replace line 82:
#   results = self.agent._execute_tool_calls(turn_tools)
# With kernel-aware dispatch:
    if self._kernel:
        results = []
        for tc in turn_tools:
            result = self._kernel.dispatch.call("tool.call", tc.name, **tc.input)
            content = str(result) if result is not None else f"Tool '{tc.name}' returned no result"
            results.append({"tool_use_id": tc.id, "content": content})
    else:
        results = self.agent._execute_tool_calls(turn_tools)
```

- [ ] **Step 4: Run chat unit tests**

Run: `pytest tests/ -k "chat" -v 2>&1 | tail -10`
Expected: Tests pass (chat.py has no direct test file; integration tests may exercise it)

- [ ] **Step 5: Commit**

```bash
git add tain_agent/core/chat.py
git commit -m "refactor(chat): replace hasattr checks with kernel lifecycle.get() Plugin queries"
```

---

### Task 11: Delete old Mixin files + compat.py

**Files to DELETE:**
- `tain_agent/core/agent.py`
- `tain_agent/core/agent_config.py`
- `tain_agent/core/agent_subsystems.py`
- `tain_agent/core/agent_cognition.py`
- `tain_agent/core/agent_phase.py`
- `tain_agent/core/agent_tools.py`
- `tain_agent/core/agent_protocols.py`
- `tain_agent/core/bootstrap.py`
- `tain_agent/compat.py`

- [ ] **Step 1: Verify no import references remain**

```bash
# Check ALL imports of the files to be deleted
grep -rn "from tain_agent.core.agent import\|from tain_agent.core.agent_config\|from tain_agent.core.agent_subsystems\|from tain_agent.core.agent_cognition\|from tain_agent.core.agent_phase\|from tain_agent.core.agent_tools\|from tain_agent.core.agent_protocols\|from tain_agent.core.bootstrap import\|from tain_agent.compat import\|from tain_agent.core import bootstrap\|from tain_agent import compat" tain_agent/ main.py webui/ tests/ --include="*.py" | grep -v "test_.*\.py" | grep -v __pycache__
```

For any remaining references, update them to use `kernel.prompts` (for system prompts) or remove (for Mixin imports).

- [ ] **Step 2: Delete the files**

```bash
rm tain_agent/core/agent.py
rm tain_agent/core/agent_config.py
rm tain_agent/core/agent_subsystems.py
rm tain_agent/core/agent_cognition.py
rm tain_agent/core/agent_phase.py
rm tain_agent/core/agent_tools.py
rm tain_agent/core/agent_protocols.py
rm tain_agent/core/bootstrap.py
rm tain_agent/compat.py
```

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -q 2>&1 | tail -10`
Expected: 718+ tests pass, zero regression

- [ ] **Step 4: Fix any test imports that reference deleted modules**

If tests directly import from the deleted modules, update them:
- Tests importing `from tain_agent.core.agent import TaoAgent` → use `from tain_agent.kernel import AgentKernel`
- Tests importing `from tain_agent.core.bootstrap import EVOLVE_SYSTEM_PROMPT` → use `from tain_agent.kernel.prompts import EVOLVE_SYSTEM_PROMPT`

Iterate until full suite passes.

- [ ] **Step 5: Commit**

```bash
git add -u tain_agent/core/ tain_agent/compat.py
git add tests/
git commit -m "chore: delete old TaoAgent Mixin files, bootstrap.py, compat.py — AgentKernel is sole entry point"
```

---

### Task 12: Final verification

- [ ] **Step 1: Verify no import residuals**

```bash
grep -rn "from.*agent_config\|from.*agent_subsystems\|from.*agent_cognition\|from.*agent_phase\|from.*agent_tools\|from.*agent_protocols" tain_agent/ main.py webui/ 2>&1
```
Expected: Empty output

- [ ] **Step 2: Verify hasattr reduction in core layer**

```bash
grep -rn "hasattr" tain_agent/kernel/ tain_agent/plugins/ 2>&1
```
Expected: Only defensive `getattr(plugin, method, None)` patterns and kernel protocol checks remain

- [ ] **Step 3: Run full test suite with verbose failures**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 4: Run end-to-end smoke test**

```bash
# Create a test agent and verify state
python main.py --agent _smoke_test --state 2>&1
```
Expected: Shows agent state without errors

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "verify: architecture migration complete — 2788 lines removed, AgentKernel sole entry point"
```
