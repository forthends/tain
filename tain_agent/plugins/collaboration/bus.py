"""UpgradedMessageBus — SQLite-backed message bus with WAL mode.

Supports typed, prioritized messages with TTL expiry between agents.
"""

from __future__ import annotations
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Message:
    """A message on the bus."""

    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender: str = ""
    recipient: str = ""
    content: str = ""
    msg_type: str = "text"          # text, request, response, event, command
    priority: int = 0               # higher = more urgent
    ttl_seconds: float = 3600.0     # time-to-live in seconds
    created_at: str = field(default_factory=_now)
    read: bool = False

    def is_expired(self) -> bool:
        """Check if this message has exceeded its TTL."""
        try:
            created_dt = datetime.fromisoformat(self.created_at)
            now_dt = datetime.now(timezone.utc)
            age = (now_dt - created_dt).total_seconds()
            return age > self.ttl_seconds
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "content": self.content,
            "msg_type": self.msg_type,
            "priority": self.priority,
            "ttl_seconds": self.ttl_seconds,
            "created_at": self.created_at,
            "read": self.read,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(
            msg_id=data.get("msg_id", str(uuid.uuid4())),
            sender=data.get("sender", ""),
            recipient=data.get("recipient", ""),
            content=data.get("content", ""),
            msg_type=data.get("msg_type", "text"),
            priority=data.get("priority", 0),
            ttl_seconds=data.get("ttl_seconds", 3600.0),
            created_at=data.get("created_at", _now()),
            read=data.get("read", False),
        )


class UpgradedMessageBus:
    """SQLite-backed message bus with WAL mode for concurrent access.

    Schema: social_messages table with msg_type, priority, ttl_seconds.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create the database and table if not exists."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS social_messages (
                msg_id TEXT PRIMARY KEY,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                msg_type TEXT NOT NULL DEFAULT 'text',
                priority INTEGER NOT NULL DEFAULT 0,
                ttl_seconds REAL NOT NULL DEFAULT 3600.0,
                created_at TEXT NOT NULL,
                read INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Indices for common queries
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_recipient
            ON social_messages(recipient, read)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_priority
            ON social_messages(recipient, priority DESC, created_at)
        """)
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def send(
        self,
        sender: str,
        recipient: str,
        content: str,
        msg_type: str = "text",
        priority: int = 0,
        ttl: float = 3600.0,
    ) -> Message:
        """Send a message. Returns the created Message."""
        if self._conn is None:
            raise RuntimeError("MessageBus not initialized")

        msg = Message(
            sender=sender,
            recipient=recipient,
            content=content,
            msg_type=msg_type,
            priority=priority,
            ttl_seconds=ttl,
        )

        self._conn.execute(
            """
            INSERT INTO social_messages
                (msg_id, sender, recipient, content, msg_type, priority,
                 ttl_seconds, created_at, read)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                msg.msg_id, msg.sender, msg.recipient, msg.content,
                msg.msg_type, msg.priority, msg.ttl_seconds, msg.created_at,
            ),
        )
        self._conn.commit()
        return msg

    def broadcast(
        self,
        sender: str,
        content: str,
        recipients: list[str],
        msg_type: str = "text",
        priority: int = 0,
        ttl: float = 3600.0,
    ) -> list[Message]:
        """Send a message to multiple recipients."""
        messages = []
        for recipient in recipients:
            msg = self.send(sender, recipient, content, msg_type, priority, ttl)
            messages.append(msg)
        return messages

    def check_inbox(
        self,
        agent_name: str,
        mark_read: bool = True,
        limit: int = 50,
    ) -> list[Message]:
        """Check for messages addressed to an agent.

        Returns messages ordered by priority DESC, then timestamp.
        Expired messages are purged before retrieval.

        Args:
            agent_name: The recipient agent's name.
            mark_read: If True, mark returned messages as read.
            limit: Maximum number of messages to return.

        Returns list of Message objects.
        """
        if self._conn is None:
            return []

        # Purge expired messages first
        self._conn.execute(
            """
            DELETE FROM social_messages
            WHERE read = 0
              AND (strftime('%s', 'now') - strftime('%s', created_at)) > ttl_seconds
            """
        )
        self._conn.commit()

        # Fetch unread messages
        rows = self._conn.execute(
            """
            SELECT msg_id, sender, recipient, content, msg_type, priority,
                   ttl_seconds, created_at, read
            FROM social_messages
            WHERE recipient = ? AND read = 0
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
            """,
            (agent_name, limit),
        ).fetchall()

        messages = []
        for row in rows:
            msg = Message(
                msg_id=row[0],
                sender=row[1],
                recipient=row[2],
                content=row[3],
                msg_type=row[4],
                priority=row[5],
                ttl_seconds=row[6],
                created_at=row[7],
                read=bool(row[8]),
            )
            messages.append(msg)

        if mark_read and messages:
            msg_ids = [(m.msg_id,) for m in messages]
            self._conn.executemany(
                "UPDATE social_messages SET read = 1 WHERE msg_id = ?",
                msg_ids,
            )
            self._conn.commit()

        return messages

    def purge(self) -> int:
        """Delete all expired and read messages. Returns count deleted."""
        if self._conn is None:
            return 0
        cursor = self._conn.execute(
            """
            DELETE FROM social_messages
            WHERE read = 1
               OR (strftime('%s', 'now') - strftime('%s', created_at)) > ttl_seconds
            """
        )
        self._conn.commit()
        return cursor.rowcount
