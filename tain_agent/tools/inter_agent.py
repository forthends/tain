"""
Inter-Agent Communication — Agent间通信

Tools for agent discovery, messaging, and conversation between agents
within the same Tain Agent Framework instance.

Architecture:
  agent_workspace/
    _registry.json           # Shared agent registry (discovery)
    _messages/               # Shared message bus directory
      <from>_to_<to>_<ts>.json   # Individual message files
    <agent>/
      logs/conversations/
        <peer>.jsonl         # Per-peer conversation history (append-only)

Design:
  - File-based messaging: no sockets, no external services
  - Pull model: agents check inbox on their own cognitive cycle
  - Persistent: all messages logged per-peer, reloadable on restart
  - Safe: plain JSON files, no code execution vectors
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


# ─── Conversation log rotation ────────────────────────────────────────

MAX_CONVERSATION_MESSAGES = 1000
KEEP_CONVERSATION_MESSAGES = 500


def _rotate_conversation_log(filepath: Path,
                              max_lines: int = MAX_CONVERSATION_MESSAGES,
                              keep: int = KEEP_CONVERSATION_MESSAGES) -> None:
    """Trim conversation log to the most recent messages to prevent unbounded growth."""
    if not filepath.exists():
        return
    try:
        text = filepath.read_text(encoding="utf-8")
    except IOError:
        return
    lines = [l for l in text.strip().split("\n") if l.strip()]
    if len(lines) > max_lines:
        filepath.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")


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
    """Send a message to another agent.

    The message is written to the shared _messages/ directory and also
    appended to the sender's conversation log with the recipient.

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

    root = Path(workspace_root)

    # Verify recipient exists
    registry_path = root / "_registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            if to_agent not in registry.get("agents", {}):
                return {"success": False, "error": f"Agent '{to_agent}' not found."}
        except (json.JSONDecodeError, IOError):
            pass

    msg_id = _make_msg_id()
    now_ts = _now_iso()

    message = {
        "message_id": msg_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "timestamp": now_ts,
        "content": content,
        "reply_to": reply_to,
        "message_type": message_type,
    }

    # Write to shared message bus
    messages_dir = root / "_messages"
    messages_dir.mkdir(parents=True, exist_ok=True)
    msg_file = messages_dir / f"{from_agent}_to_{to_agent}_{msg_id}.json"
    msg_file.write_text(
        json.dumps(message, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Append to sender's conversation log
    conv_dir = root / from_agent / "logs" / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_file = conv_dir / f"{to_agent}.jsonl"
    with open(conv_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")
    _rotate_conversation_log(conv_file)

    return {
        "success": True,
        "message_id": msg_id,
        "to": to_agent,
        "timestamp": now_ts,
    }


# ─── Tool: check_messages ─────────────────────────────────────────────

def check_messages(agent_name: str = "",
                   from_agent: str = "",
                   workspace_root: str = "agent_workspace") -> dict:
    """Check for new messages addressed to this agent.

    Reads message files from _messages/ that are addressed to agent_name.
    Uses atomic rename to claim each message, preventing duplicate processing
    by concurrent agent instances. Processed messages are archived to the
    conversation log and removed from the bus.

    Args:
        agent_name: Name of the agent checking messages.
        from_agent: Optional filter — only return messages from this sender.
        workspace_root: Path to the agent workspace root directory.

    Returns:
        dict with 'messages' list and 'count'.
    """
    if not agent_name:
        return {"success": False, "error": "agent_name is required.", "messages": [], "count": 0}

    root = Path(workspace_root)
    messages_dir = root / "_messages"

    if not messages_dir.exists():
        return {"messages": [], "count": 0, "message": "No messages directory."}

    # First pass: read all candidate messages, then sort by timestamp
    candidates = []
    for msg_file in messages_dir.glob("*.json"):
        try:
            msg = json.loads(msg_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            # Corrupt file — try to clean up
            msg_file.unlink(missing_ok=True)
            continue

        if msg.get("to_agent") != agent_name:
            continue

        if from_agent and msg.get("from_agent") != from_agent:
            continue

        candidates.append((msg.get("timestamp", ""), msg_file, msg))

    # Sort by timestamp so messages are processed in chronological order
    candidates.sort(key=lambda x: x[0])

    new_messages = []

    for _ts, msg_file, msg in candidates:
        # Atomic claim: rename the file before processing.
        # If another instance already claimed it, the rename fails
        # and we skip — no duplicate delivery.
        claimed = msg_file.with_name(msg_file.name + ".claimed")
        try:
            os.rename(msg_file, claimed)
        except FileNotFoundError:
            continue  # another instance claimed it first

        try:
            new_messages.append(msg)

            # Archive to conversation log
            sender = msg.get("from_agent", "unknown")
            conv_dir = root / agent_name / "logs" / "conversations"
            conv_dir.mkdir(parents=True, exist_ok=True)
            conv_file = conv_dir / f"{sender}.jsonl"
            with open(conv_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            _rotate_conversation_log(conv_file)
        finally:
            claimed.unlink(missing_ok=True)

    return {
        "messages": new_messages,
        "count": len(new_messages),
        "message": f"You have {len(new_messages)} new message(s)." if new_messages else "No new messages.",
    }


# ─── Tool: get_conversation_history ────────────────────────────────────

def get_conversation_history(with_agent: str, agent_name: str = "",
                             limit: int = 50,
                             threaded: bool = False,
                             workspace_root: str = "agent_workspace") -> dict:
    """Load conversation history with a specific peer agent.

    Reads from the agent's logs/conversations/<peer>.jsonl file.

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
        return {"success": False, "error": "agent_name and with_agent are required.", "messages": [], "count": 0}

    root = Path(workspace_root)
    conv_file = root / agent_name / "logs" / "conversations" / f"{with_agent}.jsonl"

    if not conv_file.exists():
        return {"messages": [], "count": 0, "total_stored": 0,
                "message": f"No conversation history with '{with_agent}'."}

    all_messages = []
    try:
        with open(conv_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        msg = json.loads(line)
                        if isinstance(msg, dict) and "message_id" in msg:
                            all_messages.append(msg)
                    except json.JSONDecodeError:
                        continue
    except IOError:
        return {"success": False, "error": "Failed to read conversation file.", "messages": [], "count": 0}

    total = len(all_messages)

    # Most recent first (default) or build threaded view
    if threaded:
        # Build index: message_id → message
        by_id = {m["message_id"]: m for m in all_messages}
        roots = []
        for m in all_messages:
            m["replies"] = []
        for m in all_messages:
            parent_id = m.get("reply_to", "")
            if parent_id and parent_id in by_id:
                by_id[parent_id].setdefault("replies", []).append(m)
            else:
                roots.append(m)
        # Sort roots by timestamp, most recent first
        roots.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        # Return limited set of thread roots
        result = roots[-limit:] if limit else roots
        result = result[::-1] if limit else result
    else:
        result = all_messages[-limit:][::-1]

    return {
        "messages": result,
        "count": len(result),
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
    import copy

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
