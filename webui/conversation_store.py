"""Conversation history persistence (JSONL-based)."""
import json
from collections import deque
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT / "agent_workspace"


def load_history(agent_name: str) -> list[dict]:
    """Load chat history for an agent, reading only the tail of large files.

    Uses a generous tail window (2 MB) to avoid truncating long messages.
    Falls back to reading the entire file when it's smaller than the window.
    """
    conv_file = WORKSPACE_ROOT / agent_name / "logs" / "conversations" / "web_user.jsonl"
    if not conv_file.exists():
        return []
    TAIL_BYTES = 2 * 1024 * 1024  # 2 MB — handles very long single messages
    file_size = conv_file.stat().st_size
    messages = deque()
    try:
        with open(conv_file, "r", encoding="utf-8") as f:
            if file_size > TAIL_BYTES:
                f.seek(max(0, file_size - TAIL_BYTES))
                # Discard the first (likely partial) line from the seek position
                f.readline()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if isinstance(msg, dict) and "message_id" in msg:
                        messages.append(msg)
                except json.JSONDecodeError:
                    continue
    except IOError:
        pass
    return list(messages)


def append_message(agent_name: str, message: dict) -> None:
    conv_dir = WORKSPACE_ROOT / agent_name / "logs" / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_file = conv_dir / "web_user.jsonl"
    with open(conv_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")


def cleanup_incomplete(messages: list[dict]) -> None:
    if not messages:
        return
    last = messages[-1]
    if last.get("role") == "assistant":
        content = last.get("content")
        if isinstance(content, list):
            has_tool_use = any(
                isinstance(b, dict) and b.get("type") == "tool_use"
                for b in content
            )
            if has_tool_use:
                messages.pop()
