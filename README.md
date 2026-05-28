# Tain Agent Framework

> 道生一，一生二，二生三，三生万物。

A practical AI agent framework with multi-provider LLM support, safe tool-use execution, behavioral evolution tracking, and inter-agent communication. Agents operate in isolated workspaces and evolve through **framework-measured behavioral metrics** — not LLM self-evaluation.

**v0.5.0** — AST Sandbox · Honest Evolution · Drive System · Multi-Agent Bus · Web UI

[Safety Model](docs/SAFETY.md) · [Evolution Design](docs/EVOLUTION.md) · [Architecture](docs/architecture.md)

---

## Quick Start

```bash
# Install
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

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

# Chat with your agent
python main.py --agent poet --dialogue

# Launch Web UI
python main.py --webui --port 8000
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

## What's New in v0.4.3

### Stability (v0.4.3)

- **LLM retry with exponential backoff** — automatic retry for transient API failures (rate limits, server errors) with jitter, configurable per-provider
- **Token-aware context management** — tiktoken-based token estimation with auto-summarization and token budget trimming to prevent context window overflow

### Observability (v0.4.4)

- **Structured LLM call logging** — JSONL-format logs with request/response/tool_result events, latency tracking, and truncated content previews
- **Chat cancellation** — SSE-based cancellation via `asyncio.Event`, cancel API endpoint, and Send/Stop button toggle in Web UI

### Agent Capability (v0.4.5)

- **Persistent memory notes** — agents can `remember_note` and `recall_notes` with category filtering, stored as JSONL in their workspace
- **Tool base class** — standard `Tool` interface with dual schema generation (Anthropic + OpenAI formats), enabling consistent tool contracts
- **SKILL.md export** — forge can export tools as SKILL.md packages (YAML frontmatter + markdown body + scripts/references/assets)
- **Reusable tool templates** — safe path resolution, token-aware truncation, shell execution helpers for forged tools

### Boundary Expansion (v0.5.0)

- **MCP integration** — dynamic tool discovery from external MCP servers over stdio transport (JSON-RPC)
- **Background process manager** — async subprocess lifecycle for long-running commands (start, monitor, kill, list, wait)
- **ACP protocol support** — JSON-RPC over stdio ACP server for embedding agents in external editors (Zed-compatible)
- **Multi-level config search** — layered config: CLI flag > project > user (~/.tain) > built-in defaults, plus per-agent agent.yaml overrides
- **Smart file truncation** — token-aware head+tail preservation when reading large files, preventing context overflow

Full changelog: [docs/changelog/v0.4.3.md](docs/changelog/v0.4.3.md)

---

## Architecture

```
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

```
tain_agent/                  # Framework package
  core/                      # Agent core
    agent.py                 # TaoAgent — main agent class
    agent_factory.py         # Multi-agent lifecycle management
    llm.py                   # Multi-provider LLM backend with retry
    retry.py                 # Exponential backoff retry mechanism
    llm_logger.py            # Structured JSONL call logging
    conversation.py          # Token-aware context management
    config.py                # Multi-level config loading with deep merge
    personality.py           # Emergent personality system
    drives.py                # Intrinsic motivation engine
    cognitive_loop.py        # PRAL cognitive cycle
    pral_bridge.py           # PRAL-to-agent bridge
    memory.py                # Agent memory
    environment.py           # Environment scanning
    bootstrap.py             # Tool bootstrap registration
    time_utils.py            # Timezone-aware datetime utilities
  tools/                     # Tool system
    registry.py              # Tool registry with timeout protection
    base.py                  # Tool abstract base class
    primal.py                # Primal tools (observe, read, write, search, memory)
    forge.py                 # Tool forge with SKILL.md export
    templates.py             # Reusable tool templates & utilities
    mcp_loader.py            # MCP server integration over stdio
    background_manager.py    # Async background process lifecycle
    inter_agent.py           # Agent-to-agent communication
  acp/                       # ACP protocol server
    server.py                # JSON-RPC ACP server over stdio
  evolution/                 # Self-evolution (pipeline, improvement, exporter)
  utils/                     # Utility functions
    token_utils.py           # Token-aware smart truncation
  runtime/                   # Standalone runtime kernel for exported agents
  storage_registry.py        # Semantic storage path resolution
webui/                       # Web UI (FastAPI + Jinja2 + HTMX + Alpine.js)
  app.py                     # FastAPI application
  dialogue.py                # SSE-streamed web chat engine
  routes/                    # API routes (chat, agents, controls)
  templates/                 # Jinja2 templates
  render.py                  # Content rendering utilities
agent_workspace/             # All agent workspaces (gitignored)
  _registry.json             # Global agent registry
  _messages/                 # Inter-agent message bus
  <agent_name>/              # Per-agent isolated workspace
main.py                      # CLI entry point
supervise_agent.py           # Daemon process manager
config.yaml                  # Framework configuration
docs/                        # Documentation
  architecture.md            # Full architecture design
  quickstart.md              # Getting started guide
  changelog/                 # Version changelogs
  plan/                      # Implementation plans (P0-P12)
tests/                       # Test suite (159 tests, 10 files)
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `python main.py --agent <name>` | Start an agent (creates if new) |
| `python main.py --agent <name> --dialogue` | Interactive chat mode |
| `python main.py --list-agents` | List all registered agents |
| `python main.py --create-agent` | Interactive creation wizard |
| `python main.py --webui` | Start Web UI management interface |
| `python main.py --agent <name> --state` | Print agent state report |
| `python main.py --agent <name> --log` | View agent decision log |
| `python main.py --agent <name> --export` | Export agent as standalone package |
| `python main.py --agent <name> --daemon` | Run as background daemon |
| `python main.py --daemon --stop` | Stop the daemon |
| `python main.py --daemon --status` | Check daemon status |

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

conversation:
  token_limit: 80000
  model_context_window: 131072

tools:
  max_output_tokens: 32000
  max_output_lines: 5000
```

---

## Documentation

- [Architecture Design](docs/architecture.md) — Full system architecture and design
- [Quick Start Guide](docs/quickstart.md) — Step-by-step getting started
- [Changelog](docs/changelog/) — Version history and release notes
- [Implementation Plans](docs/plan/) — Detailed implementation plans (P0-P12)

## Requirements

- Python 3.10+
- LLM API access (Anthropic, DeepSeek, OpenAI, or MiniMax)
- Dependencies: `anthropic`, `openai`, `pyyaml`, `duckduckgo_search`, `requests`, `rich`
- Optional: `tiktoken` (for accurate token counting), `pytest-asyncio` (for async tests)

## License

MIT
