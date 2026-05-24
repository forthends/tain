# Tain Agent Framework

> 道生一，一生二，二生三，三生万物。

A framework for building self-evolving AI agents. Each agent can start from chaos (self-awakening) or with a specified role and personality. Agents operate in isolated workspaces, forge their own tools, build knowledge, and evolve through continuous self-improvement. Multiple agents can run simultaneously and communicate with each other.

**v0.4.0** — Multi-Agent Architecture · Dual Evolution Modes · Inter-Agent Communication

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
```

See [Quick Start Guide](docs/quickstart.md) for detailed instructions.

---

## Core Features

### Self-Evolving Agents
Agents evolve through the PRAL cognitive cycle (**P**erceive → **R**eason → **A**ct → **L**earn). They forge their own tools, build knowledge gardens, and develop emergent personalities through experience — not menu selection.

### Dual Evolution Modes
- **Chaos Mode (混沌模式)**: The agent awakens with an empty personality. Identity emerges from action patterns.
- **Specified Mode (指定人格模式)**: The agent starts with a predefined role and personality traits, which still evolve through experience.

### Multi-Agent Architecture
Run multiple agents simultaneously, each in its own isolated workspace (`agent_workspace/<name>/`). Agents register in a shared registry and can discover each other.

### Inter-Agent Communication
Agents can discover peers, send messages, check their inbox, and maintain persistent conversation histories. Communication uses a file-based message bus — no sockets or external services required.

### Tool Forging
Agents create their own tools through a 6-stage safety pipeline: NameCheck → Sandbox → WorkspaceValidation → Compile → Exec → Discover → Register. All forged tools are sandboxed with restricted imports and timeout protection.

### Factory Export
Evolved agents can be exported as standalone packages that run independently from the framework, with zero internal framework dependencies.

### Safety & Isolation
- Complete workspace isolation — agents cannot read or modify project source
- Protected paths prevent self-modification of critical framework files
- Thread-pool timeout on all tool execution
- AST-level sandboxing on forged tools

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     main.py (CLI)                        │
│  --agent · --list-agents · --create-agent · --dialogue  │
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
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              agent_workspace/<name>/                     │
│  logs/ · knowledge/ · forged_tools/ · reports/ · state/ │
└─────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              agent_workspace/_messages/                  │
│         Inter-Agent Communication Bus                    │
└─────────────────────────────────────────────────────────┘
```

Full architecture: [docs/architecture.md](docs/architecture.md)

---

## Project Structure

```
tain_agent/                  # Framework package
  core/                      # Agent core (agent, personality, drives, LLM, memory)
    agent_factory.py         # Multi-agent lifecycle management (v0.4.0)
  tools/                     # Tool system (registry, forge, primal, inter_agent)
    inter_agent.py           # Agent-to-agent communication (v0.4.0)
  evolution/                 # Self-evolution (pipeline, improvement, exporter)
  runtime/                   # Standalone runtime kernel for exported agents
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
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `python main.py --agent <name>` | Start an agent (creates if new) |
| `python main.py --agent <name> --dialogue` | Interactive chat mode |
| `python main.py --list-agents` | List all registered agents |
| `python main.py --create-agent` | Interactive creation wizard |
| `python main.py --agent <name> --state` | Print agent state report |
| `python main.py --agent <name> --log` | View agent decision log |
| `python main.py --agent <name> --export` | Export agent as standalone package |
| `python main.py --agent <name> --daemon` | Run as background daemon |
| `python main.py --daemon --stop` | Stop the daemon |
| `python main.py --daemon --status` | Check daemon status |

---

## Documentation

- [Architecture Design](docs/architecture.md) — Full system architecture and design
- [Quick Start Guide](docs/quickstart.md) — Step-by-step getting started
- [Phase 4 Design](docs/parse-4-design.md) — v0.4.0 refactoring design document

## Requirements

- Python 3.10+
- LLM API access (Anthropic, DeepSeek, OpenAI, or MiniMax)
- Dependencies: `anthropic`, `openai`, `pyyaml`, `duckduckgo_search`, `requests`, `rich`

## License

MIT
