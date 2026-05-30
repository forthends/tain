"""Team management — Team, TeamMember, TeamTask data models."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TeamMember:
    """A member of a team."""

    agent_id: str
    agent_name: str
    role: str = "member"        # lead, member, observer
    joined_at: str = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamTask:
    """A task assigned within a team."""

    task_id: str
    title: str
    description: str = ""
    assigned_to: str = ""        # agent_id
    status: Literal["pending", "in_progress", "completed", "blocked"] = "pending"
    priority: int = 0
    dependencies: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    completed_at: str | None = None


@dataclass
class Team:
    """A team of agents collaborating on a mission."""

    team_id: str
    name: str
    description: str = ""
    members: list[TeamMember] = field(default_factory=list)
    tasks: list[TeamTask] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_member(self, agent_id: str, agent_name: str, role: str = "member") -> TeamMember:
        """Add a member to the team. Returns the TeamMember."""
        member = TeamMember(agent_id=agent_id, agent_name=agent_name, role=role)
        self.members.append(member)
        return member

    def remove_member(self, agent_id: str) -> bool:
        """Remove a member by agent_id. Returns True if found and removed."""
        for i, m in enumerate(self.members):
            if m.agent_id == agent_id:
                self.members.pop(i)
                return True
        return False

    def is_lead(self, agent_id: str) -> bool:
        """Check if the agent is the team lead."""
        for m in self.members:
            if m.agent_id == agent_id and m.role == "lead":
                return True
        return False

    def assign_task(self, task: TeamTask) -> None:
        """Assign a task to the team."""
        self.tasks.append(task)

    def get_tasks_for(self, agent_id: str) -> list[TeamTask]:
        """Get all tasks assigned to a specific agent."""
        return [t for t in self.tasks if t.assigned_to == agent_id]

    def to_dict(self) -> dict[str, Any]:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Team":
        data = dict(data)
        members_data = data.pop("members", [])
        tasks_data = data.pop("tasks", [])
        team = cls(**data)
        team.members = [TeamMember(**m) for m in members_data]
        team.tasks = [TeamTask(**t) for t in tasks_data]
        return team
