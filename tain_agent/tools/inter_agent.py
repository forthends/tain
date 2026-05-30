"""
Inter-Agent Communication — Agent间通信

Tools for agent discovery, messaging, and conversation between agents
within the same Tain Agent Framework instance.

Architecture:
  agent_workspace/
    _registry.json        # Shared agent registry (discovery)
    _message_bus.db       # SQLite WAL-mode message bus + conversation archive
    <agent>/
      logs/conversations/ # (deprecated — now stored in _message_bus.db)

Design:
  - SQLite-backed: WAL mode for concurrent read/write, atomic claims
  - Pull model: agents check inbox on their own cognitive cycle
  - Persistent: all messages archived in conversations table
  - Safe: no code execution vectors, no external services
"""
import json
from pathlib import Path
from typing import Optional

from tain_agent.core.message_bus import MessageBus


# ─── Tool: discover_agents ────────────────────────────────────────────

def discover_agents(workspace_root: str = "agent_workspace",
                    self_name: str = "") -> dict:
    """Discover other agents running in the same framework.

    Reads the shared agent registry and returns info about all agents
    except the caller.

    Args:
        workspace_root: Path to the agent workspace root directory.
        self_name: Name of the calling agent (excluded from results).

    Returns:
        dict with 'agents' list and 'count'.
    """
    root = Path(workspace_root)
    registry_path = root / "_registry.json"

    if not registry_path.exists():
        return {"agents": [], "count": 0, "message": "Registry not found."}

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {"agents": [], "count": 0, "error": "Failed to read registry."}

    agents = []
    for name, info in registry.get("agents", {}).items():
        if name == self_name:
            continue
        agents.append({
            "name": name,
            "role": info.get("role"),
            "evolution_mode": info.get("evolution_mode"),
            "status": info.get("status", "unknown"),
            "last_active_at": info.get("last_active_at"),
        })

    return {
        "agents": agents,
        "count": len(agents),
        "message": f"Found {len(agents)} other agent(s)." if agents else "No other agents found.",
    }


# ─── Tool: send_message ───────────────────────────────────────────────

def send_message(to_agent: str, content: str,
                 from_agent: str = "",
                 reply_to: str = "",
                 message_type: str = "chat",
                 workspace_root: str = "agent_workspace") -> dict:
    """Send a message to another agent via the SQLite message bus.

    Args:
        to_agent: Target agent name.
        content: Message content (text).
        from_agent: Sender's agent name.
        reply_to: Optional message ID this is replying to.
        message_type: Type of message (default "chat").
        workspace_root: Path to the agent workspace root directory.

    Returns:
        dict with message_id and status.
    """
    if not to_agent or not content:
        return {"success": False, "error": "to_agent and content are required."}

    if not from_agent:
        return {"success": False, "error": "from_agent is required."}

    # Verify recipient exists in registry
    root = Path(workspace_root)
    registry_path = root / "_registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            if to_agent not in registry.get("agents", {}):
                return {"success": False, "error": f"Agent '{to_agent}' not found."}
        except (json.JSONDecodeError, IOError):
            pass

    bus = MessageBus(workspace_root)
    return bus.send_message(
        from_agent=from_agent, to_agent=to_agent,
        content=content, reply_to=reply_to, message_type=message_type,
    )


# ─── Tool: check_messages ─────────────────────────────────────────────

def check_messages(agent_name: str = "",
                   from_agent: str = "",
                   workspace_root: str = "agent_workspace") -> dict:
    """Check for new messages addressed to this agent.

    Uses atomic claim via SQLite BEGIN IMMEDIATE to prevent duplicate
    delivery across concurrent agent instances.

    Args:
        agent_name: Name of the agent checking messages.
        from_agent: Optional filter — only return messages from this sender.
        workspace_root: Path to the agent workspace root directory.

    Returns:
        dict with 'messages' list and 'count'.
    """
    if not agent_name:
        return {"success": False, "error": "agent_name is required.",
                "messages": [], "count": 0}

    bus = MessageBus(workspace_root)

    result = bus.check_messages(agent_name=agent_name, from_agent=from_agent)

    # Periodic rotation — trim old conversations if needed
    if result["count"] > 0:
        try:
            bus.rotate_conversations()
        except Exception:
            pass

    return result


# ─── Tool: get_conversation_history ────────────────────────────────────

def get_conversation_history(with_agent: str, agent_name: str = "",
                             limit: int = 50,
                             threaded: bool = False,
                             workspace_root: str = "agent_workspace") -> dict:
    """Load conversation history with a specific peer agent.

    Reads from the SQLite conversations table.

    Args:
        with_agent: Peer agent name to load conversation with.
        agent_name: This agent's name.
        limit: Max number of messages to return (most recent first).
        threaded: If True, nest replies under their parent messages.
        workspace_root: Path to the agent workspace root directory.

    Returns:
        dict with 'messages' list, 'count', and 'total_stored'.
    """
    if not agent_name or not with_agent:
        return {"success": False, "error": "agent_name and with_agent are required.",
                "messages": [], "count": 0}

    bus = MessageBus(workspace_root)
    result = bus.get_conversation_history(
        agent_name=agent_name, with_agent=with_agent,
        limit=limit, threaded=threaded,
    )

    total = result.get("total_stored", 0)
    return {
        "messages": result["messages"],
        "count": result["count"],
        "with_agent": with_agent,
        "total_stored": total,
    }


# ─── Registration helpers ──────────────────────────────────────────────

def register_inter_agent_tools(tool_registry, workspace_root: str = "agent_workspace",
                               agent_name: str = "") -> None:
    """Register inter-agent communication tools on a ToolRegistry.

    Each tool is registered as a closure that captures workspace_root and
    agent_name, so the agent doesn't need to pass them explicitly.

    Args:
        tool_registry: ToolRegistry instance to register on.
        workspace_root: Path to the agent workspace root.
        agent_name: This agent's name.
    """
    _ws = workspace_root
    _name = agent_name

    def _discover_agents() -> dict:
        return discover_agents(workspace_root=_ws, self_name=_name)

    def _send_message(to_agent: str, content: str, reply_to: str = "",
                      message_type: str = "chat") -> dict:
        return send_message(
            to_agent=to_agent, content=content,
            from_agent=_name, reply_to=reply_to,
            message_type=message_type,
            workspace_root=_ws,
        )

    def _check_messages(from_agent: str = "") -> dict:
        return check_messages(agent_name=_name, from_agent=from_agent, workspace_root=_ws)

    def _get_conversation_history(with_agent: str, limit: int = 50,
                                  threaded: bool = False) -> dict:
        return get_conversation_history(
            with_agent=with_agent, agent_name=_name,
            limit=limit, threaded=threaded, workspace_root=_ws,
        )

    tool_registry.register(
        "discover_agents",
        _discover_agents,
        "Discover other agents running in the same framework. "
        "Returns a list of agents with their names, roles, statuses, and last active times.",
        {},
    )

    tool_registry.register(
        "send_message",
        _send_message,
        "Send a message to another agent. The message is persisted in both "
        "the shared message bus and your conversation log with that agent. "
        "Use message_type to indicate the purpose: 'chat' (conversation), "
        "'request' (asking for something), 'response' (reply to a request), "
        "'broadcast' (announcement to all).",
        {
            "to_agent": {"type": "string", "required": True,
                         "description": "Name of the agent to send the message to."},
            "content": {"type": "string", "required": True,
                        "description": "The message content."},
            "reply_to": {"type": "string", "required": False,
                         "description": "Optional message ID this is replying to."},
            "message_type": {"type": "string", "required": False,
                             "description": "Type of message: 'chat', 'request', 'response', or 'broadcast'. Default 'chat'."},
        },
    )

    tool_registry.register(
        "check_messages",
        _check_messages,
        "Check for new messages addressed to you from other agents. "
        "Messages are automatically archived to your conversation logs.",
        {
            "from_agent": {"type": "string", "required": False,
                           "description": "Optional filter — only check messages from this agent."},
        },
    )

    tool_registry.register(
        "get_conversation_history",
        _get_conversation_history,
        "Load your conversation history with a specific agent. "
        "Useful when resuming a dialogue after restart. "
        "Set threaded=True to see replies nested under their parent messages.",
        {
            "with_agent": {"type": "string", "required": True,
                           "description": "Name of the agent whose conversation to load."},
            "limit": {"type": "integer", "required": False,
                      "description": "Max messages to return (default 50, most recent first)."},
            "threaded": {"type": "boolean", "required": False,
                         "description": "If True, nest replies under parent messages as a thread tree."},
        },
    )
