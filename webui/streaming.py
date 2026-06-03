"""SSE streaming layer for Web UI chat."""
import asyncio
import logging
import re
import uuid
from typing import AsyncGenerator

from webui.agent_cache import get_agent
from webui.conversation_store import load_history, append_message, cleanup_incomplete
from tain_agent.core.chat import ChatEngine

logger = logging.getLogger(__name__)

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent

_active_cancel_events: dict[str, asyncio.Event] = {}


def cancel_chat_message(message_id: str) -> bool:
    event = _active_cancel_events.get(message_id)
    if event and not event.is_set():
        event.set()
        return True
    return False


def cancel_all_streams() -> int:
    """Cancel all active chat streams. Returns the count of cancelled streams."""
    count = 0
    for event in _active_cancel_events.values():
        if not event.is_set():
            event.set()
            count += 1
    return count


def _make_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _chunk_text(text: str, size: int = 30) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks = []
    pos = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        if end < len(text):
            for sep in ('\n', '。', '，', '、', '.', ',', ' ', ';'):
                idx = text.rfind(sep, pos, end)
                if idx > pos + size // 2:
                    end = idx + 1
                    break
        chunks.append(text[pos:end])
        pos = end
    return chunks


async def stream_chat_message(agent_name: str, user_content: str,
                              cancel_event: asyncio.Event = None) -> AsyncGenerator[dict, None]:
    msg_id = _make_msg_id()
    now_ts = _now_iso()

    agent = get_agent(agent_name, config_path=str(PROJECT_ROOT / "config.yaml"))
    if not agent.backend:
        yield {"text": "[Agent has no LLM backend configured.]"}
        yield {"done": True, "message_id": msg_id}
        return

    engine = ChatEngine(agent)
    history = load_history(agent_name)
    messages = []
    for m in history[-20:]:
        role = "user" if m.get("from_agent") == "web_user" else "assistant"
        content = m.get("content", "")
        if isinstance(content, str):
            content = re.sub(r'<[^>]*?tool_calls>.*?</[^>]*?tool_calls>', '', content, flags=re.DOTALL).strip()
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})

    user_msg = {
        "message_id": _make_msg_id(), "from_agent": "web_user", "to_agent": agent_name,
        "timestamp": now_ts, "content": user_content, "reply_to": "", "message_type": "chat",
    }
    append_message(agent_name, user_msg)

    async for event in engine.run_turn(messages, cancel_event):
        etype = event.get("type", "")
        if etype == "thinking":
            yield {"status": "thinking"}
        elif etype == "tool_start":
            for tname in event.get("tool_names", []):
                yield {"status": "tool", "tool_name": tname}
        elif etype == "done":
            turn = event["turn"]
            if cancel_event and cancel_event.is_set():
                cleanup_incomplete(messages)
                yield {"cancelled": True}
                return

            if turn.text and turn.text != "[Tool processing — no text response]":
                yield {"status": "text"}
                for chunk in _chunk_text(turn.text):
                    yield {"text": chunk}

            agent_msg = {
                "message_id": msg_id, "from_agent": agent_name, "to_agent": "web_user",
                "timestamp": _now_iso(), "content": turn.text, "reply_to": "", "message_type": "chat",
            }
            append_message(agent_name, agent_msg)
            yield {"done": True, "message_id": msg_id}
