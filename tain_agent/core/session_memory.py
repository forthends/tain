"""
Session Memory — 会话记忆

Let the agent remember who it talked to and what was discussed.
Stores user identity and dialogue session summaries persistently.

Data is stored in the existing LongTermMemory under key "dialogue_sessions".
"""

from tain_agent.core.time_utils import now


class SessionMemory:
    """Persistent memory for dialogue partners and past conversation sessions.

    Each session records:
      - user_name: who the agent talked to
      - started_at / ended_at: timestamps
      - message_count: how many exchanges
      - summary: LLM-generated summary of what was discussed
      - topics: key topics extracted from the conversation
    """

    MAX_SESSIONS = 20  # Keep at most this many session records

    def __init__(self, memory):
        """Wrap an existing Memory instance.

        Args:
            memory: tain_agent.core.memory.Memory instance (provides long_term persistence)
        """
        self._memory = memory
        self._current_session: dict | None = None

    # ── User identity ─────────────────────────────────────────────────

    def get_user_name(self) -> str | None:
        """Return the remembered user name, or None if never set."""
        return self._load().get("user_name")

    def set_user_name(self, name: str) -> None:
        """Remember the user's name persistently."""
        data = self._load()
        data["user_name"] = name
        self._save(data)

    # ── Session lifecycle ─────────────────────────────────────────────

    def start_session(self) -> dict:
        """Begin a new dialogue session. Call once at REPL start."""
        self._current_session = {
            "id": now().strftime("%Y%m%dT%H%M%S"),
            "user_name": self.get_user_name() or "未知",
            "started_at": now().isoformat(),
            "ended_at": None,
            "message_count": 0,
            "summary": "",
            "topics": [],
        }
        return self._current_session

    def end_session(self, summary: str, message_count: int,
                    topics: list[str] | None = None) -> dict:
        """Finalize the current session with a summary and save it.

        Args:
            summary: Brief description of what was discussed
            message_count: Total exchanges in this session
            topics: Optional list of key topics
        """
        if not self._current_session:
            return {}

        self._current_session["ended_at"] = now().isoformat()
        self._current_session["message_count"] = message_count
        self._current_session["summary"] = summary
        self._current_session["topics"] = topics or []

        data = self._load()
        sessions = data.get("sessions", [])
        sessions.append(self._current_session)

        # Keep only recent sessions
        if len(sessions) > self.MAX_SESSIONS:
            sessions = sessions[-self.MAX_SESSIONS:]

        data["sessions"] = sessions
        self._save(data)

        session = self._current_session
        self._current_session = None
        return session

    def update_message_count(self, count: int) -> None:
        """Update the running message count for the current session."""
        if self._current_session:
            self._current_session["message_count"] = count

    # ── Session queries ───────────────────────────────────────────────

    def recent_sessions(self, n: int = 5) -> list[dict]:
        """Return the n most recent sessions (newest last)."""
        sessions = self._load().get("sessions", [])
        return sessions[-n:] if len(sessions) > n else sessions

    def total_sessions(self) -> int:
        """Total number of recorded sessions."""
        return len(self._load().get("sessions", []))

    # ── Context for system prompt ─────────────────────────────────────

    def get_context_for_prompt(self) -> str:
        """Build a context block about the user and past sessions.

        Returns a string suitable for injection into the LLM system prompt.
        """
        user_name = self.get_user_name()
        sessions = self.recent_sessions(5)

        lines = []

        # User identity
        if user_name:
            lines.append(f"## 对话对象")
            lines.append(f"你正在与 **{user_name}** 对话。这是你们之前对话的延续。")
        else:
            lines.append(f"## 对话对象")
            lines.append("这是你们第一次对话。你可以询问对方的名字以便记住。")

        # Past sessions
        if sessions:
            lines.append("")
            lines.append("## 最近的对话记录")
            for s in sessions:
                started = s.get("started_at", "")[:16]
                summary = s.get("summary", "(无摘要)")
                msg_count = s.get("message_count", 0)
                topics = s.get("topics", [])
                topic_str = f"  主题: {', '.join(topics)}" if topics else ""
                lines.append(f"- [{started}] {summary} ({msg_count} 条消息){topic_str}")

        return "\n".join(lines)

    # ── Persistence ───────────────────────────────────────────────────

    def _load(self) -> dict:
        """Load dialogue session data from long-term memory."""
        return self._memory.long_term.get("dialogue_sessions", {})

    def _save(self, data: dict) -> None:
        """Save dialogue session data to long-term memory."""
        self._memory.remember("dialogue_sessions", data, persist=True)
