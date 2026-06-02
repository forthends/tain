"""AgentIdentity data model — the complete agent resume."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Literal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Proficiency(IntEnum):
    NOVICE = 1
    BEGINNER = 2
    INTERMEDIATE = 3
    ADVANCED = 4
    EXPERT = 5


class AutonomyLevel(IntEnum):
    SUPERVISED = 1     # every action needs human approval
    GUIDED = 2         # most actions auto, critical ones need approval
    TRUSTED = 3        # only destructive actions need approval
    AUTONOMOUS = 4     # self-approves all actions within constraints
    FULL = 5           # no human in the loop


@dataclass
class DomainExpertise:
    domain: str
    proficiency: Proficiency = Proficiency.NOVICE
    evidence: list[str] = field(default_factory=list)
    acquired_at: str = field(default_factory=_now)


@dataclass
class Value:
    name: str
    priority: int = 5               # 1-10
    description: str = ""
    source: str = ""                # "role_assigned" | "self_discovered" | "external_feedback"


@dataclass
class BehaviorConstraints:
    allowed_categories: list[str] = field(default_factory=list)
    blocked_categories: list[str] = field(default_factory=list)
    max_autonomy_level: AutonomyLevel = AutonomyLevel.GUIDED
    requires_human_for: list[str] = field(default_factory=list)

    def requires_human_approval(self, action_category: str) -> bool:
        if action_category in self.blocked_categories:
            return True
        if action_category in self.requires_human_for:
            return True
        return False


@dataclass
class Goal:
    id: str
    title: str
    parent_id: str | None = None
    status: Literal["active", "completed", "abandoned"] = "active"
    progress: float = 0.0           # 0.0 - 1.0
    description: str = ""
    children: list[Goal] = field(default_factory=list)

    def add_child(self, child: Goal) -> None:
        child.parent_id = self.id
        self.children.append(child)


@dataclass
class ExperienceLevel:
    overall: int = 1                # 1-10
    domain_breakdown: dict[str, int] = field(default_factory=dict)


@dataclass
class CollaborationPrefs:
    preferred_roles: list[str] = field(default_factory=list)
    communication_style: str = "direct"
    team_size_preference: int = 3
    availability: Literal["always", "scheduled", "on_demand"] = "on_demand"


@dataclass
class EvolutionEvent:
    timestamp: str = field(default_factory=_now)
    event_type: str = ""
    description: str = ""
    version_from: str = ""
    version_to: str = ""


@dataclass
class AgentIdentity:
    """Complete agent identity — role, expertise, values, constraints, goals, experience."""

    # Core
    agent_id: str
    name: str
    role: str = ""
    role_description: str = ""
    evolution_mode: Literal["specified", "chaos"] = "specified"

    # Expertise
    expertise_domains: list[DomainExpertise] = field(default_factory=list)

    # Values
    values: list[Value] = field(default_factory=list)

    # Constraints
    constraints: BehaviorConstraints = field(default_factory=BehaviorConstraints)

    # Mission & Goals
    mission: str = ""
    goals: list[Goal] = field(default_factory=list)

    # Growth
    skill_catalog: list[str] = field(default_factory=list)       # skill names
    experience: ExperienceLevel = field(default_factory=ExperienceLevel)

    # Collaboration
    collaboration: CollaborationPrefs = field(default_factory=CollaborationPrefs)

    # Personality traits (7 categories, inherited from personality.py model)
    traits: dict[str, list[dict]] = field(default_factory=lambda: {
        "values": [], "communication_style": [], "interests": [],
        "quirks": [], "self_description": [], "relationship_stance": [],
        "growth_orientation": [],
    })

    # History
    evolution_log: list[EvolutionEvent] = field(default_factory=list)

    def awaken_from_role(self, role: str, role_description: str) -> None:
        """Initialize identity fields from a role assignment (Specified mode)."""
        self.role = role
        self.role_description = role_description
        self.mission = f"以 {role} 的身份持续学习和演化，成为该领域的专家"
        self.expertise_domains.append(DomainExpertise(
            domain=role, proficiency=Proficiency.BEGINNER,
            evidence=[f"Assigned role: {role}"],
        ))
        self.values.append(Value(name="专业精神", priority=8, source="role_assigned"))
        self.evolution_log.append(EvolutionEvent(
            event_type="awakening", description=f"Agent awakened with role: {role}",
            version_from="0.0.0", version_to="0.0.1",
        ))

    def add_expertise(self, domain: str, proficiency: Proficiency, evidence: str) -> None:
        existing = next((d for d in self.expertise_domains if d.domain == domain), None)
        if existing:
            if proficiency > existing.proficiency:
                existing.proficiency = proficiency
            existing.evidence.append(evidence)
        else:
            self.expertise_domains.append(DomainExpertise(
                domain=domain, proficiency=proficiency, evidence=[evidence],
            ))

    def upgrade_autonomy(self, new_level: AutonomyLevel, reason: str) -> None:
        self.constraints.max_autonomy_level = new_level
        self.evolution_log.append(EvolutionEvent(
            event_type="autonomy_upgrade",
            description=f"Autonomy upgraded to {new_level.name}: {reason}",
        ))

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)
