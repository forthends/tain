"""
Memory System — session persistence for standalone agents.

Implements the memory.json structure from Phase 3 §3.5:
  - Session summaries (LLM-generated at exit)
  - Key topics tracking
  - User preferences / user model
  - Long-term key facts with dedup
  - ≤ 1MB cap with auto-merge of old sessions

Zero framework dependencies — uses only stdlib.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


MAX_MEMORY_BYTES = 1_048_576  # 1 MB


class MemoryStore:
    """Persistent memory backing the standalone agent across sessions."""

    def __init__(self, file_path: str = "memory.json"):
        self.file_path = Path(file_path)
        self.data: dict = self._load()

    # ── Disk I/O ───────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self.file_path.exists():
            try:
                raw = self.file_path.read_text(encoding="utf-8")
                return json.loads(raw)
            except (json.JSONDecodeError, IOError):
                pass
        return self._empty_state()

    def _empty_state(self) -> dict:
        return {
            "version": "0.0.0",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "session_count": 0,
            "sessions": [],
            "long_term": {
                "key_facts": [],
                "user_model": {
                    "expertise_level": "unknown",
                    "preferred_style": "unknown",
                    "interests": [],
                },
            },
        }

    def save(self) -> None:
        self.data["updated_at"] = _now_iso()
        raw = json.dumps(self.data, ensure_ascii=False, indent=2)
        # Enforce size cap: merge old sessions if over limit
        while len(raw.encode("utf-8")) > MAX_MEMORY_BYTES and len(self.data.get("sessions", [])) > 1:
            self._merge_oldest_sessions()
            raw = json.dumps(self.data, ensure_ascii=False, indent=2)
        self.file_path.write_text(raw, encoding="utf-8")

    def _merge_oldest_sessions(self) -> None:
        """Merge the two oldest sessions into one summary entry."""
        sessions = self.data.get("sessions", [])
        if len(sessions) < 2:
            return
        a, b = sessions[0], sessions[1]
        merged = {
            "id": a.get("id", "merged"),
            "started": a.get("started", b.get("started", "")),
            "ended": b.get("ended", a.get("ended", "")),
            "message_count": a.get("message_count", 0) + b.get("message_count", 0),
            "summary": (a.get("summary", "") + " " + b.get("summary", "")).strip()[:500],
            "key_topics": list(set(a.get("key_topics", []) + b.get("key_topics", [])))[:10],
            "decisions_made": (a.get("decisions_made", []) + b.get("decisions_made", []))[:10],
            "user_preferences_learned": list(set(
                a.get("user_preferences_learned", []) +
                b.get("user_preferences_learned", [])
            ))[:10],
            "merged_from": [a.get("id", ""), b.get("id", "")],
        }
        self.data["sessions"] = [merged] + sessions[2:]

    # ── Session lifecycle ──────────────────────────────────────────────

    def start_session(self, version: str) -> str:
        """Begin a new session. Returns session id."""
        self.data["session_count"] += 1
        self.data["version"] = version
        session_id = f"sess_{self.data['session_count']:03d}"
        self._current_session = {
            "id": session_id,
            "started": _now_iso(),
            "ended": None,
            "message_count": 0,
            "summary": "",
            "key_topics": [],
            "decisions_made": [],
            "user_preferences_learned": [],
        }
        return session_id

    # ── Session end with LLM dedup ──────────────────────────────────

    def end_session(self, summary: str, key_topics: list[str],
                    decisions: list[str], preferences: list[str]) -> dict:
        """Finalize current session with LLM-generated summary and save."""
        session = getattr(self, "_current_session", None)
        if session is None:
            return {}
        session["ended"] = _now_iso()
        session["summary"] = summary
        session["key_topics"] = key_topics
        session["decisions_made"] = decisions
        session["user_preferences_learned"] = preferences

        self.data["sessions"].append(session)
        self._merge_long_term(session)
        self.save()
        self._current_session = None
        return session

    def dedup_key_facts(self, new_facts: list[str]) -> list[str]:
        """Merge new facts with existing long-term key_facts, removing duplicates.

        Uses simple string comparison for the runtime case. For LLM-based
        semantic dedup, the agent loop passes pre-deduped facts directly.
        """
        ltm = self.data.setdefault("long_term", {
            "key_facts": [],
            "user_model": {},
        })
        existing = set(ltm.get("key_facts", []))
        merged = list(ltm.get("key_facts", []))
        for fact in new_facts:
            if fact not in existing:
                merged.append(fact)
                existing.add(fact)
        return merged

    def set_key_facts(self, facts: list[str]) -> None:
        """Replace long-term key_facts with a deduped list (caller handles LLM dedup)."""
        ltm = self.data.setdefault("long_term", {})
        ltm["key_facts"] = facts

    def increment_messages(self, count: int = 1) -> None:
        session = getattr(self, "_current_session", None)
        if session:
            session["message_count"] += count

    # ── Long-term memory ───────────────────────────────────────────────

    def _merge_long_term(self, session: dict) -> None:
        """Merge session learnings into long_term storage."""
        ltm = self.data.setdefault("long_term", {
            "key_facts": [],
            "user_model": {
                "expertise_level": "unknown",
                "preferred_style": "unknown",
                "interests": [],
            },
        })

        # Dedup and merge key_facts
        existing_facts = set(ltm.get("key_facts", []))
        for topic in session.get("key_topics", []):
            if topic not in existing_facts:
                ltm.setdefault("key_facts", []).append(topic)
                existing_facts.add(topic)

        # Merge preferences into user_model
        um = ltm.setdefault("user_model", {})
        for pref in session.get("user_preferences_learned", []):
            interests = um.setdefault("interests", [])
            if pref not in interests:
                interests.append(pref)

    def add_key_fact(self, fact: str) -> None:
        ltm = self.data.setdefault("long_term", {})
        facts = ltm.setdefault("key_facts", [])
        if fact not in facts:
            facts.append(fact)

    def update_user_model(self, **kwargs) -> None:
        ltm = self.data.setdefault("long_term", {})
        um = ltm.setdefault("user_model", {})
        um.update(kwargs)

    # ── Retrieval ──────────────────────────────────────────────────────

    def recent_sessions(self, n: int = 5) -> list[dict]:
        """Return the N most recent session summaries."""
        sessions = self.data.get("sessions", [])
        return sessions[-n:]

    def last_session_summary(self) -> Optional[dict]:
        sessions = self.data.get("sessions", [])
        return sessions[-1] if sessions else None

    def get_long_term(self) -> dict:
        return self.data.get("long_term", {})

    def is_first_boot(self) -> bool:
        return self.data.get("session_count", 0) == 0

    # ── Import / export ────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a full copy of memory state for export."""
        return json.loads(json.dumps(self.data))

    def restore(self, data: dict) -> None:
        """Restore memory from a previously exported snapshot."""
        self.data = data
        self.save()
