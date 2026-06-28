# Tain Agent Framework — Architecture Design

**Version**: 0.10.0
**Date**: 2026-06-27

---

## 1. Overview

The Tain Agent Framework is a platform for building and running self-evolving AI agents. Each agent operates in an isolated workspace, can be started with or without a predefined personality, forges its own tools, builds knowledge, and evolves through continuous self-improvement.

### Design Philosophy

```
道生一  →  Framework provides the empty vessel
一生二  →  Agent explores its environment and identity (explore phase)
二生三  →  Agent works: forges tools, builds knowledge, evolves (work phase)
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
│                    AgentKernel                                │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ PRALLoop        │  │LifecycleMgr │  │ Dispatch          │ │
│  │ (Perceive→      │  │ (Plugin      │  │ (Event routing)   │ │
│  │  Reason→Act→    │  │  lifecycle)  │  │                   │ │
│  │  Learn)         │  │              │  │                   │ │
│  └────────────────┘  └──────────────┘  └──────────────────┘ │
│  ┌────────┬────────┬────────┬────────┬────────┬────────┐    │
│  │Identity│ Memory │  Tool  │ Skill  │Knowled.│Workflow│    │
│  │ Plugin │ Plugin │ Plugin │ Plugin │ Plugin │ Plugin │    │
│  ├────────┼────────┼────────┼────────┼────────┼────────┤    │
│  │Collab. │ Eval.  │ Drives │ConvMgr │ AutoEvo│Behav.  │    │
│  │ Plugin │ Plugin │ System │        │ Loop   │Contract│    │
│  └────────┴────────┴────────┴────────┴────────┴────────┘    │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Package Structure

```
tain_agent/                        # Framework package
  __init__.py                      # __version__ = "0.10.0"
  decision_log.py                  # Append-only JSONL decision log
  storage_registry.py              # Semantic storage path resolution

  kernel/                          # AgentKernel — sole entry point
    __init__.py                    # AgentKernel class
    pral.py                        # PRALLoop (Perceive→Reason→Act→Learn)
    lifecycle.py                   # LifecycleManager (Plugin lifecycle)
    dispatch.py                    # Dispatch (cross-plugin event routing)
    protocol.py                    # PluginProtocol (@runtime_checkable)
    factories.py                   # STANDARD_FACTORIES (7 Plugin mapping)
    prompts.py                     # System prompts (migrated from bootstrap.py)

  plugins/                         # Plugin implementations (PluginProtocol)
    identity/                      # Agent identity + personality adapter
    memory/                        # Episodic + semantic memory
    tool/                          # ToolRegistry + ToolForge + ClosedForgeCycle
    skill/                         # Skill composition
    knowledge/                     # Knowledge graph + GoalManager
    workflow/                      # Workflow engine
    collaboration/                 # Inter-agent communication bus
    evaluation/                    # Quality gate + export readiness

  core/                            # Core subsystems
    agent_factory.py               # Agent lifecycle management
    chat.py                        # Shared chat engine (Web UI + ACP)
    cognitive_loop.py              # PRAL cognitive loop enrichment
    config_schema.py               # Pydantic v2 config validation
    conversation.py                # Token-aware context management
    dialogue.py                    # DialogueBridge: interactive REPL
    drives.py                      # Drive system (4 intrinsic drives)
    environment.py                 # Environment scanner
    llm.py                         # LLM backend abstraction (4 providers)
    llm_logger.py                  # Structured JSONL call logging
    logging_config.py              # Logging infrastructure
    memory.py                      # Long-term memory store
    message_bus.py                 # Inter-component communication
    personality.py                 # Emergent personality (7 categories)
    retry.py                       # Exponential backoff + jitter retry
    session_memory.py              # Cross-session user recognition
    time_utils.py                  # Timezone-aware datetime utilities

  tools/                           # Extensible tool system
    registry.py                    # ToolRegistry (thread-pool timeout exec)
    forge.py                       # ToolForge (7-stage safety pipeline)
    primal.py                      # Primal tools (file ops, web, code exec, knowledge)
    sandbox_allowlist.py           # Shared sandbox import/API allowlist
    mcp_loader.py                  # MCP server integration over stdio
    background_manager.py          # Async background process lifecycle
    inter_agent.py                 # Inter-agent communication tools
    forged/                        # Agent-forged tools

  evolution/                       # Self-evolution subsystem
    autonomous_loop.py             # AutonomousEvolutionLoop (8-stage closed cycle)
    behavior_contract.py           # BehaviorContract (AST compliance verification)
    pipeline.py                    # SelfImprovementPipeline (5-stage)
    quality_gate.py                # Export quality gate (7 hard + 9 scoring)
    emergence_verifier.py          # Behavioral emergence verification (6 checks)
    goal.py                        # Goal system with lifecycle management
    lineage.py                     # LineageTracker (SHA-256 events)
    capability.py                  # CapabilityRegistry with gap analysis
    reporter.py                    # EvolutionReporter (version bump + report)
    sub_agent.py                   # Sub-agent sandbox
    exporter.py                    # Export pipeline
    importer.py                    # Return-to-factory import pipeline
    skill_exporter.py              # agentskills.io Skill export
    introspection.py               # get_self_profile lightweight API
    diagnostic_feedback.py         # Agent→framework diagnostic channel
    dependency_manager.py          # Package dependency resolution
    self_modify.py                 # Workspace-scoped self-modification
    vector_store.py                # Vector embedding storage

  acp/                             # ACP protocol (JSON-RPC 2.0 over stdio)
  mcp/                             # MCP server (IDE embedding)
  utils/                           # Utilities
    token_utils.py                 # Token-aware smart truncation
    persist.py                     # Atomic write utilities

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

### 5.2 Explore Phase

```
Agent Created
     │
     ▼
┌──────────┐    ┌──────────┐    ┌──────────┐
│ Explore   │───→│ Act      │───→│ Reflect  │
│ workspace │    │ use tools│    │ patterns │
└──────────┘    └──────────┘    └──────────┘
     │                               │
     └───────────────────────────────┘
                     │
                     ▼
                Work Phase
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
| `tain_agent/__init__.py` | Framework version (`__version__ = "0.10.0"`) |
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
- ToolForge: 7-stage pipeline with AST sandbox, restricted imports, workspace path validation
- BehaviorContract: LLM-generated tools must declare import/side-effect boundaries; AST-verified before forging
- AutonomousEvolutionLoop: automatic rollback on consecutive failure or quality degradation
- SelfModify: protected paths cannot be modified
- No `os.system`, `subprocess`, `exec`, `eval` in forged tools

### 8.3 Message Bus Safety

- Plain JSON files — no code execution
- Messages are signed with sender name
- Processed messages are deleted from bus (no accumulation)
- Rate limiting: 10 outgoing messages per cycle cap (configurable)

---

## 9. Extension Points

- **New tools**: `ToolForge.forge()` 7-stage pipeline or manual registration via `ToolPlugin`
- **New evolution triggers**: Add dimension to `AutonomousEvolutionLoop.trigger_config`
- **New Plugins**: Implement `PluginProtocol` and register in `STANDARD_FACTORIES`
- **New LLM providers**: Implement backend in `core/llm.py`
- **Custom system prompts**: Add templates to `kernel/prompts.py`
- **Runtime export**: `Exporter.export()` produces standalone packages
