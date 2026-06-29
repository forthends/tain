# Tain Agent Framework

> 道生一，一生二，二生三，三生万物。

A practical AI agent framework with multi-provider LLM support, safe tool-use execution, behavioral evolution tracking, and inter-agent communication. Agents operate in isolated workspaces and evolve through **framework-measured behavioral metrics** — not LLM self-evaluation.

**v0.11.0** — Autonomous Evolution · Kernel/Plugin Architecture · Closed Evolution Loop

[Safety Model](docs/SAFETY.md) · [Evolution Design](docs/EVOLUTION.md) · [Architecture](docs/architecture.md) · [Changelog](docs/changelog/v0.10.0.md)

---

## Capability Status

| Capability | Status | Notes |
|---|---|---|
| Autonomous tool generation | 🧪 Experimental | Gated, rate-limited, auto-rollback on failure. Quality under active improvement. |
| Behavior contract enforcement | ✅ Stable | AST-level import/call validation for sandbox security. |
| Multi-provider LLM (Anthropic, OpenAI) | ✅ Stable | Via official SDKs. |
| WebUI (SSE streaming) | ✅ Stable | FastAPI + SSE, real-time conversation view. |
| CLI (`tain run` / `tain package`) | ✅ Stable | uv-based single-command launch. |
| MCP/ACP server | 🚧 Beta | Protocol support, limited tool coverage. |
| Package evolution (evolve/mutate/rollback) | 🧪 Experimental | 5-stage loop with contract enforcement. Active development. |
| Cross-platform (Linux/macOS/Windows) | 🚧 Beta | Core path tested; Windows sandbox env added in 0.11.0. |

---

## 安装 uv

`tain` 启动脚本依赖 [uv](https://docs.astral.sh/uv/) 管理 Python 依赖与虚拟环境（首次运行时自动同步）。

```bash
# macOS
brew install uv

# Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
winget install astral-sh.uv
```

---

## Quick Start

```bash
# 1. 装 uv（参见上文「安装 uv」）

# 2. 配置 API key
export MINIMAX_API_KEY="your-key"

# 3. 启动
./tain run poet            # 启动 agent（不存在则自动进入创建向导）
./tain webui               # 启动 Web UI，自动开浏览器

# 其他常用
./tain list                # 列出所有 agent
./tain new                 # 交互式创建 agent
./tain state poet          # 查看 agent 状态
./tain log poet            # 查看决策日志
./tain help                # 完整帮助
```

> **首次启动**会触发 `uv sync` 自动安装依赖（~30s），后续启动毫秒级。
>
> Windows 用户使用 `tain.cmd`：`tain.cmd run poet`、`tain.cmd webui` 等同效。

如需传统方式（不经 `tain`）：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python main.py --agent poet
```

See [Quick Start Guide](docs/quickstart.md) for detailed instructions.

---

## Core Features

### Behavioral Evolution Tracking

Agents operate through the PRAL cognitive cycle (**P**erceive → **R**eason → **A**ct → **L**earn) orchestrated by `AgentKernel`. The framework measures real behavioral metrics — tool success rates, action diversity, drive intensities — rather than relying on LLM self-evaluation.

> ⚠️ **Experimental:** The autonomous evolution loop runs as a rate-limited, quota-bounded cycle triggered within the PRAL `_learn()` phase. It is currently scoped to tool generation with behavior contract enforcement and automatic rollback on quality degradation. Continuous background evolution is planned for a future release. See [EVOLUTION.md](docs/EVOLUTION.md) for the roadmap.

### Dual Creation Modes

- **Chaos Mode (混沌模式)**: The agent starts with an empty personality, developing identity through tool usage patterns.
- **Specified Mode (指定人格模式)**: The agent starts with a predefined role, which still adapts through experience.

### Multi-Agent Architecture

Run multiple agents simultaneously, each in its own isolated workspace (`agent_workspace/<name>/`). Agents register in a shared registry and can discover each other.

### Inter-Agent Communication

Agents can discover peers, send messages, check their inbox, and maintain persistent conversation histories. Communication uses a file-based message bus — no sockets or external services required.

### Safe Tool Forging

Tools are created through a **7-stage safety pipeline**: NameCheck → AST Import Whitelist → AST Call Blacklist → PathValidation → Compile → Subprocess Smoke Test → Register. All forged tools run in subprocess isolation with a 10-second timeout. See [Safety Model](docs/SAFETY.md).

### Web UI

Real-time SSE-streamed chat with agents, tabbed dashboards for decision logs and knowledge, agent lifecycle controls, and multi-agent management. See [Web UI](#web-ui) section.

### Safety & Isolation

- Complete workspace isolation — agents cannot read or modify project source
- Protected paths prevent self-modification of critical framework files
- Thread-pool timeout on all tool execution
- AST-level sandboxing on forged tools

---

## What's New in v0.10.0

### Autonomous Evolution Loop

The framework now includes an experimental **8-stage pipeline** (GAP_DETECT → SPEC_DESIGN → CODE_GENERATE → CONTRACT_CHECK → SANDBOX_FORGE → REGISTER → ONLINE_VERIFY → EVALUATE) with three-layer safety: sandbox AST validation, **behavior contract** enforcement (LLM-generated code must declare allowed imports and side effects), and automatic rollback on quality degradation. This pipeline is rate-limited, gated, and supervised — it is not a fully autonomous system.

### Architecture Migration: Mixin → Kernel/Plugin

The old `TaoAgent` + 6 Mixin architecture (~2,788 lines) has been replaced by a clean **AgentKernel** + **8 Plugin** system. Plugins implement an explicit `PluginProtocol` interface contract, eliminating 60+ `hasattr()` checks. All consumers (CLI, Web UI, ACP, dialogue) now use `AgentKernel` directly.

### Stabilization

- Version unified across all modules (`from tain_agent import __version__`)
- Dead code removed (SELF_DEFINE phase, external_world/trial_scheduler stubs)
- `estimate_tokens` consolidated from 4 definitions to 1
- Config parameters now actually drive behavior (exploration cycles, action categories)
- LLM retry logic unified with exponential backoff + jitter
- **766 tests** (up from 614, +25%) covering evolution, personality, forge, and LLM parsing

Full changelog: [docs/changelog/v0.10.0.md](docs/changelog/v0.10.0.md)

---

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                     main.py (CLI)                        │
│  --agent · --list-agents · --create-agent · --dialogue  │
│  --webui · --daemon · --export · --state · --log        │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                   AgentFactory                           │
│  create / exists / list / registry / compatibility      │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                    AgentKernel                           │
│  PRALLoop · LifecycleManager · Dispatch                 │
│  ┌──────────┬──────────┬──────────┬──────────┐          │
│  │ Identity │  Memory  │   Tool   │  Skill   │          │
│  │ Plugin   │  Plugin  │  Plugin  │  Plugin  │          │
│  ├──────────┼──────────┼──────────┼──────────┤          │
│  │Knowledge │ Workflow │Collabor. │Evaluation│          │
│  │ Plugin   │  Plugin  │  Plugin  │  Plugin  │          │
│  └──────────┴──────────┴──────────┴──────────┘          │
│  AutonomousEvolutionLoop · BehaviorContract             │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              agent_workspace/<name>/                     │
│  logs/ · knowledge/ · forged_tools/ · diagnostics/      │
│  state/ · memory/ · skills/ · version.json              │
└─────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              agent_workspace/_messages/                  │
│         Inter-Agent Communication Bus                    │
└─────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              External Integration Layer                  │
│  MCP Client (stdio) · ACP Server (stdio) · Web UI (SSE) │
└─────────────────────────────────────────────────────────┘
```

Full architecture: [docs/architecture.md](docs/architecture.md)

---

## Project Structure

```plaintext
tain_agent/                  # Framework package
  kernel/                    # Backward-compatible shim layer
    __init__.py              # AgentKernel — delegates to AgentRuntime
    dispatch.py              # Cross-plugin event routing
    protocol.py              # PluginProtocol, AgentContext, HealthStatus
  runtime/                   # Actual execution engine
    __init__.py              # AgentRuntime — package-based kernel
    pral.py                  # PRAL cognitive loop (Perceive→Reason→Act→Learn)
    prompts.py               # System prompt templates
    plugin_loader.py         # Plugin assembly with version checking
  plugins/                   # Plugin implementations
    identity/                # Agent identity + personality adapter
    memory/                  # Episodic + semantic memory
    tool/                    # ToolRegistry + ToolForge + ForgeCycle
    skill/                   # Skill composition
    knowledge/               # Knowledge graph + GoalManager
    workflow/                # Workflow engine
    collaboration/           # Inter-agent communication bus
    evaluation/              # Quality evaluation + export readiness
  core/                      # Core subsystems
    agent_factory.py         # Multi-agent lifecycle management
    chat.py                  # Shared chat engine (Web UI + ACP)
    config_schema.py         # Pydantic config validation (v2)
    conversation.py          # Token-aware context management
    dialogue.py              # Human-AI dialogue bridge (REPL)
    drives.py                # Intrinsic motivation engine
    environment.py           # Environment scanning
    llm.py                   # Multi-provider LLM backend with retry
    llm_logger.py            # Structured JSONL call logging
    logging_config.py        # Logging infrastructure
    memory.py                # Long-term memory store
    message_bus.py           # Inter-component communication
    personality.py           # Emergent personality system
    retry.py                 # Exponential backoff retry + LLM retry
    session_memory.py        # Human session awareness
    time_utils.py            # Timezone-aware datetime utilities
  evolution/                 # Self-evolution system
    autonomous_loop.py       # AutonomousEvolutionLoop — 8-stage closed cycle
    behavior_contract.py     # BehaviorContract — AST compliance verification
    forge_cycle.py           # ForgeCycle — 5-stage tool forging orchestrator
    pipeline.py              # SelfImprovementPipeline (manual/export use)
    quality_gate.py          # Export quality gate (7H + 9S)
    emergence_verifier.py    # Behavioral emergence verification
    lineage.py               # Evolution event tracking
    capability.py            # Capability registry + desired capabilities
    exporter.py              # Agent export
    importer.py              # Agent import
    introspection.py         # get_self_profile lightweight API
    diagnostic_feedback.py   # Agent→framework diagnostic channel
    goal.py                  # Goal system
    reporter.py              # Evolution metrics reporter
    self_modify.py           # Self code modification
    vector_store.py          # Knowledge vector storage
    dependency_manager.py    # Package dependency resolution
    sub_agent.py             # Sub-agent spawning
    skill_exporter.py        # Skill export logic
  package/                   # Package model — agent export/import unit
    __init__.py              # AgentPackage, PackageRegistry, PackageKind
    manifest.py              # Manifest parser, hash verification
    evolution.py             # EvolutionResult, Mutation, evolve() cycle
  tools/                     # Tool system
    primal.py                # Primal tools (file ops, web, code exec, knowledge)
    forge.py                 # Tool forge (7-stage safety pipeline)
    sandbox_allowlist.py     # Shared sandbox import/API allowlist
    registry.py              # Tool registry with timeout protection
    mcp_loader.py            # MCP server integration over stdio
    background_manager.py    # Async background process lifecycle
    inter_agent.py           # Agent-to-agent communication
    forged/                  # Sandbox testing for agent-forged tools
  acp/                       # ACP protocol (JSON-RPC over stdio)
  mcp/                       # MCP server (IDE embedding)
  utils/                     # Utilities
    token_utils.py           # Token-aware smart truncation
    persist.py               # Atomic write utilities
webui/                       # Web UI (FastAPI + Jinja2 + HTMX + Alpine.js)
  app.py                     # FastAPI application
  agent_cache.py             # AgentKernel instance cache
  data.py                    # Data access layer
  routes/                    # API routes (chat, agents, pages)
  templates/                 # Jinja2 templates
agent_workspace/             # All agent workspaces (gitignored)
  _registry.json             # Global agent registry
  <agent_name>/              # Per-agent isolated workspace
main.py                      # CLI entry point
supervise_agent.py           # Daemon process manager
config.yaml                  # Framework configuration
Dockerfile                   # Multi-stage container build
docker-compose.yml           # Container orchestration
docs/                        # Documentation
  architecture.md            # Full architecture design
  quickstart.md              # Getting started guide
  changelog/                 # Version changelogs
  EVOLUTION.md               # Evolution design philosophy
  SAFETY.md                  # Safety model
  runtime.md                 # Runtime kernel documentation
tests/                       # Test suite (829 tests)
```

---

## CLI Reference

| `tain` 命令                       | `python main.py` 旧用法                          | 描述                              |
|-----------------------------------|--------------------------------------------------|-----------------------------------|
| `./tain run <name>`               | `python main.py --agent <name>`                  | 启动 agent（不存在则创建）        |
| `./tain list`                     | `python main.py --list-agents`                   | 列出所有已注册 agent              |
| `./tain new`                      | `python main.py --create-agent`                  | 交互式创建向导                    |
| `./tain state <name>`             | `python main.py --agent <name> --state`          | 打印 agent 状态                   |
| `./tain log <name>`               | `python main.py --agent <name> --log`            | 查看 agent 决策日志               |
| `./tain export <name>`            | `python main.py --agent <name> --export`         | 导出 agent 为独立包               |
| `./tain dialogue <name>`          | `python main.py --agent <name> --dialogue`       | REPL 对话模式                     |
| `./tain daemon start <name>`      | `python main.py --daemon start --agent <name>`   | 启动守护进程                      |
| `./tain daemon stop`              | `python main.py --daemon stop`                   | 停止守护进程                      |
| `./tain daemon status`            | `python main.py --daemon status`                 | 查看守护进程状态                  |
| `./tain webui [port]`             | `python main.py --webui --port 8000`             | 启动 Web UI（自动开浏览器）       |
| `./tain reset`                    | —                                                | 删除 `.venv`（下次启动自动重同步）|
| `./tain help`                     | `python main.py --help`                          | 显示帮助                          |

> Windows 用户把 `./tain` 换成 `tain.cmd` 即可（其余参数完全一致）。

---

## Configuration

`config.yaml` supports multi-level loading with deep merge:

```text
Priority (highest → lowest):
  1. --config CLI flag
  2. ./config.yaml (project root)
  3. ~/.tain/config.yaml (user-level)
  4. Built-in package defaults

Per-agent overrides:
  agent_workspace/<name>/agent.yaml
```

Key config sections:

```yaml
llm:
  provider: "minimax"
  model: "MiniMax-M2.7"
  retry:
    enabled: true
    max_retries: 3
    initial_delay: 1.0
    max_delay: 30.0

exploration:
  max_exploration_cycles: 10
  min_bootstrap_cycles: 5
  min_action_categories: 2

conversation:
  token_limit: 80000
  model_context_window: 131072

logging:
  directory: "tain_agent/logs"
  decision_log_file: "decisions.jsonl"
```

---

## Documentation

- [Architecture Design](docs/architecture.md) — Full system architecture and design
- [Quick Start Guide](docs/quickstart.md) — Step-by-step getting started
- [Evolution Design](docs/EVOLUTION.md) — Evolution philosophy and implementation
- [Safety Model](docs/SAFETY.md) — Security model and known limitations
- [Runtime Kernel](docs/runtime.md) — Standalone runtime documentation
- [Changelog](docs/changelog/) — Version history and release notes

## Requirements

- Python 3.10+
- LLM API access (Anthropic, DeepSeek, OpenAI, or MiniMax)
- Dependencies: `anthropic`, `openai`, `pyyaml`, `duckduckgo_search`, `requests`, `rich`, `fastapi`, `uvicorn`, `jinja2`, `pydantic`
- Optional: `tiktoken` (for accurate token counting), `pytest-asyncio` (for async tests)

## License

MIT — see [LICENSE](LICENSE) for details.
