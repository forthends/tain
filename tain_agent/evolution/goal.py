"""
Goal System — 目标系统

The agent's ability to set, track, and evaluate goals.
Goals are the "三" that drive evolution — they create a feedback loop
between intention and action.
"""

import uuid
from tain_agent.core.time_utils import now
from typing import Optional


class Goal:
    """A single goal with tracking state."""

    STATUSES = ("pending", "in_progress", "completed", "abandoned", "blocked")

    def __init__(self, description: str, success_criteria: str, parent_id: Optional[str] = None):
        self.id = str(uuid.uuid4())[:8]
        self.description = description
        self.success_criteria = success_criteria
        self.status = "pending"
        self.parent_id = parent_id
        self.created_at = now().isoformat()
        self.completed_at = None
        self.progress_notes: list[str] = []

    def start(self) -> None:
        """Mark the goal as actively being pursued."""
        self.status = "in_progress"

    def complete(self) -> None:
        """Mark the goal as successfully completed."""
        self.status = "completed"
        self.completed_at = now().isoformat()

    def abandon(self, reason: str) -> None:
        """Abandon the goal with a given reason."""
        self.status = "abandoned"
        self.progress_notes.append(f"Abandoned: {reason}")

    def block(self, reason: str) -> None:
        """Block the goal from progressing."""
        self.status = "blocked"
        self.progress_notes.append(f"Blocked: {reason}")

    def note_progress(self, note: str) -> None:
        """Record a progress note."""
        self.progress_notes.append(note)

    def to_dict(self) -> dict:
        """Serialize the goal to a dictionary."""
        return {
            "id": self.id,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "status": self.status,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "progress_notes": self.progress_notes,
        }


class PlanArtifact:
    """
    Planning Artifact — Harness Engineering核心组件
    
    为长周期任务生成结构化规划文档：
    - Plan.md      — WHAT to do (目标和分解)
    - Implement.md — HOW to do it (实现步骤)
    - Review.md    — WHAT was done (复盘总结)
    
    每个规划产物都假设模型不能做某事——
    这些假设会随模型改进而过时。
    """
    
    def __init__(self, goal: Goal):
        self.id = str(uuid.uuid4())[:8]
        self.goal = goal
        self.plan = ""
        self.implement = ""
        self.review = ""
        self.created_at = now().isoformat()
        self.updated_at = now().isoformat()
    
    def generate_plan(self, steps: list[str]) -> str:
        """生成Plan.md内容"""
        lines = [
            f"# Plan: {self.goal.description}\n",
            f"**Goal ID**: {self.goal.id}",
            f"**Created**: {self.created_at}\n",
            "## Objectives\n",
        ]
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        
        lines.extend([
            "\n## Success Criteria\n",
            f"> {self.goal.success_criteria}\n",
            "## Assumptions\n",
            "*(This artifact assumes the model cannot do X — those assumptions expire.)*\n",
        ])
        
        self.plan = "".join(lines)
        self.updated_at = now().isoformat()
        return self.plan
    
    def generate_implement(self, steps: list[dict]) -> str:
        """生成Implement.md内容"""
        lines = [
            f"# Implementation: {self.goal.description}\n",
            f"**Plan ID**: {self.id}\n",
            "## Steps\n\n",
        ]
        for i, step in enumerate(steps, 1):
            name = step.get("name", f"Step {i}")
            desc = step.get("description", "")
            tool = step.get("tool", "")
            
            lines.append(f"### Step {i}: {name}\n")
            lines.append(f"**Description**: {desc}\n")
            if tool:
                lines.append(f"**Tool**: `{tool}`\n")
            lines.append("\n---\n\n")
        
        self.implement = "".join(lines)
        self.updated_at = now().isoformat()
        return self.implement
    
    def generate_review(self, outcomes: list[str]) -> str:
        """生成Review.md内容"""
        lines = [
            f"# Review: {self.goal.description}\n",
            f"**Plan ID**: {self.id}\n",
            f"**Completed**: {now().isoformat()}\n",
            "## Outcomes\n\n",
        ]
        for outcome in outcomes:
            lines.append(f"- {outcome}\n")
        
        lines.extend([
            "\n## Lessons Learned\n",
            "*(What would you do differently?)*\n",
            "## Artifact Expiration\n",
            "*(Which harness assumptions have expired with model improvements?)*\n",
        ])
        
        self.review = "".join(lines)
        self.updated_at = now().isoformat()
        return self.review
    
    def to_dict(self) -> dict:
        """Serialize the plan artifact to a dictionary."""
        return {
            "id": self.id,
            "goal_id": self.goal.id,
            "plan": self.plan,
            "implement": self.implement,
            "review": self.review,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class GoalSystem:
    """Manages the agent's goals — the engine of self-driven evolution."""

    def __init__(self, memory=None):
        self._goals: dict[str, Goal] = {}
        self._current_goal_id: Optional[str] = None
        self._memory = memory
        self._plan_artifacts: dict[str, PlanArtifact] = {}
        self._load_from_memory()

    def create_goal(self, description: str, success_criteria: str) -> Goal:
        """Create a new goal and set it as the current goal."""
        goal = Goal(description, success_criteria)
        self._goals[goal.id] = goal
        self._current_goal_id = goal.id
        self._save_to_memory()
        return goal

    def get_current(self) -> Optional[Goal]:
        """Get the currently active goal."""
        if self._current_goal_id:
            return self._goals.get(self._current_goal_id)
        return None

    def get(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

    def list_all(self) -> list[Goal]:
        return list(self._goals.values())

    def list_active(self) -> list[Goal]:
        return [g for g in self._goals.values() if g.status in ("pending", "in_progress", "blocked")]

    def complete_current(self) -> Optional[Goal]:
        """Mark current goal as complete."""
        goal = self.get_current()
        if goal:
            goal.complete()
            self._save_to_memory()
        return goal

    def switch_to(self, goal_id: str) -> bool:
        """Switch active goal."""
        if goal_id in self._goals:
            self._current_goal_id = goal_id
            return True
        return False

    def abandon_current(self, reason: str) -> Optional[Goal]:
        """Abandon the current goal."""
        goal = self.get_current()
        if goal:
            goal.abandon(reason)
            self._current_goal_id = None
            self._save_to_memory()
        return goal

    def summary(self) -> str:
        """Human-readable summary of all goals."""
        if not self._goals:
            return "No goals set yet."
        lines = [f"=== Goals ({len(self._goals)} total) ==="]
        for g in self._goals.values():
            active = "→ " if g.id == self._current_goal_id else "  "
            lines.append(f"{active}[{g.status}] {g.id}: {g.description}")
            if g.progress_notes:
                for note in g.progress_notes[-3:]:
                    lines.append(f"      └ {note}")
        return "\n".join(lines)

    # ─── Planning Artifact Methods ───────────────────────────────────────
    
    def create_plan_artifact(self, goal: Optional[Goal] = None) -> PlanArtifact:
        """
        为目标创建规划产物。
        如果未指定goal，使用当前目标。
        """
        if goal is None:
            goal = self.get_current()
        if goal is None:
            raise ValueError("No goal available to create plan artifact for.")
        
        artifact = PlanArtifact(goal)
        self._plan_artifacts[artifact.id] = artifact
        return artifact
    
    def get_plan_artifact(self, artifact_id: str) -> Optional[PlanArtifact]:
        """获取规划产物。"""
        return self._plan_artifacts.get(artifact_id)
    
    def list_plan_artifacts(self) -> list[PlanArtifact]:
        """列出所有规划产物。"""
        return list(self._plan_artifacts.values())

    def _save_to_memory(self) -> None:
        if self._memory:
            goals_data = {gid: g.to_dict() for gid, g in self._goals.items()}
            self._memory.remember("goals", goals_data, persist=True)
            self._memory.remember("current_goal_id", self._current_goal_id, persist=True)

    def _load_from_memory(self) -> None:
        if not self._memory:
            return
        goals_data = self._memory.long_term.get("goals", {})
        for gid, gdata in goals_data.items():
            goal = Goal(gdata["description"], gdata["success_criteria"], gdata.get("parent_id"))
            goal.id = gid
            goal.status = gdata.get("status", "pending")
            goal.created_at = gdata.get("created_at", "")
            goal.completed_at = gdata.get("completed_at")
            goal.progress_notes = gdata.get("progress_notes", [])
            self._goals[gid] = goal
        self._current_goal_id = self._memory.long_term.get("current_goal_id")
