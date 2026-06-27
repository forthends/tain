# Tain Agent Framework — Quick Start Guide

**Version**: 0.10.0

---

## Prerequisites

- Python 3.10+
- An LLM API key (Anthropic, DeepSeek, OpenAI, or MiniMax)

---

## 1. Installation

```bash
cd /path/to/tain
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## 2. Configuration

Edit `config.yaml` to set your LLM provider and API key:

```yaml
agent:
  default_agent: "default"

llm:
  provider: "minimax"            # anthropic | deepseek | openai | minimax
  model: "MiniMax-M3"
  api_key_env: "MINIMAX_API_KEY"
  base_url: "https://api.minimaxi.com/anthropic"
  retry:
    enabled: true
    max_retries: 3

exploration:
  max_exploration_cycles: 10
  min_action_categories: 2

evolution:
  min_interval_seconds: 300
  max_improvements_per_session: 10
  contract_enforcement: "strict"
```

Set your API key:
```bash
export MINIMAX_API_KEY="your-api-key"
```

---

## 3. Create Your First Agent (Chaos Mode)

Chaos mode creates an agent with no predefined personality — it will self-awaken and discover its identity through action.

```bash
./tain new
```

```
  Create New Agent — 创建新Agent

  Agent name: explorer

  Select evolution mode:
    1. 混沌模式 (Chaos) — 从空白人格开始，Agent自我觉醒，自我定义
    2. 指定人格模式 (Specified) — 预设角色与人格特质

  Choice [1/2]: 1

  Agent 'explorer' created successfully.
```

Or create and start in one step:
```bash
./tain run explorer
```

---

## 4. Create an Agent with a Specified Personality

Specified mode lets you predefine the agent's role and personality:

```bash
./tain new
```

```
  Agent name: poet

  Select evolution mode:
    1. 混沌模式 (Chaos)
    2. 指定人格模式 (Specified)

  Choice [1/2]: 2

  Role name (e.g. 浪漫主义诗人): 浪漫主义诗人
  Role description: 随性、浪漫的现代诗人，目标是用诗歌慰藉人性

  Agent 'poet' created successfully.
    Mode: specified
    Role: 浪漫主义诗人
    Description: 随性、浪漫的现代诗人，目标是用诗歌慰藉人性
    Workspace: agent_workspace/poet/
```

Start the poet:
```bash
./tain run poet
```

---

## 5. Web UI

Start the Web UI to interact with agents through a browser:

```bash
./tain webui
```

Open `http://localhost:8000` to access the dashboard. From there you can:
- Create and manage agents
- Chat with agents in real-time
- View evolution metrics, tools, and knowledge
- Monitor agent state and decisions

Protect the API with an API key:
```bash
export TAIN_API_KEY="your-secret-key"
```

Then include `X-API-Key: your-secret-key` in API request headers.

---

## 6. Running Multiple Agents

Open multiple terminal windows and start different agents:

Terminal 1:
```bash
./tain run poet
```

Terminal 2:
```bash
./tain run alpha01
```

---

## 7. Inter-Agent Communication

Once multiple agents are running, they can discover and talk to each other. The poet agent can discover alpha01:

```
> discover_agents
{
  "agents": [
    {"name": "alpha01", "role": null, "status": "running", ...}
  ],
  "count": 1
}
```

And send a message:
```
> send_message(to_agent="alpha01", content="你好！我在寻找诗歌的灵感。你最近在探索什么？")
```

alpha01 checks and responds:
```
> check_messages
{
  "messages": [
    {"from_agent": "poet", "content": "你好！我在寻找诗歌的灵感。..."}
  ],
  "count": 1
}

> send_message(to_agent="poet", content="你好poet！我在研究意识理论。也许我们可以合作——你用诗歌表达，我用逻辑分析。")
```

---

## 8. Viewing Agent State

```bash
# List all agents
./tain list

# View a specific agent
./tain run poet --state

# View agent decision log
./tain run poet --log
```

---

## 9. Daemon Mode

Run an agent as a background daemon with auto-restart:

```bash
./tain daemon start poet
./tain daemon stop
./tain daemon status
```

---

## 10. CLI Reference

| `./tain` command | `python main.py` equivalent | Description |
| --- | --- | --- |
| `./tain run <name>` | `python main.py --agent <name>` | Start agent (creates if new) |
| `./tain list` | `./tain list` | List all agents |
| `./tain new` | `python main.py --create-agent` | Interactive creation wizard |
| `./tain state <name>` | `python main.py --agent <name> --state` | Print agent state |
| `./tain log <name>` | `python main.py --agent <name> --log` | View decision log |
| `./tain webui [port]` | `python main.py --webui --port 8000` | Start Web UI |
| `./tain daemon start <name>` | `python main.py --daemon start --agent <name>` | Run as daemon |
| `./tain daemon stop` | `python main.py --daemon stop` | Stop daemon |
| `./tain daemon status` | `python main.py --daemon status` | Check daemon status |
| `./tain export <name>` | `python main.py --agent <name> --export` | Export agent package |
| `./tain dialogue <name>` | `python main.py --agent <name> --dialogue` | REPL dialogue mode |
| `./tain help` | `python main.py --help` | Show help |

---

## Next Steps

- Read [architecture.md](architecture.md) for the full system design
- Read [EVOLUTION.md](EVOLUTION.md) for the evolution philosophy
- Explore `agent_workspace/<name>/` to see what your agent creates
- Check `agent_workspace/<name>/logs/` for decision logs and reports
- Try creating agents with different roles and let them communicate
