# Tain Agent Framework — Quick Start Guide

**Version**: 0.4.0

---

## Prerequisites

- Python 3.10+
- An LLM API key (Anthropic, DeepSeek, OpenAI, or MiniMax)

---

## 1. Installation

```bash
cd /path/to/zero
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 2. Configuration

Edit `config.yaml` to set your LLM provider and API key:

```yaml
framework:
  version: "0.4.0"

agent:
  default_agent: "default"

llm:
  provider: "minimax"            # anthropic | deepseek | openai | minimax
  model: "MiniMax-M2.7"
  api_key_env: "MINIMAX_API_KEY"
  base_url: "https://api.minimaxi.com/anthropic"
```

Set your API key:
```bash
export MINIMAX_API_KEY="your-api-key"
```

---

## 3. Create Your First Agent (Chaos Mode)

Chaos mode creates an agent with no predefined personality — it will self-awaken and discover its identity through action.

```bash
python main.py --create-agent
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
python main.py --agent explorer
```

---

## 4. Create an Agent with a Specified Personality

Specified mode lets you predefine the agent's role and personality:

```bash
python main.py --create-agent
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
python main.py --agent poet
```

---

## 5. Dialogue Mode

Interact with an agent directly:

```bash
python main.py --agent poet --dialogue
```

---

## 6. Running Multiple Agents

Open multiple terminal windows and start different agents:

Terminal 1:
```bash
python main.py --agent poet
```

Terminal 2:
```bash
python main.py --agent alpha01
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
python main.py --list-agents

# View a specific agent
python main.py --agent poet --state

# View agent decision log
python main.py --agent poet --log
```

---

## 9. Exporting an Evolved Agent

After evolution, export your agent as a standalone package:

```bash
python main.py --agent poet --export --output ./dist
```

The exported package runs independently without the framework.

---

## 10. Daemon Mode

Run an agent as a background daemon with auto-restart:

```bash
python main.py --agent poet --daemon
python main.py --daemon --status
python main.py --daemon --stop
```

---

## 11. CLI Reference

| Command | Description |
|---------|-------------|
| `python main.py --agent <name>` | Start an agent (creates if new) |
| `python main.py --agent <name> --dialogue` | Interactive chat with agent |
| `python main.py --list-agents` | List all agents |
| `python main.py --create-agent` | Interactive creation wizard |
| `python main.py --agent <name> --state` | Print agent state |
| `python main.py --agent <name> --log` | View decision log |
| `python main.py --agent <name> --export` | Export as standalone package |
| `python main.py --agent <name> --daemon` | Run as daemon |
| `python main.py --daemon --stop` | Stop daemon |
| `python main.py --daemon --status` | Check daemon status |

---

## Next Steps

- Read [architecture.md](architecture.md) for the full system design
- Explore the `agent_workspace/<name>/` directory to see what your agent creates
- Check `agent_workspace/<name>/reports/` for evolution reports
- Try creating agents with different roles and let them communicate
