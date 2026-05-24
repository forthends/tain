"""
Conversation Manager — 对话管理

Manages the agent's conversation history with the LLM.
Provides history trimming, format conversion, and periodic checkpoint snapshots.

Extracted from agent.py during Phase 2 architecture decoupling.
"""

import json
from tain_agent.core.time_utils import now
from pathlib import Path
from typing import Optional


class ConversationManager:
    """Manages conversation_history lifecycle.

    Responsibilities:
      - Append user/assistant messages
      - Convert to Claude API format
      - Trim to prevent context overflow
      - Periodic checkpoint to disk for crash recovery
    """

    def __init__(self, checkpoint_dir: str = "tain_agent/logs",
                 checkpoint_file: str = "conversation_checkpoint.json",
                 auto_checkpoint_interval: int = 10):
        self.history: list[dict] = []
        self.checkpoint_path = Path(checkpoint_dir) / checkpoint_file
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.auto_checkpoint_interval = auto_checkpoint_interval
        self._cycles_since_checkpoint = 0

    # ── History management ──────────────────────────────────────────

    def append(self, role: str, content) -> None:
        """Append a message to conversation history."""
        self.history.append({"role": role, "content": content})

    def clear(self) -> None:
        """Clear all history."""
        self.history = []

    def len(self) -> int:
        return len(self.history)

    def to_claude_messages(self) -> list[dict]:
        """Convert internal history to Claude API format."""
        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self.history
        ]

    def last_safe(self, n: int) -> list[dict]:
        """Return the last N messages, expanding backward to preserve tool_use/tool_result pairs.

        Unlike a raw ``history[-n:]`` slice, this ensures no tool_result block
        is orphaned from its tool_use — the API rejects orphaned tool_results
        with error 2013.
        """
        if len(self.history) <= n:
            return self.to_claude_messages()

        start_idx = len(self.history) - n
        safe_idx = self._find_safe_boundary(start_idx)
        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self.history[safe_idx:]
        ]

    def keep_first_and_last(self, keep_last: int = 8) -> int:
        """Trim history: keep first message + last N messages.

        Ensures tool_use/tool_result pairs are never broken across the
        trim boundary. A broken pair causes the LLM API to reject the
        request with "tool result's tool id not found" (error 2013).

        Returns number of messages removed.
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
        """Find a cut point that won't orphan tool_use/tool_result pairs.

        Walks forward from idx (up to 15 messages) looking for a safe
        starting point — a message that doesn't depend on tool calls
        from the trimmed range. Also walks backward to include
        orphaned tool_use messages referenced by kept tool_results.
        """
        if idx <= 0:
            return 0

        # Collect tool_use IDs present in the tentative keep range
        def _tool_use_ids(messages):
            ids = set()
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            ids.add(b.get("id"))
            return ids

        # Collect tool_use_id references from tool_result blocks
        def _tool_result_refs(messages):
            refs = set()
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            refs.add(b.get("tool_use_id"))
            return refs

        # Expand backward to include missing tool_use messages
        lo = idx
        for _ in range(10):  # guard against infinite loop
            keep_range = self.history[lo:]
            result_refs = _tool_result_refs(keep_range)
            use_ids = _tool_use_ids(keep_range)
            missing = result_refs - use_ids
            if not missing:
                break
            # Walk back to find messages containing the missing tool_use IDs
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
                lo = max(0, lo - 5)  # couldn't find all, expand anyway
                break

        # Now walk forward to find a clean starting point
        for i in range(lo, min(lo + 15, len(self.history))):
            msg = self.history[i]
            content = msg.get("content", "")
            if isinstance(content, str):
                return i  # text-only message = safe boundary
            if isinstance(content, list):
                has_tool_results = any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                )
                if not has_tool_results:
                    return i  # no tool_result dependency = safe
                # This message has tool_results — skip it and include
                # its paired tool_use (which should already be included
                # from the backward-expansion above)

        return lo  # fallback to expanded boundary

    # ── Checkpoint ──────────────────────────────────────────────────

    def checkpoint(self) -> dict:
        """Save conversation history to disk for crash recovery.

        Returns checkpoint metadata.
        """
        snapshot = {
            "timestamp": now().isoformat(),
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
        """Load conversation history from the last checkpoint.

        Returns the history list or None if no checkpoint exists.
        """
        if not self.checkpoint_path.exists():
            return None
        try:
            snapshot = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            self.history = snapshot.get("history", [])
            return self.history
        except (json.JSONDecodeError, IOError):
            return None

    def should_checkpoint(self) -> bool:
        """Check if it's time for an auto-checkpoint."""
        self._cycles_since_checkpoint += 1
        return self._cycles_since_checkpoint >= self.auto_checkpoint_interval

    def checkpoint_if_needed(self) -> Optional[dict]:
        """Auto-checkpoint if the interval has been reached."""
        if self.should_checkpoint():
            return self.checkpoint()
        return None
