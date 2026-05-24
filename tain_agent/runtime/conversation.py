"""
Conversation Manager — dialogue history with tool-pair protection.

Manages conversation_history for the agent's LLM interactions.
Provides trimming, format conversion, and crash-recovery checkpointing.

Zero framework dependencies — uses only stdlib.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationManager:
    """Manages conversation_history lifecycle.

    Responsibilities:
      - Append user/assistant messages
      - Trim to prevent context overflow (preserving tool_use/tool_result pairs)
      - Periodic checkpoint to disk for crash recovery
    """

    def __init__(self, checkpoint_dir: str = "logs",
                 checkpoint_file: str = "conversation_checkpoint.json",
                 auto_checkpoint_interval: int = 10):
        self.history: list[dict] = []
        self.checkpoint_path = Path(checkpoint_dir) / checkpoint_file
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.auto_checkpoint_interval = auto_checkpoint_interval
        self._cycles_since_checkpoint = 0

    def append(self, role: str, content) -> None:
        self.history.append({"role": role, "content": content})

    def clear(self) -> None:
        self.history = []

    def __len__(self) -> int:
        return len(self.history)

    def to_messages(self) -> list[dict]:
        """Convert to API-compatible message list."""
        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self.history
        ]

    def keep_first_and_last(self, keep_last: int = 8) -> int:
        """Trim history: keep first message + last N messages.

        Ensures tool_use/tool_result pairs are never broken across the
        trim boundary. Returns number of messages removed.
        """
        if len(self.history) <= keep_last + 1:
            return 0

        start_idx = len(self.history) - keep_last
        safe_idx = self._find_safe_boundary(start_idx)

        trimmed = [self.history[0]]
        trimmed.extend(self.history[safe_idx:])
        removed = len(self.history) - len(trimmed)
        self.history = trimmed
        return removed

    def _find_safe_boundary(self, idx: int) -> int:
        """Find a cut point that preserves tool_use/tool_result pairs."""
        if idx <= 0:
            return 0

        def _tool_use_ids(messages):
            ids = set()
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            ids.add(b.get("id"))
            return ids

        def _tool_result_refs(messages):
            refs = set()
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            refs.add(b.get("tool_use_id"))
            return refs

        lo = idx
        for _ in range(10):
            keep_range = self.history[lo:]
            result_refs = _tool_result_refs(keep_range)
            use_ids = _tool_use_ids(keep_range)
            missing = result_refs - use_ids
            if not missing:
                break
            for j in range(lo - 1, -1, -1):
                msg = self.history[j]
                content = msg.get("content", "")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            missing.discard(b.get("id"))
                if not missing:
                    lo = j
                    break
            else:
                lo = max(0, lo - 5)
                break

        for i in range(lo, min(lo + 15, len(self.history))):
            msg = self.history[i]
            content = msg.get("content", "")
            if isinstance(content, str):
                return i
            if isinstance(content, list):
                has_tool_results = any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                )
                if not has_tool_results:
                    return i

        return lo

    def checkpoint(self) -> dict:
        """Save conversation history to disk for crash recovery."""
        snapshot = {
            "timestamp": _now_iso(),
            "message_count": len(self.history),
            "history": self.history,
        }
        self.checkpoint_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._cycles_since_checkpoint = 0
        return {
            "checkpoint_path": str(self.checkpoint_path),
            "message_count": len(self.history),
            "file_size": self.checkpoint_path.stat().st_size,
        }

    def load_checkpoint(self) -> Optional[list[dict]]:
        """Load conversation history from the last checkpoint."""
        if not self.checkpoint_path.exists():
            return None
        try:
            snapshot = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            self.history = snapshot.get("history", [])
            return self.history
        except (json.JSONDecodeError, IOError):
            return None

    def should_checkpoint(self) -> bool:
        self._cycles_since_checkpoint += 1
        return self._cycles_since_checkpoint >= self.auto_checkpoint_interval

    def checkpoint_if_needed(self) -> Optional[dict]:
        if self.should_checkpoint():
            return self.checkpoint()
        return None
