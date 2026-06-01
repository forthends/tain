# Tain Agent Framework

> 道生一，一生二，二生三，三生万物。

A practical AI agent framework with multi-provider LLM support, safe tool-use execution, behavioral evolution tracking, and inter-agent communication. Agents operate in isolated workspaces and evolve through **framework-measured behavioral metrics** — not LLM self-evaluation.

**v0.5.0** — AST Sandbox · Honest Evolution · Drive System · Multi-Agent Bus · Web UI

[Safety Model](docs/SAFETY.md) · [Evolution Design](docs/EVOLUTION.md) · [Architecture](docs/architecture.md)

---

## Quick Start

```bash
# Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Configure your API key
export MINIMAX_API_KEY="your-key"

# Create and start your first agent
python main.py --create-agent

# Or create one with a predefined role
python main.py --create-agent
# → Choose mode 2 (Specified)
# → Role: 浪漫主义诗人
# → Description: 随性、浪漫的现代诗人，目标是用诗歌慰藉人性

# Start an existing agent
python main.py --agent poet

# Launch Web UI
python -m uvicorn webui.app:create_app --host 0.0.0.0 --port 8000 --factory
```

See [Quick Start Guide](docs/quickstart.md) for detailed instructions.

---

## Core Features

### Behavioral Evolution Tracking

Agents operate through the PRAL cognitive cycle (**P**erceive → **R**eason → **A**ct → **L**earn). The framework measures real behavioral metrics — tool success rates, action diversity, drive intensities — rather than relying on LLM self-evaluation. Personality traits emerge from observed behavior patterns, not prompted introspection.

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

## What's New in v0.5.0

### Honest Evolution

- **Framework-measured metrics** — evolution quality is judged by tool success rates, action diversity, and drive intensity — not LLM self-evaluation
- **PRAL four-phase run loop** — `run()` split into `_perceive()` / `_reason()` / `_act()` / `_learn()` with clear boundaries
- **Quality gates** — S1 and S4 explicitly labeled "no LLM participation"; emergence verifier uses zero LLM calls

### Security Hardening

- **Path traversal fix** — knowledge content endpoint guards against directory traversal
- **XSS protection** — Markdown rendering now escapes HTML before regex substitutions
- **Command injection prevention** — `shell=True` replaced with `shlex.split()` + `shell=False`
- **SSRF protection** — `web_fetch` validates URLs against dangerous schemes, private IPs, internal hosts
- **API authentication** — API key middleware for Web UI endpoints
- **Rate limiting** — token bucket per IP (60 req/min) on chat endpoints

### Architecture Improvements

- **Shared chat engine** — `ChatEngine` extracted to `tain_agent/core/chat.py`, breaking ACP ↔ Web UI circular dependency
- **Dialogue split** — 553-line `dialogue.py` → `streaming.py` + `conversation_store.py` + `chat.py`
- **Mixin protocols** — explicit interface contracts for Mixin dependencies
- **Config validation** — Pydantic schema validates `config.yaml` at startup
- **Process manager** — unified agent lifecycle (start/stop/restart) abstraction

### MCP & ACP Integration

- **MCP integration** — dynamic tool discovery from external MCP servers over stdio transport
- **ACP protocol** — JSON-RPC over stdio for embedding agents in external editors
- **Background manager** — async subprocess lifecycle for long-running commands

### Infrastructure

- **Unified retry** — `llm_retry_call` with exponential backoff + jitter for LLM API calls
- **Structured logging** — `logging` module replaces all `print()` statements
- **Agent caching** — mtime-based invalidation prevents redundant re-initialization
- **Atomic writes** — `tempfile + rename` for all JSON persistence
- **Docker support** — multi-stage build with docker-compose
- **326 tests** — up from 282, covering pipeline, LLM parsing, Web UI routes, and integration

Full changelog: [docs/changelog/v0.5.0.md](docs/changelog/v0.5.0.md)

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
│                     TaoAgent                             │
│  Personality · Drives · PRAL Loop · ToolRegistry        │
│  ToolForge · ImprovementLoop · Memory · DecisionLog     │
│  LLMLogger · RetryConfig · CognitiveLoop · Config       │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              agent_workspace/<name>/                     │
│  logs/ · knowledge/ · forged_tools/ · reports/ · state/ │
│  memory/agent_notes.jsonl · skills/ · version.json      │
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
  core/                      # Agent core
    agent.py                 # TaoAgent — main agent class (5 Mixins, PRAL loop)
    agent_cognition.py       # Cognitive loop enrichment
    agent_config.py          # Configuration loading + identity
    agent_factory.py         # Multi-agent lifecycle management
    agent_phase.py           # Phase management + action tracking
    agent_protocols.py       # Mixin interface contracts
    agent_subsystems.py      # Subsystem initialization
    agent_tools.py           # Tool execution + decision logging
    bootstrap.py             # Tool registration closures
    chat.py                  # Shared chat engine (Web UI + ACP)
    cognitive_loop.py        # PRAL cognitive cycle
    config_schema.py         # Pydantic config validation
    conversation.py          # Token-aware context management
    drives.py                # Intrinsic motivation engine
    environment.py           # Environment scanning
    llm.py                   # Multi-provider LLM backend with retry
    llm_logger.py            # Structured JSONL call logging
    logging_config.py        # Logging infrastructure
    memory.py                # Agent memory
    message_bus.py           # Inter-component communication
    personality.py           # Emergent personality system
    retry.py                 # Exponential backoff retry + LLM retry
    time_utils.py            # Timezone-aware datetime utilities
  tools/                     # Tool system
    base.py                  # Tool abstract base class
    primal.py                # Primal tools (file ops, web, code exec, knowledge)
    forge.py                 # Tool forge (7-stage safety pipeline)
    templates.py             # Reusable tool templates
    mcp_loader.py            # MCP server integration over stdio
    background_manager.py    # Async background process lifecycle
    inter_agent.py           # Agent-to-agent communication
    registry.py              # Tool registry with timeout protection
  evolution/                 # Self-evolution (pipeline, improvement, exporter)
  acp/                       # ACP protocol (JSON-RPC over stdio)
  runtime/                   # Standalone runtime kernel for exported agents
  utils/                     # Utilities
    token_utils.py           # Token-aware smart truncation
    persist.py               # Atomic write utilities
  storage_registry.py        # Semantic storage path resolution
webui/                       # Web UI (FastAPI + Jinja2 + HTMX + Alpine.js)
  app.py                     # FastAPI application
  agent_cache.py             # Agent instance cache
  streaming.py               # SSE streaming layer
  conversation_store.py      # Conversation persistence
  dialogue.py                # Compatibility re-exports
  auth.py                    # API key middleware
  rate_limit.py              # Token bucket rate limiter
  process.py                 # Agent lifecycle process manager
  data.py                    # Data access layer
  render.py                  # Content rendering
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
tests/                       # Test suite (326 tests, 25 files)
```

---

## CLI Reference

| Command                                  | Description                     |
|------------------------------------------|---------------------------------|
| `python main.py --agent <name>`          | Start an agent (creates if new) |
| `python main.py --list-agents`           | List all registered agents      |
| `python main.py --create-agent`          | Interactive creation wizard     |
| `python main.py --agent <name> --state`  | Print agent state report        |
| `python main.py --agent <name> --log`    | View agent decision log         |
| `python main.py --agent <name> --daemon` | Run as background daemon        |
| `python main.py --daemon --stop`         | Stop the daemon                 |
| `python main.py --daemon --status`       | Check daemon status             |
| `uvicorn webui.app:create_app --factory` | Start Web UI on port 8000       |

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
- [Optimization Backlog](docs/optimization-backlog.md) — Planned improvements

## Requirements

- Python 3.10+
- LLM API access (Anthropic, DeepSeek, OpenAI, or MiniMax)
- Dependencies: `anthropic`, `openai`, `pyyaml`, `duckduckgo_search`, `requests`, `rich`, `fastapi`, `uvicorn`, `jinja2`, `pydantic`
- Optional: `tiktoken` (for accurate token counting), `pytest-asyncio` (for async tests)

## License

MIT — see [LICENSE](LICENSE) for details.
