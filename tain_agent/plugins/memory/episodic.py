"""Episodic memory — experience store backed by SQLite with decay-based forgetting."""

from __future__ import annotations
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tain_agent.plugins.memory.decay import current_strength, should_forget


@dataclass
class EpisodicMemory:
    """A single episodic memory — an experience the agent had."""

    content: str
    importance: float = 0.5
    created_at: str = ""
    recall_count: int = 0
    last_recalled_at: str | None = None
    associations: list[str] = field(default_factory=list)
    memory_id: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.memory_id:
            self.memory_id = str(uuid.uuid4())

    def strength(self) -> float:
        """Compute current memory strength using the decay engine."""
        return current_strength(
            importance=self.importance,
            created_at=self.created_at,
            recall_count=self.recall_count,
            last_recalled_at=self.last_recalled_at,
        )

    def recall(self) -> "EpisodicMemory":
        """Record a recall event — increments count and updates timestamp."""
        self.recall_count += 1
        self.last_recalled_at = datetime.now(timezone.utc).isoformat()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "importance": self.importance,
            "created_at": self.created_at,
            "recall_count": self.recall_count,
            "last_recalled_at": self.last_recalled_at,
            "associations": self.associations,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EpisodicMemory":
        return cls(
            memory_id=data.get("memory_id", ""),
            content=data["content"],
            importance=data.get("importance", 0.5),
            created_at=data.get("created_at", ""),
            recall_count=data.get("recall_count", 0),
            last_recalled_at=data.get("last_recalled_at"),
            associations=data.get("associations", []),
        )


class EpisodicStore:
    """SQLite-backed store for episodic memories with decay-based forgetting."""

    def __init__(self, db_path: Path | str):
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # ── Lifecycle ──

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS episodic_memory (
                memory_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                recall_count INTEGER DEFAULT 0,
                last_recalled_at TEXT,
                associations TEXT DEFAULT '[]'
            );"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_strength "
            "ON episodic_memory(importance, recall_count, created_at);"
        )
        self._conn.commit()

    def shutdown(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def health_check(self) -> str:
        if self._conn is None:
            return "not_connected"
        try:
            self._conn.execute("SELECT 1 FROM episodic_memory LIMIT 0;")
            return "ok"
        except Exception:
            return "error"

    # ── CRUD ──

    def encode(self, memory: EpisodicMemory) -> str:
        """Store a new episodic memory. Returns the memory_id."""
        if self._conn is None:
            raise RuntimeError("EpisodicStore not initialized")
        row = (
            memory.memory_id,
            memory.content,
            memory.importance,
            memory.created_at,
            memory.recall_count,
            memory.last_recalled_at,
            json.dumps(memory.associations),
        )
        self._conn.execute(
            """INSERT OR REPLACE INTO episodic_memory
               (memory_id, content, importance, created_at, recall_count,
                last_recalled_at, associations)
               VALUES (?, ?, ?, ?, ?, ?, ?);""",
            row,
        )
        self._conn.commit()
        return memory.memory_id

    def recall(self, limit: int = 10, min_strength: float = 0.0) -> list[EpisodicMemory]:
        """Retrieve memories ordered by current strength descending."""
        if self._conn is None:
            raise RuntimeError("EpisodicStore not initialized")
        rows = self._conn.execute(
            "SELECT memory_id, content, importance, created_at, recall_count, "
            "last_recalled_at, associations FROM episodic_memory "
            "ORDER BY importance DESC, recall_count DESC LIMIT ?;",
            (limit,),
        ).fetchall()

        memories = [EpisodicMemory.from_dict(self._row_to_dict(r)) for r in rows]
        if min_strength > 0:
            memories = [m for m in memories if m.strength() >= min_strength]
        return memories[:limit]

    def recent(self, limit: int = 10) -> list[EpisodicMemory]:
        """Retrieve most recently created memories."""
        if self._conn is None:
            raise RuntimeError("EpisodicStore not initialized")
        rows = self._conn.execute(
            "SELECT memory_id, content, importance, created_at, recall_count, "
            "last_recalled_at, associations FROM episodic_memory "
            "ORDER BY created_at DESC LIMIT ?;",
            (limit,),
        ).fetchall()
        return [EpisodicMemory.from_dict(self._row_to_dict(r)) for r in rows]

    def reinforce(self, memory_id: str) -> EpisodicMemory | None:
        """Reinforce a memory by recording a recall event."""
        if self._conn is None:
            raise RuntimeError("EpisodicStore not initialized")
        row = self._conn.execute(
            "SELECT memory_id, content, importance, created_at, recall_count, "
            "last_recalled_at, associations FROM episodic_memory "
            "WHERE memory_id = ?;",
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        memory = EpisodicMemory.from_dict(self._row_to_dict(row))
        memory.recall()
        self.encode(memory)
        return memory

    def forget(self, threshold: float = 0.05) -> int:
        """Remove memories whose strength has fallen below the threshold.
        Returns the number of memories forgotten."""
        if self._conn is None:
            raise RuntimeError("EpisodicStore not initialized")
        rows = self._conn.execute(
            "SELECT memory_id, content, importance, created_at, recall_count, "
            "last_recalled_at, associations FROM episodic_memory;"
        ).fetchall()

        to_delete: list[str] = []
        for row in rows:
            memory = EpisodicMemory.from_dict(self._row_to_dict(row))
            if should_forget(memory.strength(), threshold):
                to_delete.append(memory.memory_id)

        if to_delete:
            placeholders = ",".join("?" for _ in to_delete)
            self._conn.execute(
                f"DELETE FROM episodic_memory WHERE memory_id IN ({placeholders});",
                to_delete,
            )
            self._conn.commit()

        return len(to_delete)

    def count(self) -> int:
        """Return the total number of stored episodic memories."""
        if self._conn is None:
            return 0
        row = self._conn.execute("SELECT COUNT(*) FROM episodic_memory;").fetchone()
        return row[0] if row else 0

    def get(self, memory_id: str) -> EpisodicMemory | None:
        """Retrieve a single memory by ID."""
        if self._conn is None:
            raise RuntimeError("EpisodicStore not initialized")
        row = self._conn.execute(
            "SELECT memory_id, content, importance, created_at, recall_count, "
            "last_recalled_at, associations FROM episodic_memory "
            "WHERE memory_id = ?;",
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return EpisodicMemory.from_dict(self._row_to_dict(row))

    def snapshot(self) -> list[dict[str, Any]]:
        """Return all memories as dicts for serialization."""
        if self._conn is None:
            return []
        rows = self._conn.execute(
            "SELECT memory_id, content, importance, created_at, recall_count, "
            "last_recalled_at, associations FROM episodic_memory;"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ── Helpers ──

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        return {
            "memory_id": row[0],
            "content": row[1],
            "importance": row[2],
            "created_at": row[3],
            "recall_count": row[4],
            "last_recalled_at": row[5],
            "associations": json.loads(row[6]) if isinstance(row[6], str) else row[6],
        }
