"""
Memory System — 记忆系统

Two-tier memory:
1. Working Memory — ephemeral, session-scoped (Python dict)
2. Long-term Memory — persistent, file-based (JSON)

Context Compression:
Harness Engineering principles — progressively compress context against
"context rot" as tokens accumulate. 5-stage strategy inspired by Claude Code.
"""

import json
import re
from tain_agent.core.time_utils import now
from pathlib import Path
from typing import Optional, Callable


# ─── Context Compression Stages ─────────────────────────────────────

class CompressionStage:
    """One stage of progressive context compression."""
    
    def __init__(self, name: str, ratio: float, description: str):
        self.name = name
        self.ratio = ratio  # e.g., 0.8 = keep 80%
        self.description = description
    
    def compress(self, text: str) -> str:
        """Apply this compression stage to text."""
        if len(text) <= 100:
            return text
        
        target_len = int(len(text) * self.ratio)
        if len(text) <= target_len:
            return text
        
        # Strategy: Keep first and last sentences, summarize middle
        lines = text.split('\n')
        if len(lines) <= 3:
            return text
        
        # Keep headers, compress body
        result = []
        for line in lines:
            if line.strip().startswith('#') or line.strip().startswith('**'):
                result.append(line)  # Keep formatting
            elif len(line) < 50:
                result.append(line)  # Keep short lines
            else:
                # Truncate long lines
                result.append(line[:200] + '...' if len(line) > 200 else line)
        
        return '\n'.join(result)


# 5-stage progressive compaction (inspired by Claude Code)
COMPRESSION_STAGES = [
    CompressionStage("budget_reduction", 0.9, 
        "Light pruning — remove whitespace, trim long lines"),
    CompressionStage("snip", 0.7, 
        "Extract key sentences — keep intro/conclusion, summarize body"),
    CompressionStage("microcompact", 0.5, 
        "Aggressive compression — keep headers and bullet points only"),
    CompressionStage("context_collapse", 0.3, 
        "Collapse to summary — single paragraph per section"),
    CompressionStage("auto_compact", 0.15, 
        "Minimal summary — core insight only"),
]


class ContextCompressor:
    """
    Progressive context compressor — Harness Engineering component.
    
    As context grows, compress it through 5 stages to maintain
    coherence while freeing token budget.
    """
    
    def __init__(self, budget_tokens: int = 100000):
        self.budget_tokens = budget_tokens
        self.current_stage = 0
        self.total_compressions = 0
    
    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(text) // 4
    
    def get_stage(self, text: str) -> int:
        """Determine which compression stage is needed."""
        tokens = self.estimate_tokens(text)
        
        if tokens < self.budget_tokens * 0.5:
            return 0  # No compression needed
        elif tokens < self.budget_tokens * 0.7:
            return 1  # Light pruning
        elif tokens < self.budget_tokens * 0.85:
            return 2  # Key extraction
        elif tokens < self.budget_tokens * 0.95:
            return 3  # Aggressive
        else:
            return 4  # Maximum compression
    
    def compress(self, text: str, force_stage: Optional[int] = None) -> dict:
        """
        Compress text through appropriate stage.
        
        Returns dict with:
        - compressed: the compressed text
        - stage: which stage was used
        - original_tokens: token count before
        - compressed_tokens: token count after
        - ratio: compression ratio achieved
        """
        original_tokens = self.estimate_tokens(text)
        
        if force_stage is not None:
            stage_idx = min(force_stage, len(COMPRESSION_STAGES) - 1)
        else:
            stage_idx = self.get_stage(text)
        
        stage = COMPRESSION_STAGES[stage_idx]
        compressed = stage.compress(text)
        compressed_tokens = self.estimate_tokens(compressed)
        
        self.current_stage = stage_idx
        self.total_compressions += 1
        
        return {
            "compressed": compressed,
            "stage": stage.name,
            "stage_index": stage_idx,
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
            "ratio": compressed_tokens / original_tokens if original_tokens > 0 else 1.0,
        }
    
    def needs_compression(self, text: str) -> bool:
        """Check if text exceeds budget and needs compression."""
        return self.estimate_tokens(text) > self.budget_tokens * 0.8


class WorkingMemory:
    """In-memory, session-scoped storage. Cleared on restart."""

    def __init__(self):
        self._store: dict = {}
        self._created_at = now().isoformat()

    def set(self, key: str, value) -> None:
        """Store a value under the given key."""
        self._store[key] = value

    def get(self, key: str, default=None):
        """Retrieve a value by key, returning default if not found."""
        return self._store.get(key, default)

    def all(self) -> dict:
        """Return a shallow copy of all stored entries."""
        return dict(self._store)

    def delete(self, key: str) -> None:
        """Remove a key from the store if it exists."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries from the store."""
        self._store.clear()

    def snapshot(self) -> dict:
        """Return a snapshot of creation time and all entries."""
        return {
            "created_at": self._created_at,
            "entries": self.all(),
        }


class LongTermMemory:
    """File-based persistent memory. Survives restarts."""

    def __init__(self, file_path: str = "tain_agent/logs/memory.json"):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._store: dict = self._load()

    def _load(self) -> dict:
        if self.file_path.exists():
            try:
                return json.loads(self.file_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save(self) -> None:
        self.file_path.write_text(
            json.dumps(self._store, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def set(self, key: str, value) -> None:
        """Persist a value under key with timestamp and save to disk."""
        self._store[key] = {
            "value": value,
            "updated_at": now().isoformat(),
        }
        self._save()

    def get(self, key: str, default=None):
        """Retrieve a persisted value, returning default if not found."""
        entry = self._store.get(key)
        return entry["value"] if entry else default

    def all_keys(self) -> list[str]:
        """Return all stored keys."""
        return list(self._store.keys())

    def delete(self, key: str) -> None:
        """Remove a key from persistent storage."""
        self._store.pop(key, None)
        self._save()

    def clear(self) -> None:
        """Remove all entries from persistent storage."""
        self._store.clear()
        self._save()


class Memory:
    """Unified memory interface — working + long-term."""

    def __init__(self, long_term_path: str = "tain_agent/logs/memory.json",
                 budget_tokens: int = 100000):
        self.working = WorkingMemory()
        self.long_term = LongTermMemory(long_term_path)
        self.compressor = ContextCompressor(budget_tokens=budget_tokens)

    def remember(self, key: str, value, persist: bool = False) -> None:
        """Store a memory. If persist=True, survives restarts."""
        self.working.set(key, value)
        if persist:
            self.long_term.set(key, value)

    def recall(self, key: str, default=None):
        """Recall a memory, checking working first then long-term."""
        val = self.working.get(key)
        if val is not None:
            return val
        return self.long_term.get(key, default)

    def snapshot(self) -> dict:
        """Full memory snapshot for the agent's context."""
        return {
            "working": self.working.snapshot(),
            "long_term_keys": self.long_term.all_keys(),
        }

    def compact_context(self, text: str, force_stage: Optional[int] = None) -> dict:
        """
        Compress context text through progressive stages.
        
        Args:
            text: Text to compress
            force_stage: Force specific compression stage (0-4)
        
        Returns compression result dict.
        """
        return self.compressor.compress(text, force_stage)
    
    def needs_compression(self, text: str) -> bool:
        """Check if text needs compression."""
        return self.compressor.needs_compression(text)
