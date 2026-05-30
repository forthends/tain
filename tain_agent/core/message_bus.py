"""
Message Bus — SQLite-backed inter-agent communication.

Replaces the file-polling _messages/ directory with WAL-mode SQLite for
lower latency, atomic message claiming, and reliable persistence.

Schema:
  messages      — pending/in-flight messages (the bus)
  conversations — archived message history (replaces per-peer JSONL files)

Concurrency:
  WAL mode allows concurrent readers + one writer. Each process opens its
  own connection. Busy timeout (5s) handles contention gracefully.
"""
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


# ─── SQL DDL ──────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    content TEXT NOT NULL,
    reply_to TEXT DEFAULT '',
    message_type TEXT DEFAULT 'chat',
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    peer_name TEXT NOT NULL,
    direction TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    content TEXT NOT NULL,
    reply_to TEXT DEFAULT '',
    message_type TEXT DEFAULT 'chat'
);

CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_agent, status);
CREATE INDEX IF NOT EXISTS idx_conv_agent_peer ON conversations(agent_name, peer_name);
CREATE INDEX IF NOT EXISTS idx_conv_msg_id ON conversations(message_id);
"""


# ─── Message Bus ──────────────────────────────────────────────────────

class MessageBus:
    """SQLite-backed message bus for inter-agent communication."""

    def __init__(self, workspace_root: str = "agent_workspace"):
        self.workspace_root = Path(workspace_root)
        self.db_path = self.workspace_root / "_message_bus.db"
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Create a new connection configured for WAL and concurrent access."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Ensure the database and schema exist."""
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        try:
            conn.executescript(DDL)
            conn.commit()
        finally:
            conn.close()

    # ── Send ──────────────────────────────────────────────────────

    def send_message(self, *, from_agent: str, to_agent: str,
                     content: str, reply_to: str = "",
                     message_type: str = "chat") -> dict:
        """Send a message to another agent. Returns result dict."""
        if not to_agent or not content:
            return {"success": False, "error": "to_agent and content are required."}
        if not from_agent:
            return {"success": False, "error": "from_agent is required."}

        msg_id = _make_msg_id()
        now_ts = _now_iso()

        conn = self._get_conn()
        try:
            # Write to messages bus
            conn.execute(
                """INSERT INTO messages (message_id, from_agent, to_agent,
                   timestamp, content, reply_to, message_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, from_agent, to_agent, now_ts, content, reply_to, message_type),
            )
            # Archive in sender's conversation log
            conn.execute(
                """INSERT INTO conversations (message_id, agent_name, peer_name,
                   direction, timestamp, content, reply_to, message_type)
                   VALUES (?, ?, ?, 'sent', ?, ?, ?, ?)""",
                (msg_id, from_agent, to_agent, now_ts, content, reply_to, message_type),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "success": True,
            "message_id": msg_id,
            "to": to_agent,
            "timestamp": now_ts,
        }

    # ── Check / Receive ───────────────────────────────────────────

    def check_messages(self, agent_name: str,
                       from_agent: str = "") -> dict:
        """Atomically claim and retrieve pending messages for an agent.

        Uses BEGIN IMMEDIATE to serialize claims across processes.
        Messages are archived to conversations table and removed from the bus.
        """
        if not agent_name:
            return {"success": False, "error": "agent_name is required.",
                    "messages": [], "count": 0}

        conn = self._get_conn()
        try:
            # Build query with optional from_agent filter
            params = [agent_name]
            filter_clause = ""
            if from_agent:
                filter_clause = "AND from_agent = ?"
                params.append(from_agent)

            # Atomically claim all pending messages for this agent
            conn.execute("BEGIN IMMEDIATE")

            rows = conn.execute(
                f"""SELECT * FROM messages
                    WHERE to_agent = ? AND status = 'pending' {filter_clause}
                    ORDER BY timestamp""",
                params,
            ).fetchall()

            if rows:
                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE messages SET status = 'claimed' WHERE id IN ({placeholders})",
                    ids,
                )

            conn.commit()

            # Convert to dicts and archive
            new_messages = []
            for row in rows:
                msg = dict(row)
                del msg["id"]  # internal only
                del msg["status"]
                new_messages.append(msg)

                # Archive in receiver's conversation log
                conn.execute(
                    """INSERT OR IGNORE INTO conversations
                       (message_id, agent_name, peer_name, direction,
                        timestamp, content, reply_to, message_type)
                       VALUES (?, ?, ?, 'received', ?, ?, ?, ?)""",
                    (msg["message_id"], agent_name, msg["from_agent"],
                     msg["timestamp"], msg["content"],
                     msg["reply_to"], msg["message_type"]),
                )

            # Delete claimed messages from the bus
            if rows:
                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"DELETE FROM messages WHERE id IN ({placeholders})",
                    ids,
                )
                conn.commit()

        finally:
            conn.close()

        return {
            "messages": new_messages,
            "count": len(new_messages),
            "message": (
                f"You have {len(new_messages)} new message(s)."
                if new_messages else "No new messages."
            ),
        }

    # ── Conversation History ───────────────────────────────────────

    def get_conversation_history(self, agent_name: str, with_agent: str,
                                  limit: int = 50,
                                  threaded: bool = False) -> dict:
        """Load conversation history between two agents."""
        if not agent_name or not with_agent:
            return {"success": False,
                    "error": "agent_name and with_agent are required.",
                    "messages": [], "count": 0}

        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM conversations
                   WHERE agent_name = ? AND peer_name = ?
                   ORDER BY timestamp""",
                (agent_name, with_agent),
            ).fetchall()

            all_messages = []
            for row in rows:
                msg = dict(row)
                del msg["id"]
                all_messages.append(msg)

            total = len(all_messages)

            if threaded:
                by_id = {m["message_id"]: m for m in all_messages}
                roots = []
                for m in all_messages:
                    parent_id = m.get("reply_to", "")
                    if parent_id and parent_id in by_id:
                        by_id[parent_id].setdefault("replies", []).append(m)
                    else:
                        roots.append(m)
                roots.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
                result = roots[-limit:] if limit else roots
                result = result[::-1] if limit else result
            else:
                result = all_messages[-limit:][::-1]

        finally:
            conn.close()

        return {
            "messages": result,
            "count": len(result),
            "with_agent": with_agent,
            "total_stored": total,
        }

    # ── Cleanup ───────────────────────────────────────────────────

    def cleanup(self, older_than_days: int = 7) -> int:
        """Remove old claimed/processed messages to prevent unbounded growth."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """DELETE FROM messages
                   WHERE status != 'pending'
                     AND timestamp < datetime('now', ? || ' days')""",
                (f"-{older_than_days}",),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def rotate_conversations(self, max_messages: int = 2000,
                              keep: int = 1000) -> dict[str, int]:
        """Trim old conversation entries per agent-peer pair."""
        conn = self._get_conn()
        trimmed = {}
        try:
            pairs = conn.execute(
                "SELECT DISTINCT agent_name, peer_name FROM conversations"
            ).fetchall()
            for pair in pairs:
                count_row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM conversations WHERE agent_name=? AND peer_name=?",
                    (pair["agent_name"], pair["peer_name"]),
                ).fetchone()
                if count_row["cnt"] > max_messages:
                    conn.execute(
                        """DELETE FROM conversations WHERE id IN (
                               SELECT id FROM conversations
                               WHERE agent_name=? AND peer_name=?
                               ORDER BY timestamp ASC
                               LIMIT ?
                           )""",
                        (pair["agent_name"], pair["peer_name"],
                         count_row["cnt"] - keep),
                    )
                    key = f"{pair['agent_name']}/{pair['peer_name']}"
                    trimmed[key] = count_row["cnt"] - keep
            conn.commit()
        finally:
            conn.close()
        return trimmed

    # ── Stats ──────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return bus statistics for monitoring."""
        conn = self._get_conn()
        try:
            pending = conn.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE status='pending'"
            ).fetchone()["cnt"]
            claimed = conn.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE status='claimed'"
            ).fetchone()["cnt"]
            total_conv = conn.execute(
                "SELECT COUNT(*) as cnt FROM conversations"
            ).fetchone()["cnt"]
        finally:
            conn.close()
        return {
            "pending_messages": pending,
            "claimed_messages": claimed,
            "total_conversations": total_conv,
            "db_path": str(self.db_path),
        }
