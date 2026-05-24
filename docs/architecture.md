# Tain Agent Framework — Architecture Design

**Version**: 0.4.0
**Date**: 2026-05-24

---

## 1. Overview

The Tain Agent Framework is a platform for building and running self-evolving AI agents. Each agent operates in an isolated workspace, can be started with or without a predefined personality, forges its own tools, builds knowledge, and evolves through continuous self-improvement.

### Design Philosophy

```
道生一  →  Framework provides the empty vessel (Bootstrap)
一生二  →  Agent discovers its identity through action (Self-Define)
二生三  →  Agent creates tools, knowledge, and goals (Evolve)
三生万物 →  Multi-agent collaboration, export, infinite evolution
```

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        main.py (CLI)                         │
│  --agent, --list-agents, --create-agent, --dialogue, etc.   │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│                  AgentFactory                                 │
│  create / exists / list / registry / compatibility           │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│                    TaoAgent                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │ Personality  │  │ Drive System │  │ Cognitive Loop    │   │
│  │ (emergent)   │  │ (4 drives)   │  │ (PRAL state mach) │   │
│  └─────────────┘  └──────────────┘  └───────────────────┘   │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │ ToolRegistry│  │ ToolForge    │  │ ImprovementLoop   │   │
│  │ (safe exec)  │  │ (6-stage)    │  │ (6-dim triggers)  │   │
│  └─────────────┘  └──────────────┘  └───────────────────┘   │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │ Memory      │  │ DecisionLog  │  │ ConversationMgr   │   │
│  │ (dual-tier) │  │ (append-only)│  │ (checkpointed)    │   │
│  └─────────────┘  └──────────────┘  └───────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Package Structure

```
tain_agent/                        # Framework package
  __init__.py                      # __version__ = "0.4.0"
  decision_log.py                  # Append-only JSONL decision log

  core/                            # Central nervous system
    agent.py                       # TaoAgent class — main orchestrator
    agent_factory.py               # Agent lifecycle management (v0.4.0)
    bootstrap.py                   # Tool registration + system prompts
    cognitive_loop.py              # PRAL cognitive loop state machine
    pral_bridge.py                 # CognitiveBridge: wraps agent.run()
    dialogue.py                    # DialogueBridge: interactive REPL
    personality.py                 # Emergent personality (7 categories)
    drives.py                      # Drive system (4 intrinsic drives)
    trials.py                      # Trial scheduler (5 formative trials)
    memory.py                      # Dual-tier memory (working + long-term)
    conversation.py                # Conversation manager (checkpointed)
    llm.py                         # LLM backend abstraction (4 providers)
    environment.py                 # Environment scanner + diversity engine
    external_world.py              # External API subscriptions
    time_utils.py                  # Timezone-aware utilities
    session_memory.py              # Cross-session user recognition
    companion_shrine.py            # Non-code presence marker

  tools/                           # Extensible tool system
    registry.py                    # ToolRegistry (thread-pool timeout exec)
    forge.py                       # ToolForge (6-stage safe pipeline)
    primal.py                      # 10 primal tools (read/write/search/execute)
    inter_agent.py                 # Inter-agent communication tools (v0.4.0)

  evolution/                       # Self-evolution subsystem
    goal.py                        # Goal system with lifecycle management
    pipeline.py                    # SelfImprovementPipeline (5-stage)
    improvement_loop.py            # ImprovementLoop (6-dimension triggers)
    self_modify.py                 # SelfModify (workspace-scoped)
    capability.py                  # CapabilityRegistry with gap analysis
    lineage.py                     # LineageTracker (SHA-256 events)
    reporter.py                    # EvolutionReporter (version bump + report)
    sub_agent.py                   # Sub-agent sandbox (5 drive profiles)
    emergence_verifier.py          # 6 emergence verification checks
    quality_gate.py                # 15-gate export quality system
    exporter.py                    # 5-step export pipeline
    importer.py                    # Return-to-factory import pipeline
    skill_exporter.py              # agentskills.io Skill export

  runtime/                         # Standalone runtime kernel (no framework deps)
    __init__.py                    # __version__ independent of framework
    llm.py                         # Multi-provider LLM backends
    tools.py                       # ToolRegistry (isolated)
    memory.py                      # MemoryStore (session lifecycle)
    conversation.py                # ConversationManager
    identity.py                    # Identity (personality + drives)
    tui.py                         # Rich/Plain TUI
```

---

## 4. Workspace Architecture (Multi-Agent)

```
agent_workspace/                     # Root for ALL agents
  _registry.json                     # Global agent registry
  _messages/                         # Shared inter-agent message bus
    <from>_to_<to>_<msgid>.json     # Individual message files

  <agent_name>/                      # Per-agent isolated workspace
    version.json                     # {agent_version, framework_version,
                                     #  evolution_mode, role, role_description}
    personality.json                 # Personality state (7 categories)
    state/                           # Runtime state snapshots
    logs/
      decisions.jsonl                # Decision log (append-only)
      lineage.jsonl                  # Evolution lineage events
      memory.json                    # Long-term memory store
      conversations/                 # Inter-agent conversation logs
        <peer_name>.jsonl           # Per-peer conversation history
    knowledge/                       # Knowledge garden documents
    forged_tools/                    # Agent-forged Python tools
    reports/                         # Evolution reports
    files/                           # General file storage
```

---

## 5. Agent Lifecycle

### 5.1 Creation

Two evolution modes:

| Mode | Personality | System Prompt | Use Case |
|------|-------------|---------------|----------|
| **Chaos** | Empty — agent self-awakens | Standard bootstrap | Exploration, emergent identity |
| **Specified** | Seeded from role + description | Role-aware bootstrap | Task-specific agents |

### 5.2 Bootstrap Phase

```
Agent Created
     │
     ▼
┌──────────┐    ┌──────────┐    ┌──────────┐
│ Explore   │───→│ Act      │───→│ Reflect  │
│ workspace │    │ use tools│    │ patterns │
└──────────┘    └──────────┘    └──────────┘
     │                               │
     └─── trials (5 types) ──────────┘
                     │
                     ▼
              Self-Define Phase
```

### 5.3 PRAL Cognitive Cycle

```
┌──────────────────────────────────────────────┐
│  Perceive  →  Reason  →  Act  →  Learn       │
│                                              │
│  Scan env    LLM thinks  Execute  Reflect    │
│  Check msgs  Choose      tools    Update     │
│  Read state  Plan        Forge    personality│
└──────────────────────────────────────────────┘
         ↑                                    │
         └────────────── cycle ───────────────┘
```

---

## 6. Inter-Agent Communication Protocol

### 6.1 Discovery

Agents register in `_registry.json` at creation. `discover_agents()` reads this registry, excluding the caller.

### 6.2 Messaging

```
Agent A (poet)                        Agent B (alpha01)
─────────────                         ────────────────
send_message(to="alpha01",            check_messages()
  content="你好!")
       │                                    │
       ▼                                    ▼
_messages/poet_to_alpha01_msg_abc.json ──→ read + archive to
                                           logs/conversations/poet.jsonl
                                           delete from _messages/
       │
       ▼
logs/conversations/alpha01.jsonl
(appended for A's records)
```

### 6.3 Conversation Persistence

All messages are stored in `logs/conversations/<peer>.jsonl` in append-only JSONL format. On agent restart, `get_conversation_history()` restores context.

### 6.4 Tools

| Tool | Purpose |
|------|---------|
| `discover_agents` | List other agents with roles and statuses |
| `send_message` | Send a message to another agent |
| `check_messages` | Check for new incoming messages |
| `get_conversation_history` | Load past conversation with a peer |

---

## 7. Framework Versioning

### 7.1 Version Schema

- **Major** (4.x.x): Breaking changes — agent workspace migration required
- **Minor** (x.1.x): New features — backward compatible
- **Patch** (x.x.1): Bug fixes — fully compatible

### 7.2 Compatibility

Each agent's `version.json` records the `framework_version` it was created with. On startup, the framework checks compatibility:

- Same major version → compatible
- Different major version → warning, migration needed

### 7.3 Version Files

| File | Purpose |
|------|---------|
| `tain_agent/__init__.py` | Framework version (`__version__ = "0.4.0"`) |
| `agent_workspace/<name>/version.json` | Agent workspace version + framework binding |
| `config.yaml` → `framework.version` | Configured framework version |

---

## 8. Safety & Isolation

### 8.1 Workspace Isolation

- Agent can only read/write within `agent_workspace/<name>/`
- Cannot access project source code
- Cannot access other agents' workspaces (except via message bus)
- Shared access: `_registry.json` (read-only), `_messages/` (write own, read own)

### 8.2 Tool Execution Safety

- All tools run in thread pool with timeout (60s default, 120s for network)
- ToolForge: 6-stage pipeline with AST sandbox, restricted imports, workspace path validation
- SelfModify: protected paths cannot be modified
- No `os.system`, `subprocess`, `exec`, `eval` in forged tools

### 8.3 Message Bus Safety

- Plain JSON files — no code execution
- Messages are signed with sender name
- Processed messages are deleted from bus (no accumulation)
- Rate limiting: 10 outgoing messages per cycle cap (configurable)

---

## 9. Extension Points

- **New tools**: `ToolForge.forge()` 6-stage pipeline or manual registration
- **New evolution triggers**: Add dimension to `ImprovementLoop` trigger config
- **New LLM providers**: Implement backend in `core/llm.py`
- **Custom system prompts**: Add templates to `bootstrap.py`
- **Runtime export**: `Exporter.export()` produces standalone packages
