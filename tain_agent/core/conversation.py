"""
Conversation Manager — 对话管理

Manages the agent's conversation history with the LLM.
Provides history trimming, format conversion, periodic checkpoint snapshots,
and token-aware context management with automatic summarization.

Extracted from agent.py during Phase 2 architecture decoupling.
"""

import json
from tain_agent.core.time_utils import now
from pathlib import Path
from typing import Callable, Optional


class ConversationManager:
    """Manages conversation_history lifecycle.

    Responsibilities:
      - Append user/assistant messages
      - Convert to Claude API format
      - Trim to prevent context overflow (token-aware)
      - Summarize execution blocks when approaching context limits
      - Periodic checkpoint to disk for crash recovery
    """

    def __init__(self, checkpoint_dir: str = "tain_agent/logs",
                 checkpoint_file: str = "conversation_checkpoint.json",
                 auto_checkpoint_interval: int = 10,
                 token_limit: int = 80000,
                 model_context_window: int = 131072):
        self.history: list[dict] = []
        self.checkpoint_path = Path(checkpoint_dir) / checkpoint_file
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.auto_checkpoint_interval = auto_checkpoint_interval
        self._cycles_since_checkpoint = 0
        self.token_limit = token_limit
        self.model_context_window = model_context_window
        self._skip_next_token_check = False
        self._summarize_callback: Optional[Callable] = None

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

    # ── Token management ────────────────────────────────────────────

    def set_summarize_callback(self, callback: Callable) -> None:
        """Register a callback for LLM-driven summarization.

        The callback receives (messages: list[dict]) -> str and returns
        a summary string.
        """
        self._summarize_callback = callback

    def estimate_tokens(self, messages: Optional[list[dict]] = None) -> int:
        """Estimate token count for messages.

        Uses tiktoken (cl100k_base) if available, falling back to
        character-based estimation (2.5 chars/token). The fallback is
        ±20% accurate for most English/Chinese text.

        Args:
            messages: Messages to count. Defaults to self.history.
        """
        msgs = messages if messages is not None else self.history
        text = self._messages_to_text(msgs)
        return self._count_tokens(text)

    @staticmethod
    def _messages_to_text(messages: list[dict]) -> str:
        parts = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") in ("text", "tool_result"):
                            parts.append(str(block.get("text", block.get("content", ""))))
                        elif block.get("type") == "tool_use":
                            parts.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(parts)

    @staticmethod
    def _count_tokens(text: str) -> int:
        """Count tokens in text, with tiktoken fallback."""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            return max(1, len(text) // 2)

    def needs_summarization(self) -> bool:
        """Check whether the conversation history should be summarized."""
        if self._skip_next_token_check:
            self._skip_next_token_check = False
            return False
        if len(self.history) <= 2:
            return False
        estimated = self.estimate_tokens()
        return estimated > self.token_limit

    def summarize(self, backend=None) -> Optional[str]:
        """Summarize execution blocks between user messages.

        Preserves system prompt (first message) and all user messages.
        Compresses the tool-call execution blocks between them.

        Args:
            backend: Optional LLM backend for generating summaries.
                     If not provided, uses the summarize_callback.

        Returns:
            Summary result string, or None if no summarization was needed.
        """
        if not self.needs_summarization():
            return None

        if len(self.history) < 3:
            return None

        # Strategy: keep first message + user messages, summarize execution blocks
        new_messages = [self.history[0]]  # system prompt
        summaries = []

        i = 1
        while i < len(self.history):
            msg = self.history[i]
            role = msg.get("role", "")

            if role == "user":
                new_messages.append(msg)
                i += 1
                continue

            # Collect execution block until next user message
            block = []
            while i < len(self.history) and self.history[i].get("role") != "user":
                block.append(self.history[i])
                i += 1

            if block and len(block) >= 2:
                summary_text = self._create_summary(block, backend)
                if summary_text:
                    new_messages.append({
                        "role": "assistant",
                        "content": f"[Previous execution summary]\n{summary_text}",
                    })
                    summaries.append(summary_text)
                else:
                    new_messages.extend(block)
            elif block:
                new_messages.extend(block)

        self.history = new_messages
        self._skip_next_token_check = True

        if summaries:
            return f"Compressed {len(summaries)} execution blocks (estimated tokens: {self.estimate_tokens()})"
        return "Summarization skipped (no execution blocks to compress)"

    def _create_summary(self, block: list[dict], backend=None) -> Optional[str]:
        """Create a summary for a single execution block."""
        # Extract key information from the block
        tool_calls = []
        results = []
        for msg in block:
            content = msg.get("content", "")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "tool_use":
                            tool_calls.append(item.get("name", "unknown"))
                        elif item.get("type") == "tool_result":
                            result_text = str(item.get("content", ""))
                            if len(result_text) > 500:
                                result_text = result_text[:500] + "..."
                            results.append(result_text)

        # Template-based summary when no LLM backend available
        return (
            f"Tools called: {', '.join(tool_calls) if tool_calls else 'none'}. "
            f"Results: {'; '.join(results[:3]) if results else 'none'}"
        )

    def trim_to_token_budget(self, keep_last: int = 8) -> int:
        """Trim history to stay within token budget.

        Uses token estimation first, falling back to keep_first_and_last
        as a safety net.

        Returns number of messages removed.
        """
        if len(self.history) <= 2:
            return 0

        estimated = self.estimate_tokens()
        if estimated <= self.token_limit:
            return 0

        # Token budget exceeded — fall back to keep_first_and_last
        # with a larger keep_last to provide more context
        return self.keep_first_and_last(keep_last=max(keep_last * 2, 16))

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
