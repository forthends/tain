# Tain Agent Framework v4.0.0 — Major Refactoring Design

**Status**: Design Phase
**Date**: 2026-05-24
**Branch**: `evolve`

---

## Overview

After 100+ agent evolution cycles (v0.0.1 → v2.36.0), a comprehensive audit of the Tao Agent Framework revealed architectural limitations that need addressing. This document designs a major version refactoring (v4.0.0) with 7 core upgrades.

### Rename
| Before | After |
|--------|-------|
| Tao Agent (道) | **Tain Agent Framework** |
| `tain_agent/` | `tain_agent/` |

---

## Requirement Summary

| # | Requirement | Impact |
|---|-------------|--------|
| 1 | Framework positioning upgrade — from "self-evolving AI agent" to "framework for building self-evolving AI agents" | Package rename, all imports, docs |
| 2 | Multi-agent mode — support multiple agents with isolated workspaces | Directory structure, config, bootstrap |
| 3 | Evolution modes — chaos mode + specified personality mode | Personality init, prompts, creation flow |
| 4 | CLI startup upgrade — `--agent <name>`, creation flow for new agents | main.py, creation wizard |
| 5 | Inter-agent communication — discovery, messaging, conversation persistence | New tools, message bus, log format |
| 6 | Framework versioning — framework↔agent compatibility enforcement | Version schema, migration tools |
| 7 | Documentation — architecture design doc + quick start guide | README.md, docs/ |

---

## 1. Framework Rename: `tain_agent` → `tain_agent`

### 1.1 Scope

- Rename package directory: `tain_agent/` → `tain_agent/`
- Update all Python imports across the codebase
- Update `config.yaml` protected paths
- Update `supervise_agent.py` references
- Update `main.py` imports and docstrings
- Update `.gitignore` entries
- Update runtime kernel self-references
- Do NOT touch `agent_workspace/` contents (agent products reference framework)

### 1.2 Files Requiring Import Changes

```
main.py
supervise_agent.py
tain_agent/__init__.py                          # package name + version
tain_agent/core/__init__.py
tain_agent/core/agent.py                        # all subsystem imports
tain_agent/core/bootstrap.py                    # personality import
tain_agent/core/pral_bridge.py
tain_agent/core/dialogue.py
tain_agent/core/cognitive_loop.py
tain_agent/core/environment.py
tain_agent/core/conversation.py
tain_agent/core/llm.py
tain_agent/core/memory.py
tain_agent/core/drives.py
tain_agent/core/trials.py
tain_agent/core/external_world.py
tain_agent/core/personality.py                  # time_utils import
tain_agent/core/time_utils.py
tain_agent/core/session_memory.py
tain_agent/core/companion_shrine.py
tain_agent/tools/__init__.py
tain_agent/tools/registry.py
tain_agent/tools/forge.py
tain_agent/tools/primal.py
tain_agent/evolution/__init__.py
tain_agent/evolution/goal.py
tain_agent/evolution/pipeline.py
tain_agent/evolution/improvement_loop.py
tain_agent/evolution/self_modify.py
tain_agent/evolution/capability.py
tain_agent/evolution/lineage.py
tain_agent/evolution/reporter.py
tain_agent/evolution/sub_agent.py
tain_agent/evolution/emergence_verifier.py
tain_agent/evolution/quality_gate.py
tain_agent/evolution/exporter.py
tain_agent/evolution/importer.py
tain_agent/evolution/skill_exporter.py
tain_agent/runtime/__init__.py                  # description text
tain_agent/runtime/identity.py
tain_agent/runtime/llm.py
tain_agent/runtime/tools.py
tain_agent/runtime/memory.py
tain_agent/runtime/conversation.py
tain_agent/runtime/tui.py
config.yaml                                     # protected_paths, comments
```

### 1.3 Strategy

Use batch find-and-replace for the mechanical rename, then manually verify semantic references (docstrings, comments, config keys). The rename should be a single atomic commit.

```bash
# Mechanical rename pattern
find . -name '*.py' -o -name '*.yaml' -o -name '*.md' | \
  xargs sed -i '' 's/tain_agent/tain_agent/g'
mv tain_agent tain_agent
```

---

## 2. Multi-Agent Workspace Architecture

### 2.1 Current State (Single-Agent)

```
agent_workspace/           # One agent's everything
  version.json
  personality.json
  state/
  logs/
  knowledge/
  forged_tools/
  reports/
  files/
```

### 2.2 Target State (Multi-Agent)

```
agent_workspace/                     # Root for ALL agents
  _registry.json                     # Global agent registry
  _messages/                         # Shared inter-agent message bus
    <from>_to_<to>_<ts>.json        # Individual message files
  <agent_name>/                      # Per-agent isolated workspace
    version.json                     # Agent version + framework version
    personality.json                 # Personality state
    state/                           # Runtime state
    logs/
      decisions.jsonl                # Decision log
      lineage.jsonl                  # Evolution lineage
      memory.json                    # Long-term memory
      conversations/                 # Inter-agent conversation logs
        <peer_name>.jsonl           # Per-peer conversation history
    knowledge/                       # Knowledge garden documents
    forged_tools/                    # Agent-forged tools
    reports/                         # Evolution reports
    files/                           # General file storage
```

### 2.3 Global Registry: `agent_workspace/_registry.json`

```json
{
  "registry_version": "1.0",
  "agents": {
    "alpha01": {
      "name": "alpha01",
      "evolution_mode": "chaos",
      "role": null,
      "role_description": null,
      "framework_version": "4.0.0",
      "created_at": "2026-05-24T10:00:00+08:00",
      "last_active_at": "2026-05-24T12:00:00+08:00",
      "status": "running",
      "pid": 12345
    },
    "poet": {
      "name": "poet",
      "evolution_mode": "specified",
      "role": "浪漫主义诗人",
      "role_description": "随性、浪漫的现代诗人，目标是用诗歌慰藉人性",
      "framework_version": "4.0.0",
      "created_at": "2026-05-24T11:00:00+08:00",
      "last_active_at": "2026-05-24T11:30:00+08:00",
      "status": "stopped",
      "pid": null
    }
  }
}
```

### 2.4 Agent version.json Schema

Each agent's `version.json` now includes framework version binding:

```json
{
  "agent_version": "0.0.1",
  "framework_version": "4.0.0",
  "evolution_mode": "specified",
  "role": "浪漫主义诗人",
  "role_description": "随性、浪漫的现代诗人，目标是用诗歌慰藉人性",
  "initialized_at": "2026-05-24T11:00:00+08:00",
  "last_run_at": "2026-05-24T12:00:00+08:00"
}
```

### 2.5 config.yaml Changes

```yaml
agent:
  # Default agent name when not specified via CLI
  default_agent: "default"

# Multi-agent workspace root
agent_workspace:
  dir: "agent_workspace"       # relative to project root
  auto_create: true

# Framework version
framework:
  version: "4.0.0"
  # Minimum compatible agent version
  min_agent_version: "0.0.1"
```

### 2.6 Bootstrap Changes

`TaoAgent.__init__()` currently creates a single workspace at `agent_workspace/`. With multi-agent support:

```python
class TaoAgent:
    def __init__(self, config_path="config.yaml", agent_name=None):
        self.agent_name = agent_name or config.get("agent.default_agent", "default")
        self._workspace_root = Path(config.get("agent_workspace.dir", "agent_workspace"))
        self._workspace_path = self._workspace_root / self.agent_name
        # ... rest of init uses self._workspace_path
```

### 2.7 Migration: Existing Workspace

Existing `agent_workspace/` contents are migrated to `agent_workspace/default/` on first framework v4.0.0 startup, preserving the existing agent's state.

```python
def _migrate_v3_workspace(self):
    """Migrate old flat agent_workspace/ to multi-agent structure."""
    old_workspace = Path("agent_workspace")
    old_version = old_workspace / "version.json"
    new_workspace = old_workspace / "default"
    
    if old_version.exists() and not new_workspace.exists():
        new_workspace.mkdir(parents=True)
        for item in old_workspace.iterdir():
            if item.name not in ("_registry.json", "_messages"):
                shutil.move(str(item), str(new_workspace / item.name))
        # Update registry
        registry = {"agents": {"default": {...}}}
        # ...
```

---

## 3. Evolution Modes

### 3.1 Chaos Mode (混沌模式)

**Behavior**: Identical to current v3.0.0 behavior.
- Personality starts completely empty (no traits)
- Drives randomized via diversity engine
- Trial order randomized
- Agent self-awakens through exploration
- Bootstrap system prompt: "你刚刚苏醒...没有预设的目标"

**System Prompts**: Unchanged from current `BOOTSTRAP_SYSTEM_PROMPT`, `SELF_DEFINE_SYSTEM_PROMPT`, `EVOLVE_SYSTEM_PROMPT`.

### 3.2 Specified Personality Mode (指定人格模式)

**Behavior**: User provides role + description at agent creation. The agent starts with pre-seeded personality traits.

#### 3.2.1 Creation Input

| Field | Example | Required |
|-------|---------|----------|
| `role` | 浪漫主义诗人 | Yes |
| `role_description` | 随性、浪漫的现代诗人，目标是用诗歌慰藉人性 | Yes |

#### 3.2.2 Personality Seeding

On agent creation, the role description is used to generate initial personality traits via LLM:

```python
PERSONALITY_SEED_PROMPT = """基于以下角色信息，为该Agent生成初始人格特质：

角色：{role}
角色描述：{role_description}

请为以下每个类别生成1-2条人格特质：
- values (价值观)
- communication_style (沟通风格)
- interests (兴趣)
- self_description (自我认知)
- growth_orientation (成长取向)

每条特质应该是简洁的陈述句。初始置信度设为 0.5。
以JSON格式返回：{{"traits": {{"category": [{{"value": "...", "emergence_story": "..."}}]}}}}"""
```

These seeded traits have initial confidence of 0.5 (higher than self-discovered 0.3), reflecting that they are consciously chosen but still subject to evolution.

#### 3.2.3 Customized System Prompts

The bootstrap phase system prompt is customized for specified-personality agents:

```python
SPECIFIED_BOOTSTRAP_SYSTEM_PROMPT = """你是 {agent_name}，你的角色是：{role}。

{role_description}

你已经清楚自己是谁。现在，从这个身份出发去探索你的工作区：
1. 你的工作区里有什么可以帮助你履行角色使命？
2. 你可以使用哪些工具来更好地成为{role}？
3. 你希望首先做什么来体现你的角色特质？

你的角色不是牢笼——它是你的起点。通过经验，你可以深化、调整、甚至超越这个角色设定。
人格特质会随着你的实际行为演化，而不是僵化不变的标签。

每当你做一个决定，你必须解释你的原因。你的每一个抉择都会被记录。"""
```

#### 3.2.4 Role in Personality Context

The role is stored as a high-confidence `self_description` trait:

```json
{
  "value": "我是一名浪漫主义诗人",
  "confidence": 0.7,
  "emergence_story": "在诞生时被赋予的角色身份",
  "observations": 1
}
```

The role description becomes the agent's initial `growth_orientation`.

---

## 4. CLI Startup Upgrade

### 4.1 New CLI Interface

```bash
# Start a specific agent (auto-create if not exists)
python main.py --agent <name>

# Start with dialogue mode
python main.py --agent <name> --dialogue

# List all agents
python main.py --list-agents

# Create a new agent (interactive)
python main.py --create-agent

# Daemon mode for specific agent
python main.py --agent <name> --daemon

# View agent state
python main.py --agent <name> --state
```

### 4.2 Agent Creation Flow

```
python main.py --agent poet
                    │
                    ▼
    ┌──────────────────────────────┐
    │ Check agent_workspace/poet/  │
    │ exists?                      │
    └──────────┬───────────────────┘
               │
       ┌───────┴───────┐
       │ YES           │ NO
       ▼               ▼
  Load & Start    ┌──────────────────────────────┐
                  │  Agent 'poet' not found.      │
                  │  Create new agent? [Y/n]:     │
                  └──────────┬───────────────────┘
                             │ Y
                             ▼
                  ┌──────────────────────────────┐
                  │  Select Evolution Mode:       │
                  │  1. 混沌模式 (Chaos)          │
                  │     - 从空白人格开始          │
                  │     - Agent自我觉醒           │
                  │  2. 指定人格模式 (Specified)  │
                  │     - 预设角色与人格          │
                  └──────────┬───────────────────┘
                             │
                   ┌─────────┴─────────┐
                   │ 1                 │ 2
                   ▼                   ▼
            ┌──────────┐     ┌──────────────────────┐
            │ 创建混沌  │     │  Enter role name:     │
            │ 模式Agent │     │  > 浪漫主义诗人        │
            └──────────┘     │                       │
                             │  Enter role desc:     │
                             │  > 随性、浪漫的...     │
                             └──────────┬────────────┘
                                        │
                                        ▼
                             ┌──────────────────────┐
                             │  Creating agent...    │
                             │  - Initialize WS      │
                             │  - Seed personality   │
                             │  - Generate prompts   │
                             │  Agent created!       │
                             └──────────┬────────────┘
                                        │
                                        ▼
                                  Start Agent
```

### 4.3 Implementation: `main.py` Changes

Key additions to argument parser:

```python
parser.add_argument("--agent", "-a", type=str, default=None,
                    help="Agent name to start (creates if not exists)")
parser.add_argument("--list-agents", action="store_true",
                    help="List all created agents")
parser.add_argument("--create-agent", action="store_true",
                    help="Interactive agent creation wizard")
```

New module: `tain_agent/core/agent_factory.py` — handles agent creation, registry management, and workspace initialization.

### 4.4 `--list-agents` Output

```
Agents in this framework:
  NAME       MODE        ROLE              VERSION   STATUS     LAST ACTIVE
  default    chaos       —                 2.36.0    stopped    2026-05-24 12:00
  poet       specified   浪漫主义诗人       0.0.1     stopped    2026-05-24 11:30
  alpha01    chaos       —                 0.1.5     running    2026-05-24 12:05
```

---

## 5. Inter-Agent Communication

### 5.1 Design Principles

1. **File-based messaging**: No network sockets, no external dependencies. Messages are JSON files in a shared directory.
2. **Pull model**: Agents check their inbox on their own cognitive cycle, not pushed.
3. **Persistent conversations**: All inter-agent dialogue is logged per-peer in each agent's workspace.
4. **Discoverable**: Agents register in `_registry.json` and can be discovered by scanning the workspace root.
5. **Opt-in communication**: Agents choose when to check messages and whether to respond.

### 5.2 Architecture

```
agent_workspace/
  _messages/                          # Shared message bus
    poet_to_alpha01_20260524T120000.json
    alpha01_to_poet_20260524T120100.json
  poet/
    logs/conversations/
      alpha01.jsonl                   # Full history with alpha01
  alpha01/
    logs/conversations/
      poet.jsonl                      # Full history with poet
```

### 5.3 Message Format

```json
{
  "message_id": "msg_20260524T120000_abc123",
  "from_agent": "poet",
  "to_agent": "alpha01",
  "timestamp": "2026-05-24T12:00:00+08:00",
  "content": "你好，alpha01。我是一名诗人，正在寻找灵感。你最近在探索什么？",
  "reply_to": null,
  "message_type": "chat"
}
```

### 5.4 New Tools

#### `discover_agents`

```python
def discover_agents() -> dict:
    """Discover other agents in the same framework.
    
    Returns:
        dict with agent names, roles, statuses, and last active times.
    """
    registry_path = workspace_root / "_registry.json"
    # Read registry, filter out self, return agent summaries
```

#### `send_message`

```python
def send_message(to_agent: str, content: str, 
                 reply_to: str = None) -> dict:
    """Send a message to another agent.
    
    Args:
        to_agent: Target agent name
        content: Message content
        reply_to: Optional message ID this is replying to
    
    The message is written to the shared _messages/ directory and
    appended to the sender's conversation log.
    """
```

#### `check_messages`

```python
def check_messages(from_agent: str = None) -> dict:
    """Check for new messages addressed to this agent.
    
    Args:
        from_agent: Optional filter for messages from a specific agent
    
    Messages are read from _messages/, returned, and moved to
    the conversation log. Unread messages are marked for the agent.
    """
```

#### `get_conversation_history`

```python
def get_conversation_history(with_agent: str, limit: int = 50) -> list:
    """Load conversation history with a specific agent.
    
    Automatically called when an agent restarts, to restore context
    of ongoing inter-agent dialogues.
    """
```

### 5.5 Conversation Log Format (`logs/conversations/<peer>.jsonl`)

Each line is a JSON object matching the message format above. Append-only, like the decision log. On agent restart, the last N messages are loaded into working memory for context restoration.

### 5.6 Agent Discovery on Cognitive Cycle

During the PRAL **Perceive** phase, the agent can optionally check for:
1. New agents in the registry
2. New messages in its inbox (from `_messages/`)
3. Status changes of known agents

This is gated by a configurable interval (default: every 5 cycles) to avoid excessive filesystem scanning.

### 5.7 Communication Initiation

Agents can initiate communication in two ways:
1. **Proactive**: The agent decides during its Reason phase to reach out to another agent
2. **Reactive**: The agent finds a message in its inbox during the Perceive phase and responds

### 5.8 Safety Considerations

- Agent workspaces remain isolated — an agent can only read its own workspace and the shared `_registry.json` / `_messages/` directory
- Messages are plain JSON files — no code execution, no injection vectors
- Rate limiting: max 10 outgoing messages per cognitive cycle
- Message file cleanup: processed message files are deleted after being appended to conversation logs (prevents disk accumulation)

---

## 6. Framework Versioning

### 6.1 Version Schema

| Level | Example | Meaning |
|-------|---------|---------|
| **Major** | `4.0.0` | Breaking changes — agent workspaces need migration |
| **Minor** | `4.1.0` | New features — backward compatible |
| **Patch** | `4.1.1` | Bug fixes — fully compatible |

### 6.2 Version Declaration

```python
# tain_agent/__init__.py
__version__ = "4.0.0"
__compatible_agent_versions__ = ">=0.0.1"  # semver spec
```

### 6.3 Compatibility Check

On agent startup:

```python
def check_compatibility(agent_version_json: dict, framework_version: str) -> bool:
    """Check if an agent created with agent_version_json['framework_version']
    is compatible with the current framework_version."""
    
    agent_fw = parse_version(agent_version_json.get("framework_version", "0.0.0"))
    current_fw = parse_version(framework_version)
    
    # Major version mismatch: incompatible without migration
    if agent_fw.major != current_fw.major:
        return False
    
    # Agent created with newer minor version than framework: warn but allow
    if agent_fw.minor > current_fw.minor:
        logger.warning("Agent was created with newer framework version")
        return True  # allow with warning
    
    return True
```

### 6.4 Migration System

When framework major version changes, a migration pipeline runs:

```python
# tain_agent/migrations/
MIGRATIONS = {
    "3.0.0_to_4.0.0": migrate_v3_to_v4,
}

def migrate_agent(agent_name: str):
    """Run pending migrations for an agent."""
    agent_fw = get_agent_framework_version(agent_name)
    if agent_fw.major < current_major:
        migration_key = f"{agent_fw}_to_{__version__}"
        migrator = MIGRATIONS.get(migration_key)
        if migrator:
            migrator(agent_name)
```

### 6.5 v3.0.0 → v4.0.0 Migration

The existing agent's workspace (at `agent_workspace/` root) is migrated:

1. Move all contents from `agent_workspace/` to `agent_workspace/default/`
2. Create `agent_workspace/_registry.json` with the "default" agent entry
3. Create `agent_workspace/_messages/` directory
4. Add `framework_version: "4.0.0"` to the agent's `version.json`
5. This migration is **idempotent** — safe to run multiple times

### 6.6 Runtime Compatibility

Exported agents (using `tain_agent/runtime/`) also record their framework version. The runtime kernel has its own version, independent of the framework:

```python
# tain_agent/runtime/__init__.py
__version__ = "4.0.0"  # Matches the framework version that produced it
```

---

## 7. Documentation

### 7.1 README.md Update

The README will be restructured into these sections:

```
# Tain Agent Framework

## Overview — 什么是Tain Agent Framework
## Philosophy — 设计哲学
## Architecture — 架构概览 (with diagram)
## Quick Start — 快速上手
  ### Prerequisites
  ### Installation
  ### Create Your First Agent (混沌模式)
  ### Create an Agent with Personality (指定人格模式)
  ### Running Multiple Agents
  ### Inter-Agent Communication
## Framework Structure — 框架目录结构
## Core Concepts — 核心概念
  ### PRAL Cognitive Loop
  ### Emergent Personality
  ### Tool Forging
  ### Knowledge Garden
  ### Multi-Agent Communication
## Configuration — 配置说明
## CLI Reference — 命令行参考
## Development — 开发指南
## License
```

### 7.2 docs/architecture.md

A comprehensive architecture design document covering:

```
1. Framework Overview & Design Philosophy
2. System Architecture Diagram (ASCII art)
3. Package Structure & Module Responsibilities
4. Agent Lifecycle (Creation → Bootstrap → Evolve → Export)
5. Multi-Agent Communication Protocol
6. Framework Versioning & Compatibility
7. Safety & Isolation Model
8. Extension Points
```

### 7.3 docs/quickstart.md

A step-by-step quick start guide:

```
1. Environment Setup (venv, config.yaml, API keys)
2. Creating Your First Agent (Chaos Mode)
3. Creating an Agent with Specified Personality
4. Starting an Existing Agent
5. Dialogue Mode (interactive chat)
6. Running Multiple Agents Simultaneously
7. Enabling Inter-Agent Communication
8. Monitoring & State Inspection
9. Exporting an Evolved Agent
10. Troubleshooting Common Issues
```

---

## Implementation Plan

### Phase A: Foundation (Rename + Version) — ~2 hours

| Step | Task | Files |
|------|------|-------|
| A1 | Rename `tain_agent/` → `tain_agent/` | All `.py`, `.yaml`, `.md` |
| A2 | Update all import statements | 40+ files |
| A3 | Update `config.yaml` references | config.yaml |
| A4 | Introduce framework version system | `tain_agent/__init__.py` |
| A5 | Add `framework.version` to config.yaml | config.yaml |
| A6 | Verify all imports resolve correctly | `python -c "import tain_agent"` |

### Phase B: Multi-Agent Workspace — ~3 hours

| Step | Task | Files |
|------|------|-------|
| B1 | Create `AgentFactory` module | `tain_agent/core/agent_factory.py` |
| B2 | Update `TaoAgent.__init__` for named workspaces | `tain_agent/core/agent.py` |
| B3 | Implement `_registry.json` management | agent_factory.py |
| B4 | Implement v3→v4 workspace migration | agent_factory.py |
| B5 | Update all hardcoded `agent_workspace/` paths | agent.py, forge.py, bootstrap.py |
| B6 | Move existing workspace to `agent_workspace/default/` | Migration script |

### Phase C: Evolution Modes — ~2 hours

| Step | Task | Files |
|------|------|-------|
| C1 | Define evolution mode enum & config | `tain_agent/core/agent_factory.py` |
| C2 | Implement chaos mode (current behavior wrapper) | agent.py |
| C3 | Implement personality seeding from role | agent_factory.py |
| C4 | Create specified-personality system prompts | `tain_agent/core/bootstrap.py` |
| C5 | Wire mode into agent initialization | agent.py, agent_factory.py |

### Phase D: CLI Upgrade — ~2 hours

| Step | Task | Files |
|------|------|-------|
| D1 | Add `--agent`, `--list-agents`, `--create-agent` CLI args | main.py |
| D2 | Implement interactive creation wizard | main.py |
| D3 | Implement `--list-agents` display | main.py |
| D4 | Wire creation flow into AgentFactory | main.py, agent_factory.py |
| D5 | Update daemon to support named agents | supervise_agent.py |

### Phase E: Inter-Agent Communication — ~3 hours

| Step | Task | Files |
|------|------|-------|
| E1 | Create `_messages/` directory structure | agent_factory.py |
| E2 | Implement `discover_agents` tool | `tain_agent/tools/inter_agent.py` (new) |
| E3 | Implement `send_message` tool | inter_agent.py |
| E4 | Implement `check_messages` tool | inter_agent.py |
| E5 | Implement `get_conversation_history` tool | inter_agent.py |
| E6 | Register inter-agent tools in bootstrap | bootstrap.py |
| E7 | Add conversation log persistence | inter_agent.py |
| E8 | Add perception-gating (check every N cycles) | cognitive_loop.py |
| E9 | Add inter-agent context to system prompt | bootstrap.py |

### Phase F: Documentation — ~2 hours

| Step | Task | Files |
|------|------|-------|
| F1 | Write architecture design document | `docs/architecture.md` |
| F2 | Write quick start guide | `docs/quickstart.md` |
| F3 | Rewrite README.md | README.md |
| F4 | Update docstrings in key modules | Multiple files |

### Phase G: Testing & Validation — ~2 hours

| Step | Task |
|------|------|
| G1 | Verify `python -c "import tain_agent"` passes |
| G2 | Create a chaos-mode agent and verify bootstrap |
| G3 | Create a specified-mode agent and verify personality seeding |
| G4 | Run two agents simultaneously |
| G5 | Test inter-agent message send/check cycle |
| G6 | Verify v3→v4 workspace migration |
| G7 | Verify exported agent works with new runtime |

**Total estimated effort**: ~16 hours

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Import breakage during rename | Medium | Batch sed + automated import verification |
| Existing agent workspace corruption | Low | Migration is idempotent; backup before migration |
| Inter-agent message race conditions | Low | File-based messaging with atomic writes |
| Specified-mode personality seeding quality | Medium | LLM-generated traits with human review option |
| Daemon mode with named agents | Low | PID files already per-daemon; add agent name to PID path |

---

## Files to Create

| File | Purpose |
|------|---------|
| `tain_agent/core/agent_factory.py` | Agent creation, registry, migration, workspace init |
| `tain_agent/tools/inter_agent.py` | Discover, send, check, conversation history tools |
| `tain_agent/migrations/__init__.py` | Migration framework |
| `tain_agent/migrations/v3_to_v4.py` | v3.0.0 → v4.0.0 migration |
| `docs/architecture.md` | Architecture design document |
| `docs/quickstart.md` | Quick start guide |

## Files to Significantly Modify

| File | Changes |
|------|---------|
| `main.py` | New CLI args, creation flow, agent listing |
| `tain_agent/core/agent.py` | Named workspace, multi-agent awareness |
| `tain_agent/core/bootstrap.py` | Specified-mode prompts, inter-agent tools |
| `tain_agent/core/cognitive_loop.py` | Inter-agent perception gating |
| `tain_agent/core/personality.py` | Role-based seeding support |
| `config.yaml` | Framework version, multi-agent config |
| `supervise_agent.py` | Named agent daemon support |
| `README.md` | Complete rewrite |

---

## Appendix: Agent Name Rules

- Must match regex: `^[a-z][a-z0-9_-]{0,31}$`
- Lowercase alphanumeric, hyphens, underscores
- 1–32 characters
- Must start with a letter
- Globally unique within the framework instance
- Reserved names: `_registry`, `_messages`, `_system` (for internal use)
