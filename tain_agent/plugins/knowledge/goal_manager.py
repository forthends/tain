"""GoalManager — agent goal tracking with JSON persistence."""

from __future__ import annotations
import json
import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


class Goal:
    """A single agent goal."""
    def __init__(self, goal_id: str, description: str, success_criteria: str,
                 status: str = "active"):
        self.id = goal_id
        self.description = description
        self.success_criteria = success_criteria
        self.status = status  # "active" | "completed" | "abandoned"
        self.completed_at: str | None = None
        self.summary: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "status": self.status,
            "completed_at": self.completed_at,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        g = cls(d["id"], d["description"], d["success_criteria"], d.get("status", "active"))
        g.completed_at = d.get("completed_at")
        g.summary = d.get("summary", "")
        return g


class GoalManager:
    """Manages agent goals with JSON persistence on disk."""

    def __init__(self, persist_path: Path | None = None):
        self._goals: dict[str, Goal] = {}
        self._persist_path = persist_path

    def initialize(self, persist_path: Path) -> None:
        self._persist_path = persist_path
        self._load()

    def create(self, description: str, success_criteria: str) -> Goal:
        """Create a new active goal. Returns the Goal object."""
        goal_id = f"goal_{uuid.uuid4().hex[:8]}"
        goal = Goal(goal_id, description, success_criteria)
        self._goals[goal_id] = goal
        self._save()
        logger.info("Goal created: %s — %s", goal_id, description[:60])
        return goal

    def complete(self, goal_id: str, summary: str = "") -> bool:
        """Mark a goal as completed. Returns True if found."""
        goal = self._goals.get(goal_id)
        if goal is None:
            return False
        goal.status = "completed"
        goal.summary = summary
        goal.completed_at = self._now()
        self._save()
        return True

    def list_active(self) -> list[dict]:
        """Return all active goals as dicts."""
        return [g.to_dict() for g in self._goals.values() if g.status == "active"]

    def list_completed(self) -> list[dict]:
        """Return all completed goals as dicts."""
        return [g.to_dict() for g in self._goals.values() if g.status == "completed"]

    def get(self, goal_id: str) -> dict | None:
        """Get a specific goal by ID."""
        g = self._goals.get(goal_id)
        return g.to_dict() if g else None

    def _save(self) -> None:
        if self._persist_path is None:
            return
        try:
            data = {"goals": [g.to_dict() for g in self._goals.values()]}
            self._persist_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save goals: %s", e)

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for gd in data.get("goals", []):
                goal = Goal.from_dict(gd)
                self._goals[goal.id] = goal
        except Exception as e:
            logger.warning("Failed to load goals: %s — starting fresh", e)

    @staticmethod
    def _now() -> str:
        from tain_agent.core.time_utils import now
        return now().isoformat()
